"""The game is running but draws nothing: only flat colours, never a page.

Leo's 4K 桌面分身 2026-11-20 18:44-19:06 (local), v0.4.9 一键完成日常:
Google Play Games failed to start with the first game window
(「ActionRequiredShutdownClientProcess」), the game closed itself and Play
Games opened it again.  That second game had a picture size of 0 from its
first second on: its own log (Player.log) wrote
「RenderTexture.Create failed: width & height must be larger than 0」
160,633 times in 21 minutes, and the window showed only flat colours
(light grey, dark red) flashing in turn.  The game itself logged in and
walked into town, but every capture was a flat colour, so the auto-login
never saw a login page or 主页 and only warned every 3 minutes until Leo
closed the clone by hand (「我桌面分身卡了」「一直不同顏色閃」).

The tool cannot make the game build its picture: it can only see that the
game draws nothing and open it again (Leo 「不能避免嗎」).  Two signs, both
needed, so a black loading screen (flat too, and the game working) is never
taken for it:

* the game's own log keeps writing the size-0 line (proof, not a guess);
* every capture is flat: nearly all of it one or two colours.

Both for ``NO_PICTURE_SECONDS`` (past the 10 s stuck limit) make the call.
When the log cannot be read at all, flat captures alone count, but only
after ``NO_PICTURE_FALLBACK_SECONDS`` (past the 45 s loading limit).
"""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import numpy as np

from src.utils.wait_limits import LOADING_MAX_SECONDS, STUCK_SECONDS

ZERO_SIZE_LINE = b"RenderTexture.Create failed: width & height must be larger than 0"
# The game wrote it about 130 times a second (2026-11-20); a few new ones
# between two looks a second apart is the game failing every frame.
ZERO_SIZE_LINES_PER_LOOK = 3
NO_PICTURE_SECONDS = STUCK_SECONDS + 5.0
NO_PICTURE_FALLBACK_SECONDS = LOADING_MAX_SECONDS + 15.0
# Read at most this much of what the log grew by since the last look.
LOG_READ_BYTES = 256 * 1024
# A capture is flat when this share of a 1/8 thumbnail falls in its two
# most common colours (16 levels per channel).  The 2026-11-20 frames: a
# flat square between black bars, 100%.  Real pages, title and loading art
# (tests/fixtures/pages.json) stay well under it.
FLAT_SHARE = 0.99
FLAT_LEVEL = 16


def player_log_path() -> Path | None:
    """The game's own log (Unity Player.log) of this Windows user."""
    home = os.environ.get("USERPROFILE")
    if not home:
        return None
    return Path(home) / "AppData" / "LocalLow" / "Gamfs" / "BrownDust II" / "Player.log"


def flat_picture(frame) -> bool:
    """Nearly all of ``frame`` is one or two flat colours (nothing drawn)."""
    if frame is None or getattr(frame, "ndim", 0) < 2 or getattr(frame, "size", 0) == 0:
        return False
    small = np.asarray(frame)[::8, ::8]
    if small.ndim == 2:
        codes = (small // FLAT_LEVEL).astype(np.int32).ravel()
    else:
        quant = (small[..., :3] // FLAT_LEVEL).astype(np.int32)
        codes = (quant[..., 0] * 256 + quant[..., 1] * 16 + quant[..., 2]).ravel()
    if codes.size == 0:
        return False
    counts = np.bincount(codes)
    top_two = np.sort(counts)[-2:].sum()
    return float(top_two) / float(codes.size) >= FLAT_SHARE


class ZeroSizeLog:
    """New size-0 lines the game's log got since the last look."""

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else player_log_path()
        self._offset: int | None = None

    def new_lines(self) -> int | None:
        """How many size-0 lines were added since the last call; None when
        the log cannot be read (no file, no access)."""
        if self.path is None:
            return None
        try:
            size = self.path.stat().st_size
            start = 0 if self._offset is None or size < self._offset else self._offset
            start = max(start, size - LOG_READ_BYTES)
            with open(self.path, "rb") as log:
                log.seek(start)
                chunk = log.read(size - start)
        except OSError:
            self._offset = None
            return None
        self._offset = size
        return chunk.count(ZERO_SIZE_LINE)


class NoPictureWatch:
    """Looks one capture at a time; ``look`` is True once the game has drawn
    nothing for long enough (see the module notes)."""

    def __init__(self, log: ZeroSizeLog | None = None, clock=monotonic):
        self.log = log if log is not None else ZeroSizeLog()
        self.clock = clock
        self.since: float | None = None
        self.proof = ""

    def reset(self) -> None:
        self.since = None
        self.proof = ""

    def look(self, frame) -> bool:
        lines = self.log.new_lines()
        if not flat_picture(frame):
            self.reset()
            return False
        if lines is None:
            limit, proof = NO_PICTURE_FALLBACK_SECONDS, "截图一直是纯色"
        elif lines >= ZERO_SIZE_LINES_PER_LOOK:
            limit, proof = NO_PICTURE_SECONDS, "游戏日志一直写画面大小为 0，截图一直是纯色"
        else:
            self.reset()
            return False
        now = self.clock()
        if self.since is None or self.proof != proof:
            self.since, self.proof = now, proof
            return False
        return now - self.since >= limit

    def held_for(self) -> float:
        return 0.0 if self.since is None else self.clock() - self.since
