"""Shared vision state and template/OCR helpers for daily-style tasks."""

from __future__ import annotations

from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks.map_trade.models import MatchResult, TemplateSpec
from src.tasks.map_trade.vision import Vision
from src.utils import task_vision
from src.utils.calibration import FHD_1080
from src.utils.home_confirmation import (
    HOME_DIMMED_P95_THRESHOLD_DEFAULT,
    HOME_GACHA_OCR_RELATIVE_ROI,
    HOME_LEFT_COLUMN_OCR_RELATIVE_ROI,
    HOME_LEFT_COLUMN_REQUIRED_HITS,
    home_confirmation_passes,
    home_gacha_ocr_with_fallback,
    home_left_column_hits,
    home_left_column_brightness,
)
from src.utils.image_utils import to_gray
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.press_next import Next, press_next
from src.utils.wait_limits import LOADING_MAX_SECONDS, STUCK_SECONDS, is_loading_dark, load_wait, scene_at_press

REFERENCE_WIDTH = FHD_1080.width

REFERENCE_HEIGHT = FHD_1080.height

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TEMPLATE_DIR = PROJECT_ROOT / "recognition-assets" / "template-assets"

# The top-left back arrow itself (recovery presses the same spot): the last
# remedy when the usual back point and Esc both left a page up.
BACK_ARROW_REFERENCE_POINT = (150, 50)

BACK_LOOK_SECONDS = 2.5

LOADING_TEMPLATE = TemplateSpec(
    name="ui_loading_black",
    file_name="image/UI_loading_black.png",
    threshold_key="加载页面阈值",
    default_threshold=0.72,
)

# How long the loading screen may stay: it is the game working, not a frozen
# or unknown screen (Leo 2026-10-15 「我說的10秒是卡死 或者辨識不到」「你單純等
# 載入怎麼可以改成只等10秒」), so the saved 「loading 消失等待秒数」 counts only
# when it is longer than LOADING_MAX_SECONDS.
def loading_gone_seconds(config) -> float:
    try:
        seconds = float(config.get("loading 消失等待秒数", LOADING_MAX_SECONDS))
    except (TypeError, ValueError):
        seconds = LOADING_MAX_SECONDS
    return max(seconds, LOADING_MAX_SECONDS)


class TaskVisionMixin:
    def _init_vision_state(self) -> None:
        self._templates: dict[str, np.ndarray] = {}
        self._template_masks: dict[str, np.ndarray | None] = {}
        self._missing_template_names: set[str] = set()
        self._match_error_names: set[str] = set()
        self._match_pause_until = 0.0

    def _quick_vision(self) -> Vision:
        vision = getattr(self, "_quick_hunt_vision", None)
        if vision is None:
            vision = Vision(self)
            self._quick_hunt_vision = vision
        return vision

    _normalize_text = staticmethod(normalize_ocr_text)

    _to_gray = staticmethod(to_gray)

    def _status_set(self, key: str, value) -> None:
        try:
            self.info_set(key, value)
        except AttributeError:
            pass

    def _back_to_home(
        self,
        name: str,
        back_point: tuple[int, int],
        page_name: str,
        page_seen,
    ) -> bool:
        """Press the top-left back on a home sub-page until home shows.

        A back press can be swallowed by the page's own animation (player
        2026-10-31: 装备抽抽乐 stayed up after its back press and the tool
        waited 46 s for home, then failed a draw that was done; the guild page
        had the same, BUG-20260901-02).  press_next presses again only while
        ``page_seen`` still reads the page, then Esc, then the arrow itself;
        a screen that moved on (loading, a popup over home) is never pressed
        and gets the full home wait.  Still on the page after all: False at
        once, no long wait (Leo 2026-10-31 「12秒離開 補點 esc」).
        """

        def loading(frame) -> bool:
            return is_loading_dark(frame) or self._passes(self._match(frame, LOADING_TEMPLATE), LOADING_TEMPLATE)

        outcome = press_next(
            name,
            lambda: self._click_reference(*back_point, after_sleep=0.5),
            [
                Next("主页", lambda frame: self._home_confirmation_ok(frame, name), goal=True),
                Next("加载画面", loading, loading=True),
                Next(page_name, page_seen, before=True),
            ],
            capture=self.capture_frame,
            sleep=self.sleep,
            log=self.log_info,
            key=("Esc", lambda: self.tap_escape(after_sleep=0.5)),
            fixed=lambda: self._click_reference(*BACK_ARROW_REFERENCE_POINT, after_sleep=0.5),
            # Four looks and the presses between them: about NO_RESPONSE_SECONDS
            # on a page that stays up (Leo 2026-10-31 「12秒離開 補點 esc」).
            timeout=BACK_LOOK_SECONDS,
            retry_after=0.5,
        )
        if outcome.reached:
            return True
        if outcome.screen == page_name:
            self.log_info(f"{name}：补按、Esc、返回箭头后还在{page_name}。")
            return False
        if self._wait_for_home_confirmation(name):
            return True
        # Neither home nor the page: at least one more press (Leo 2026-10-31
        # 「總之最少都要補按」).
        self.log_info(f"{name}：按了返回没看到主页（{outcome.screen}），补按一次返回。")
        self._click_reference(*back_point, after_sleep=0.5)  # 不用确认：下一行等主页
        return self._wait_for_home_confirmation(name)

    def _home_confirmation_ok(self, frame, name: str) -> bool:
        return self._home_confirmation_signals(frame, f"{name} 抽抽乐")[0]

    def _home_confirmation_signals(
        self,
        frame,
        ocr_name: str,
    ) -> tuple[bool, int, float, str]:
        vision = self._quick_vision()
        left_text = vision.ocr_text(
            frame,
            f"{ocr_name} 左列",
            relative_roi=HOME_LEFT_COLUMN_OCR_RELATIVE_ROI,
        )
        left_hits = home_left_column_hits(left_text)
        p95_brightness = home_left_column_brightness(frame)
        gacha_result = home_gacha_ocr_with_fallback(
            lambda scale: vision.ocr_text(
                frame,
                f"{ocr_name} x{scale:g}",
                relative_roi=HOME_GACHA_OCR_RELATIVE_ROI,
                ocr_scale=scale,
            )
        )
        gacha_text = gacha_result.text
        self._status_set(f"{ocr_name} OCR 尝试", gacha_result.trace)
        confirmed = home_confirmation_passes(
            left_hits=left_hits,
            required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
            brightness=p95_brightness,
            brightness_threshold=self._home_p95_threshold(),
            gacha_ocr_text=gacha_text,
        )
        return confirmed, left_hits, p95_brightness, gacha_text

    def _click_reference(self, x: int, y: int, after_sleep: float = 0.0):
        self.operate_click(
            max(0.0, min(1.0, x / REFERENCE_WIDTH)),
            max(0.0, min(1.0, y / REFERENCE_HEIGHT)),
            after_sleep=after_sleep,
        )

    def _wait_loading_or_template(
        self,
        task_name: str,
        spec: TemplateSpec,
        name: str,
        interval: float = 0.35,
    ) -> tuple[str, bool]:
        end_at = monotonic() + float(self.config.get("loading 出现等待秒数", 6.0))
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            self.info_set(name, f"{result.score:.3f}")
            if self._passes(result, spec):
                return "target", True

            loading = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{task_name}_loading_appear", f"{loading.score:.3f}")
            if self._passes(loading, LOADING_TEMPLATE):
                return self._wait_loading_gone_or_template(
                    task_name,
                    spec,
                    name,
                    interval=interval,
                )
            self.sleep(interval)

        return "none", False

    def _wait_loading_gone_or_template(
        self,
        task_name: str,
        spec: TemplateSpec,
        name: str,
        interval: float = 0.35,
    ) -> tuple[str, bool]:
        end_at = monotonic() + loading_gone_seconds(self.config)
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            self.info_set(name, f"{result.score:.3f}")
            if self._passes(result, spec):
                return "target", True

            loading = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{task_name}_loading_gone", f"{loading.score:.3f}")
            if not self._passes(loading, LOADING_TEMPLATE):
                return "loading", False
            self.sleep(interval)

        self.log_info(f"{task_name}：UI_loading_black.png 未在限定时间内消失。")
        return "stuck", False

    def _frame_confirms_home(self, frame, name: str) -> bool:
        confirmed, _left_hits, _p95, _gacha = self._home_confirmation_signals(
            frame,
            f"{name} 主页误检",
        )
        return confirmed

    def _wait_loading_or_template_or_ocr(
        self,
        task_name: str,
        spec: TemplateSpec,
        keywords: list[str],
        name: str,
        interval: float = 0.5,
        reject_template_on_home: bool = False,
    ) -> tuple[str, bool, str]:
        end_at = monotonic() + float(self.config.get("loading 出现等待秒数", 6.0))
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            text = self._ocr_text(frame, name=name)
            last_text = text
            self.info_set(f"{name} 模板", f"{result.score:.3f}")
            if (
                reject_template_on_home
                and self._passes(result, spec)
                and self._frame_confirms_home(frame, name)
            ):
                # BUG-20260901-02：金色签到弹窗模板在主页/切页帧打出 0.771
                # 误越过 0.76 阈值，导致脚本在进入公会页前就判定签到成功；
                # 确认主页三信号的帧不算命中。
                self.info_set(f"{name} 模板", f"{result.score:.3f} 主页帧误命中，忽略")
                self.log_info(
                    f"{task_name}：{spec.name} 模板在主页帧误命中"
                    f"（{result.score:.3f}），忽略并继续等待。"
                )
            elif self._passes(result, spec) or self._keyword_match_count(text, keywords) >= 1:
                return "target", True, text

            loading = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{task_name}_loading_appear", f"{loading.score:.3f}")
            if self._passes(loading, LOADING_TEMPLATE):
                return self._wait_loading_gone_or_template_or_ocr(
                    task_name,
                    spec,
                    keywords,
                    name,
                    last_text=last_text,
                    interval=interval,
                )
            self.sleep(interval)

        return "none", False, last_text

    def _wait_loading_gone_or_template_or_ocr(
        self,
        task_name: str,
        spec: TemplateSpec,
        keywords: list[str],
        name: str,
        last_text: str = "",
        interval: float = 0.5,
    ) -> tuple[str, bool, str]:
        end_at = monotonic() + loading_gone_seconds(self.config)
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            text = self._ocr_text(frame, name=name)
            last_text = text
            self.info_set(f"{name} 模板", f"{result.score:.3f}")
            if self._passes(result, spec) or self._keyword_match_count(text, keywords) >= 1:
                return "target", True, text

            loading = self._match(frame, LOADING_TEMPLATE)
            self.info_set(f"{task_name}_loading_gone", f"{loading.score:.3f}")
            if not self._passes(loading, LOADING_TEMPLATE):
                return "loading", False, last_text
            self.sleep(interval)

        self.log_info(f"{task_name}：UI_loading_black.png 未在限定时间内消失。")
        return "stuck", False, last_text

    def _wait_for_template(
        self,
        spec: TemplateSpec,
        timeout: float,
        name: str,
        interval: float = 0.35,
    ) -> bool:
        end_at = monotonic() + max(0.0, timeout)
        last_score = -1.0
        while monotonic() <= end_at:
            frame = self.capture_frame()
            result = self._match(frame, spec)
            last_score = result.score
            self.info_set(name, f"{result.score:.3f}")
            if self._passes(result, spec):
                return True
            self.sleep(interval)

        self.info_set(name, f"{last_score:.3f}")
        return False

    def _wait_for_ocr_keywords(
        self,
        keywords: list[str],
        timeout: float,
        minimum_matches: int,
        name: str,
        interval: float = 0.5,
    ) -> tuple[bool, str]:
        end_at = monotonic() + max(0.0, timeout)
        last_text = ""
        while monotonic() <= end_at:
            frame = self.capture_frame()
            text = self._ocr_text(frame, name=name)
            last_text = text
            count = self._keyword_match_count(text, keywords)
            self.info_set(f"{name} 关键字", f"{count}/{len(keywords)}")
            if count >= minimum_matches:
                return True, text
            self.sleep(interval)
        return False, last_text

    def _wait_for_home_confirmation(
        self,
        name: str,
        interval: float = 0.35,
        timeout: float | None = None,
    ) -> bool:
        if timeout is None:
            timeout = float(self.config.get("主页确认等待秒数", 10.0))
        # Going home passes a loading screen (leaving a page or a field): a
        # full home wait is a load wait (Leo 2026-10-15 「你單純等載入怎麼可以
        # 改成只等10秒」).  A shorter one is a quick look and stays as given.
        wait = load_wait(monotonic(), timeout, before=scene_at_press(self)) if timeout >= STUCK_SECONDS else None
        end_at = monotonic() + max(0.0, timeout)
        last_left_hits = 0
        last_p95 = 0.0
        last_gacha_text = ""
        while True:
            frame = self.capture_frame()
            if wait is not None and is_loading_dark(frame):
                if wait.over(frame, monotonic(), loading=True):
                    break
                self.info_set(f"{name} 左列关键词", "加载中")
                self.sleep(interval)
                continue
            (
                confirmed,
                last_left_hits,
                last_p95,
                last_gacha_text,
            ) = self._home_confirmation_signals(frame, f"{name} 抽抽乐")
            self.info_set(
                f"{name} 左列关键词",
                f"{last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}",
            )
            self.info_set(
                f"{name} 亮度p95",
                f"{last_p95:.0f}/{self._home_p95_threshold():.0f}",
            )
            self.info_set(f"{name} 抽抽乐 OCR", last_gacha_text or "-")
            if confirmed:
                return True
            self.clear_temporary_home_announcement_if_needed(
                left_hits=last_left_hits,
                required_left_hits=HOME_LEFT_COLUMN_REQUIRED_HITS,
                brightness=last_p95,
                brightness_threshold=self._home_p95_threshold(),
                gacha_ocr_text=last_gacha_text,
                context=name,
            )
            if wait is not None:
                if wait.over(frame, monotonic()):
                    break
            elif monotonic() > end_at:
                break
            self.sleep(interval)

        self.log_info(
            f"{name}：未同时确认左列关键词、亮度和抽抽乐文字，"
            f"left={last_left_hits}/{HOME_LEFT_COLUMN_REQUIRED_HITS}, "
            f"p95={last_p95:.0f}/{self._home_p95_threshold():.0f}, "
            f"ocr={last_gacha_text or '-'}。"
        )
        return False

    @staticmethod
    def _empty_match() -> MatchResult:
        return MatchResult(-1.0, (0, 0), (0, 0))

    def _match_best(
        self,
        frame,
        specs: tuple[TemplateSpec, ...],
    ) -> tuple[MatchResult, TemplateSpec]:
        best = self._empty_match()
        best_spec = specs[0]
        for spec in specs:
            result = self._match(frame, spec)
            if result.score > best.score:
                best = result
                best_spec = spec
        return best, best_spec

    def _match(self, frame, spec: TemplateSpec) -> MatchResult:
        empty = MatchResult(-1.0, (0, 0), (0, 0))
        if monotonic() < self._match_pause_until:
            return empty

        try:
            return task_vision.match_template(
                frame,
                spec,
                self.config,
                TEMPLATE_DIR,
                cache=self._templates,
                min_size=8,
                loader=lambda _template_dir, spec: (
                    self._load_template(spec),
                    self._load_template_mask(spec),
                ),
            )
        except RuntimeError as exc:
            if spec.name not in self._missing_template_names:
                self._missing_template_names.add(spec.name)
                self.log_warning(str(exc), notify=True)
            return empty
        except (cv2.error, MemoryError) as exc:
            self._match_pause_until = monotonic() + 2.0
            message = f"图像匹配内存不足，暂停识别2秒：{spec.name}"
            self.info_set("匹配错误", message)
            if spec.name not in self._match_error_names:
                self._match_error_names.add(spec.name)
                self.log_warning(f"{message}；{exc}", notify=True)
            return empty

    def _load_template(self, spec: TemplateSpec) -> np.ndarray:
        return task_vision.load_template(TEMPLATE_DIR, spec, cache=self._templates)[0]

    def _load_template_mask(self, spec: TemplateSpec) -> np.ndarray | None:
        return task_vision.load_template(TEMPLATE_DIR, spec, cache=self._templates)[1]

    def _passes(self, result: MatchResult, spec: TemplateSpec) -> bool:
        return task_vision.passes_match(result, spec, self.config)

    def _ocr_text(self, frame, name: str) -> str:
        try:
            boxes = self.ocr(
                frame=frame,
                threshold=float(self.config.get("日常 OCR 阈值", 0.2)),
                target_height=720,
                log=False,
                name=name,
            )
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.info_set(f"{name} OCR 错误", str(exc))
            # Audit #64: an OCR error read as "no text" silently; written to
            # the log once per name, so a problem summary shows the cause.
            reported = self.__dict__.setdefault("_ocr_error_names", set())
            if name not in reported:
                reported.add(name)
                self.log_warning(f"{name}：文字识别出错，当作没读到字；{exc}")
            return ""

        return " ".join(box.name for box in boxes if getattr(box, "name", ""))

    @staticmethod
    def _keyword_match_count(text: str, keywords: list[str]) -> int:
        return keyword_match_count(text, keywords)

    def _home_p95_threshold(self) -> float:
        return float(self.config.get("主页压暗阈值", HOME_DIMMED_P95_THRESHOLD_DEFAULT))
