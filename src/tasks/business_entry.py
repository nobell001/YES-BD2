"""The 主页 经营管理 button, shared by 一键收菜 and 领取常客圣石.

Player summary v0.2.26 2026-11-01 (1080p window, HDR on): 一键收菜 opened
the popup and closed it, then 领取常客圣石 pressed the same spot six times
(two runs of three) and the popup never opened; the 主页 check passed after
every press and the last frames show 主页 with no popup.  Why the game let
those presses through is not known (no frame of the press itself).

Two things made the two tasks differ, and both are shared here:

* how the popup is recognised: 一键收菜 read the whole picture and found it
  on that player's HDR screen; 领取常客圣石 read only two cut-outs.  Both now
  read the whole picture first (``popup_seen``).
* what a press that changes nothing is followed by: only the same spot
  again.  Now, while 主页 is still shown, the icon once more and then the
  「经营管理」 word under it (another part of the same button, harmless).
"""

from __future__ import annotations

from src.utils.ocr_utils import keyword_match_count

# 1920x1080 reference.  Icon centre (docs/dev-notes/bd2-ui-map.md: 165,265)
# and the 「经营管理」 word under it (live 4K 2026-10-11 home frame: the
# word's centre at y≈300; the next row starts below y≈330).
ENTRY_POINT = (165, 262)
LABEL_POINT = (165, 300)

# 经营管理弹窗实际文案（国服简体，BUG-20260829-011 实测转录）。
POPUP_KEYWORDS = (
    "餐馆营业额现状",
    "渔笼收获情况",
    "助手工作情况",
    "取消",
    "一键获得",
)
POPUP_MIN_HITS = 2
# How long one press waits for the popup before the next remedy.
POPUP_LOOK_SECONDS = 4.0


def popup_seen(text: object) -> bool:
    """Whole-picture OCR text shows the 经营管理 popup."""
    return keyword_match_count(str(text or ""), list(POPUP_KEYWORDS)) >= POPUP_MIN_HITS
