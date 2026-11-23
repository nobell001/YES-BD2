"""Draw a red ◆「!」 badge the way the game shows it (活动 / 通行证 lists).

find_red_badges wants the diamond and its light 「!」 (Leo's 4K 11-23: red
card art without the mark was clicked as a badge), so a plain red square no
longer stands in for one.
"""

import cv2
import numpy as np

BADGE_RED = (40, 40, 230)  # BGR, like the live badge face
BADGE_MARK = (200, 225, 255)  # BGR, the cream 「!」


def draw_badge(frame, center_x: int, center_y: int, scale: float = 1.0) -> None:
    """A 17 px (at 1080p) red diamond with a 「!」, centred at frame pixels."""
    half = 8.5 * scale
    diamond = np.array(
        [
            (center_x, center_y - half),
            (center_x + half, center_y),
            (center_x, center_y + half),
            (center_x - half, center_y),
        ],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(frame, diamond, BADGE_RED)
    bar = max(1, round(1.2 * scale))
    top, bottom = round(center_y - 5 * scale), round(center_y + 1.5 * scale)
    frame[top:bottom, center_x - bar : center_x + bar] = BADGE_MARK
    dot = round(center_y + 3 * scale)
    frame[dot : dot + max(1, round(2 * scale)), center_x - bar : center_x + bar] = BADGE_MARK
