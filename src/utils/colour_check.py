"""Does the capture show the game's own colours?

Leo 2026-09-30: HDR and similar settings must not quietly break the
judgement.  Windows HDR itself is undone by the capture (src/capture/hdr_wgc);
RTX HDR, Auto HDR or a driver colour filter can still change the pixels.  The
three currency icons in the home top bar are fixed, opaque sprites, the same
for every player: their colour quartiles against a normal-colour reference
(2K 2026-09-30) tell whether absolute colour checks can be trusted.

Simulated on live frames: resampling to 720p-4K moved the quartiles by at
most 5 levels, mild vibrance/tint/sharpen 5-10, while HDR-like brightening,
darkening or saturation changes moved them 14-65.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.utils.image_utils import template_match_response

ANCHOR_DIR = (
    Path(__file__).resolve().parents[2] / "recognition-assets" / "template-assets" / "colour_check"
)
# name, label, 1920x1080 reference box of the icon.
ANCHORS = (
    ("gem", "钻石", (1031, 44, 31, 24)),
    ("coin", "金币", (1163, 42, 30, 30)),
    ("silver", "银币", (1339, 40, 33, 34)),
)
# Pills could shift sideways with longer numbers; keep the vertical search tight.
SEARCH_PAD_X = 60
SEARCH_PAD_Y = 12
ANCHOR_MIN_MATCH = 0.7
QUARTILES = (25, 50, 75)
COLOUR_DISTANCE_MAX = 12.0


@dataclass(frozen=True)
class ColourCheck:
    distance: float | None  # median over the icons found; None = none found
    detail: str

    @property
    def distorted(self) -> bool:
        return self.distance is not None and self.distance > COLOUR_DISTANCE_MAX


def _quartiles(pixels: np.ndarray) -> np.ndarray:
    return np.array([np.percentile(pixels[:, c], QUARTILES) for c in range(3)])


@lru_cache(maxsize=1)
def _anchors():
    loaded = []
    for name, label, box in ANCHORS:
        patch = cv2.imread(str(ANCHOR_DIR / f"{name}.png"))
        mask = cv2.imread(str(ANCHOR_DIR / f"{name}_mask.png"), cv2.IMREAD_GRAYSCALE)
        if patch is None or mask is None:
            continue
        loaded.append((label, box, patch, mask, _quartiles(patch[mask > 0])))
    return tuple(loaded)


def check_capture_colours(frame) -> ColourCheck:
    """Compare the home top-bar icons with their normal colours."""

    if frame is None or frame.size == 0:
        return ColourCheck(None, "无画面")
    reference = cv2.resize(frame[:, :, :3], (1920, 1080), interpolation=cv2.INTER_AREA)
    distances = []
    parts = []
    for label, (x, y, w, h), patch, mask, expected in _anchors():
        left, top = max(0, x - SEARCH_PAD_X), max(0, y - SEARCH_PAD_Y)
        area = reference[top : y + h + SEARCH_PAD_Y, left : x + w + SEARCH_PAD_X]
        if area.shape[0] < h or area.shape[1] < w:
            continue
        scores = template_match_response(area, patch, mask, zero_mean=True)
        _low, score, _low_at, (dx, dy) = cv2.minMaxLoc(scores)
        if score < ANCHOR_MIN_MATCH:
            parts.append(f"{label}未找到({score:.2f})")
            continue
        found = area[dy : dy + h, dx : dx + w]
        distance = float(np.abs(_quartiles(found[mask > 0]) - expected).mean())
        distances.append(distance)
        parts.append(f"{label}{distance:.1f}")
    if not distances:
        return ColourCheck(None, "；".join(parts) or "无参照图")
    return ColourCheck(float(np.median(distances)), "；".join(parts))


# One distorted read is not enough (live 10-10: the first frame after the
# capture started or the window was resized read 钻石154.4；金币109.5；
# 银币152.2, the next ones 钻石2.8；金币0.9；银币5.3).  The first frame at a
# new capture size never counts, and two distorted reads in a row are needed.
DISTORTED_READS_NEEDED = 2
RECHECK_SECONDS = 1.0
MAX_READS = 3

_capture_shape: tuple[int, ...] | None = None


def _new_capture_size(frame) -> bool:
    """True for the first frame of this process or of a new capture size."""
    global _capture_shape
    shape = None if frame is None else tuple(frame.shape[:2])
    changed = shape != _capture_shape
    _capture_shape = shape
    return changed


def forget_capture() -> None:
    """The capture restarted: its next frame is a first frame again."""
    global _capture_shape
    _capture_shape = None


def check_settled(frame, capture, sleep, wait: float = RECHECK_SECONDS) -> ColourCheck:
    """check_capture_colours that warns only on lasting distortion.

    A distorted read is looked at again on fresh frames from ``capture``; it
    stands only after DISTORTED_READS_NEEDED distorted reads in a row, not
    counting the first frame at a new capture size.  Any normal read, or a
    read without the top bar, ends the check with that read.
    """

    counted = 0
    for attempt in range(MAX_READS):
        if attempt:
            sleep(wait)
            frame = capture()
        first_frame = _new_capture_size(frame)
        check = check_capture_colours(frame)
        if not check.distorted:
            return check
        if not first_frame:
            counted += 1
        if counted >= DISTORTED_READS_NEEDED:
            return check
    return ColourCheck(None, f"{check.detail}（只偶尔偏色，不算）")


_last: ColourCheck | None = None


def remember(check: ColourCheck) -> None:
    global _last
    _last = check


def last_check() -> ColourCheck | None:
    """The latest check of this process (None before the first home screen)."""
    return _last


def distorted_colour_warning(check: ColourCheck) -> str:
    return (
        f"画面颜色和游戏原本的颜色差很多（偏差 {check.distance:.0f}，正常 ≤ {COLOUR_DISTANCE_MAX:.0f}）："
        "可能开着 RTX HDR、自动 HDR、显卡的鲜艳度/滤镜或色彩调整。颜色相关的判断可能出错，"
        "爛装分解这次只判断不分解；建议关闭后再跑。"
    )
