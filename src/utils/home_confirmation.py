from dataclasses import dataclass
from typing import Callable

import numpy as np

from src.utils import game_language
from src.utils.calibration import FHD_1080
from src.utils.image_utils import relative_roi_frame, to_gray
from src.utils.ocr_utils import normalize_ocr_text

HOME_GACHA_OCR_REFERENCE_ROI = (110, 993, 95, 54)
HOME_GACHA_OCR_RELATIVE_ROI = (
    110 / FHD_1080.width,
    993 / FHD_1080.height,
    205 / FHD_1080.width,
    1047 / FHD_1080.height,
)
HOME_GACHA_OCR_KEYWORD = "抽抽乐"
HOME_GACHA_OCR_SCALES = (1.0, 2.0, 3.0)
HOME_GACHA_OCR_ALIASES = (HOME_GACHA_OCR_KEYWORD,)
HOME_ANNOUNCEMENT_CLEAR_REFERENCE_POINT = (169, 615)
HOME_ANNOUNCEMENT_CLEAR_RELATIVE_POINT = (
    HOME_ANNOUNCEMENT_CLEAR_REFERENCE_POINT[0] / FHD_1080.width,
    HOME_ANNOUNCEMENT_CLEAR_REFERENCE_POINT[1] / FHD_1080.height,
)

# 左上图标列整列大 ROI（我的小屋/格鲁TALK/街机游戏）。检测模型需要上下文，
# 禁止单独拆出单标签小 ROI（实测丢字/返回空）。来源：BUG-20260829-01 实测标定。
HOME_LEFT_COLUMN_OCR_REFERENCE_ROI = (110, 165, 430, 155)
HOME_LEFT_COLUMN_OCR_RELATIVE_ROI = (
    110 / FHD_1080.width,
    165 / FHD_1080.height,
    540 / FHD_1080.width,
    320 / FHD_1080.height,
)
# 每组关键词为简体（OCR 只识别简体中文，2026-08-29 取消繁体识别别名）；
# 子串命中即该组计 1 票。
HOME_LEFT_COLUMN_KEYWORD_GROUPS = (
    ("我的小屋",),
    ("格鲁TALK",),
    ("街机游戏",),
)
HOME_LEFT_COLUMN_REQUIRED_HITS = 2

# 左列灰度（每行 p99，见 home_left_column_brightness）：未压暗 255、0.5x 公告压暗约 126，阈值 185 分离，
# 且不随主页背景场景变化（旧模板相对亮度比值依赖采集场景，已废弃）。
HOME_DIMMED_P95_THRESHOLD_DEFAULT = 185.0
# Below this the picture is a loading screen, not a grey one: no rescaling.
WHITEST_MIN = 90.0
# White seen somewhere on screen: the picture's colours are normal.
WHITE_SEEN = 235.0
# Upper icon row (我的小屋…) vs lower row (经营管理…): reference y 240 of 165-320.
HOME_LEFT_COLUMN_ROW_SPLIT = (240 - 165) / 155


@dataclass(frozen=True)
class HomeGachaOcrResult:
    text: str
    selected_scale: float | None
    attempts: tuple[tuple[float, str], ...]

    @property
    def matched(self) -> bool:
        return self.selected_scale is not None

    @property
    def trace(self) -> str:
        attempts = ", ".join(
            f"x{scale:g}={text or '-'}" for scale, text in self.attempts
        )
        selected = (
            f"采用x{self.selected_scale:g}"
            if self.selected_scale is not None
            else "未命中"
        )
        return f"{selected}; {attempts}"


def home_gacha_ocr_with_fallback(
    read_text: Callable[[float], object],
    scales: tuple[float, ...] = HOME_GACHA_OCR_SCALES,
) -> HomeGachaOcrResult:
    """Read the fixed gacha ROI with bounded same-frame upscale fallbacks."""
    attempts: list[tuple[float, str]] = []
    first_nonempty = ""
    for scale in scales:
        text = str(read_text(float(scale)) or "").strip()
        attempts.append((float(scale), text))
        if text and not first_nonempty:
            first_nonempty = text
        if home_gacha_ocr_matches(text):
            return HomeGachaOcrResult(text, float(scale), tuple(attempts))
    return HomeGachaOcrResult(first_nonempty, None, tuple(attempts))


def home_gacha_ocr_matches(text: object) -> bool:
    game_language.note_text(text)
    normalized_text = normalize_ocr_text(text)
    return any(
        normalize_ocr_text(keyword) in normalized_text
        for keyword in HOME_GACHA_OCR_ALIASES
    )


def home_left_column_hits(text: object) -> int:
    """Count left-column keyword groups present in the same-frame OCR text."""
    game_language.note_text(text)
    normalized_text = normalize_ocr_text(text)
    hits = 0
    for aliases in HOME_LEFT_COLUMN_KEYWORD_GROUPS:
        if any(
            normalize_ocr_text(alias) in normalized_text
            for alias in aliases
        ):
            hits += 1
    return hits


def home_left_column_brightness(frame) -> float:
    """Dimming metric of the left-column ROI: the dimmer row's 99th-percentile grey.

    The white icon labels are only ~4-6 % of a row, so p95 followed the
    wallpaper behind them: live 4K 2026-09-30 a dark home wallpaper put the
    upper row's p95 at 158-171 and home was taken for an announcement for good.
    p99 still reads the labels (255 clean, <= ~130 under a 0.5x dim) and stays
    low on the pass page (49) and the other pages checked (<= 200, which the
    OCR signals already reject).
    """
    if frame is None:
        return 0.0
    _left, _top, crop = relative_roi_frame(frame, HOME_LEFT_COLUMN_OCR_RELATIVE_ROI)
    if crop.size == 0:
        return 0.0
    gray = to_gray(crop)
    whitest = screen_whitest(frame)
    # Both icon rows must be bright.  The pass page dims home but its bright
    # season cards cover the lower row, so the whole-ROI p95 read 212 and a
    # pass page passed as home (live 2K 2026-09-29: upper row 43, home 222).
    split = max(1, round(gray.shape[0] * HOME_LEFT_COLUMN_ROW_SPLIT))
    if split >= gray.shape[0]:
        raw = float(np.percentile(gray, 99))
    else:
        raw = float(
            min(np.percentile(gray[:split], 99), np.percentile(gray[split:], 99))
        )
    return relative_to_whitest(raw, whitest)


def screen_whitest(frame) -> float:
    """The whitest grey anywhere on the picture (every 2nd pixel: thin
    white text on a notice must still count)."""
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return 0.0
    return float(to_gray(frame)[::2, ::2].max())


def relative_to_whitest(raw: float, whitest: float) -> float:
    """``raw`` (0-255) as if the picture's whitest were pure white.

    Player summary v0.2.21 2026-10-29 (4K, HDR on): leaving the square,
    home never passed (cause inferred, no picture of it).  With HDR (or a dim
    filter) the whole picture comes out greyer, white labels included: at
    0.6x they read 153, under the 185 line for good, the same as a notice
    dimming home.  A notice dims home but not itself: its own text and ✕
    stay white, so with white anywhere on screen nothing changes.  Only a
    picture with no white at all is judged against its own whitest: a grey
    home then reads 255.  A near-black picture (loading) stays as it is.
    """
    return float(min(255.0, raw * grey_picture_gain(whitest)))


def grey_picture_gain(whitest: float) -> float:
    """How much a picture with no white anywhere is brightened to be judged
    (1.0 for a normal picture or a loading screen); see relative_to_whitest."""
    if whitest < WHITEST_MIN or whitest >= WHITE_SEEN:
        return 1.0
    return 255.0 / whitest


def home_confirmation_passes(
    *,
    left_hits: int,
    required_left_hits: int,
    brightness: float,
    brightness_threshold: float,
    gacha_ocr_text: object,
) -> bool:
    """Require all three same-frame signals before confirming the global home page.

    brightness is a scene-independent dimming metric compared against
    brightness_threshold: the OCR pipeline passes the left-column grayscale
    p99 per row (0-255, threshold 185); the legacy template bridge passes the
    template-relative brightness ratio (0-1, threshold 0.75).
    """
    return (
        int(left_hits) >= int(required_left_hits)
        and float(brightness) >= float(brightness_threshold)
        and home_gacha_ocr_matches(gacha_ocr_text)
    )


def home_temporary_announcement_detected(
    *,
    left_hits: int,
    required_left_hits: int,
    brightness: float,
    brightness_threshold: float,
    gacha_ocr_text: object,
) -> bool:
    """Detect a dimmed global home page covered by a temporary announcement."""
    return (
        int(left_hits) >= int(required_left_hits)
        and float(brightness) < float(brightness_threshold)
        and home_gacha_ocr_matches(gacha_ocr_text)
    )
