"""Did a round of presses change the screen at all?

The same small grey copy and the same limit as the generic way home
(src/tasks/recovery.py ``_thumb`` / ``_frames_differ``): a mean grey change
of FRAME_CHANGE_MIN_DIFF on a 1/8 copy is a new screen, an idle animation is
not.  Used where a whole round of remedies (press, press again, Esc) would
otherwise be repeated on a screen that took none of them (player v0.4.6
2026-11-20: the 跑商 出售 page, the same back press for 41 minutes).
"""

from __future__ import annotations

import numpy as np

FRAME_CHANGE_MIN_DIFF = 8.0


def small_screen(frame) -> np.ndarray | None:
    """A 1/8 grey copy of ``frame``; None when there is no picture."""
    if frame is None or getattr(frame, "size", 0) == 0 or getattr(frame, "ndim", 0) < 2:
        return None
    if frame.ndim == 2:
        return frame[::8, ::8].astype(np.float32)
    return frame[::8, ::8, :3].mean(axis=2)


def screen_changed(before, after) -> bool:
    """True when ``after`` is another screen than ``before``.

    Not knowing (a picture missing, a different size) counts as changed, so a
    caller never gives up on a guess.
    """
    if before is None or after is None or before.shape != after.shape:
        return True
    return float(np.abs(before - after).mean()) >= FRAME_CHANGE_MIN_DIFF
