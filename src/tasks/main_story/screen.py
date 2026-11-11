"""What the screen shows while 推主线 is on, and what to press for it.

Leo 2026-11-06 (thread 设计自动推主线功能): 推主线 is a state, not a task
from 主页.  The player is somewhere in the main story; while the state is
on, each look at the screen is answered with one press:

- 「劇情對話 你只要認f2就好 這是優先度最高的」: the story's top-right row
  (log F1, skip F2, auto F3) → F2;
- the 「跳過對話」 dialog F2 opens → Enter (its 確認 says ENTER OR SPACE);
- 「快速進行任務是普通難度通關後才有 如果有 就優先按這個」: the field's
  「快速進行任務」 → click it; it opens the chapter's step list;
- the step list: 「就點右下角自動進行」, then the REWARD popup (「點擊畫面
  將回到上一個畫面」) → tap; a battle step turns the button into 「戰鬥」 →
  click it;
- 「右上角有引導 有e就可以按e尋路」: the top-right 主線 quest with its E key
  → E (only while the character stands; 「自動移動中：主線任務」 = walking);
- a battle: 「戰鬥那邊我決定不要按自動戰鬥 讓玩家去操作」 → nothing, the
  player fights; 「打完 結算畫面就enter」 → Enter on VICTORY / 離開;
- 「打輸就停下來」: DEFEAT → the state ends;
- a difficulty cleared: the 冒險指南 book (普通/困難/超困難, 「可進行」 on the next
  one) → 「前往遊戲卡帶收藏集」 (Space or Enter), and on the shelf the cartridge
  marked 遊戲中 → back in the field, quest 「開始超困難難度」 (Leo 「讓程式推完
  同卡帶的三個難度」; live 4K 2026-11-07).  The book with all three 完成 ends it;
- 「黑底旁白 這不一定 有時候也會有動畫…總之就是按enter」: anything else
  → Enter now and then.

Each screen is told by any one of its cues (Leo 2026-11-06 「這點很重要」:
an extra cue only ever helps).  Cues come from Leo's 4K recording
(.local-dev/story-rec-1106/story_235850.mp4, 2560x1440, game in 繁中) and
his screenshots (/mnt/project-files/main-story-1106/leo-shots/).

Everything here works on a 1920x1080 frame and OCR boxes in the same
reference coordinates; the task scales the capture first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.utils import field_battle, image_io
from src.utils.image_utils import template_match_response
from src.utils.ocr_utils import normalize_ocr_text

REF_W, REF_H = 1920, 1080

# The skip icon (⏭) with its 「F2」 key cap under it, white parts only (the
# scene behind it changes).  Cut from the recording's first story frame.
# 1080p, 334 recording frames: story frames 0.98-1.00 (0.61-0.83 while the
# row fades in), every other frame at most 0.42.
SKIP_TEMPLATE = Path(__file__).resolve().parent / "data" / "skip_f2.png"
SKIP_SEARCH = (1450, 0, 1900, 170)  # x1, y1, x2, y2
SKIP_MIN = 0.55
WHITE_MIN = 200
# Where the skip icon is when its template is not read: the F2 cap at
# (1640, 103), the icon above it (2000x1125 screenshot, scaled).
SKIP_POINT = (1640, 60)
# The same row by its key caps' dark letters 「F1 F2 F3」 (a black-hat of the
# grey picture: dark strokes inside the white caps).  The white-only icon
# above drowns on a bright map (Leo 2026-11-09, a player: 「地图有点亮的那种」):
# on the 1520 live 4K looks, story frames with 30%+ of the corner over the
# white line read 0.39-0.66 there (3 of 7 under SKIP_MIN), while the letters
# keep 0.78+ on every bright one; no other screen over 0.32.
SKIP_KEYS_TEMPLATE = "skip_keys_dark.png"
SKIP_KEYS_MIN = 0.5
SKIP_KEYS_KERNEL = 7
SKIP_KEYS_F2 = (146, 18)  # the F2 cap's centre inside the template
SKIP_ICON_ABOVE_CAP = 46
# The other caps of the row (OCR reads 「F1」 or 「F3」 when 「F2」 is lost).
SKIP_CAP_FROM_F2 = {"F1": -122, "F3": 118}

# The 「跳過對話」 dialog (title, 「是否結束故事觀賞？」, 取消 ESC / 確認 ENTER OR SPACE).
SKIP_DIALOG_WORDS = ("跳過對話", "跳过对话", "是否結束故事觀賞", "是否结束故事观赏", "結束故事觀賞", "结束故事观赏")
SKIP_DIALOG_BOX = (500, 120, 1420, 940)
CONFIRM_WORDS = ("確認", "确认")

# The field's quest, top right: 「◆ Ⅱ 主線」 over 「E 前往賭場入口」, the
# 「快速進行任務」 pill under them (after 普通 is cleared, Leo).
QUEST_BOX = (1500, 110, 1920, 250)
# 简中 words it differently: 「进行快速探索」 (live 2026-11-07, 第13章).
QUICK_WORDS = ("快速進行任務", "快速进行任务", "进行快速探索", "進行快速探索")
# E with quick mode open can ask first: 「进行快速探索 … 是否前往快速探索界面？」,
# 取消 / 立刻前往.
QUICK_ASK_BOX = (500, 250, 1420, 800)
QUICK_ASK_WORDS = ("快速探索", "快速进行", "快速進行")
QUICK_ASK_GO_WORDS = ("立刻前往", "立即前往")
QUICK_ASK_CANCEL_WORDS = ("取消",)
# A chapter played to its end: the quest line turns into 「再次挑战主线任务」, and
# E on it asks 「再次挑战任务 … 是否要再次挑战任务?」.  That is the player's choice
# (Leo 「重開主線不寫進程式」): the state ends here.
# Esc on the field can open the game's own menu: its leaving words are never
# answered with Enter or a click, only Esc again.
EXIT_WORDS = (
    "退出游戏", "退出遊戲", "结束游戏", "結束遊戲", "离开游戏", "離開遊戲",
    "返回标题", "返回標題", "回到标题", "回到標題", "返回登录", "返回登入",
)
# An NPC's 天赋技能 menu (对话 / 偷窃 …): Enter or a click could pick a talent, so
# Esc only.  Its corner only: story lines and quests say these words too.
TALENT_WORDS = ("天赋技能", "天賦技能", "偷窃", "偷竊")
TALENT_BOX = (60, 640, 560, 1040)
CHAPTER_DONE_WORDS = ("再次挑战主线任务", "再次挑戰主線任務", "再次挑战任务", "再次挑戰任務")
MAIN_MARK = "主"  # 主線 / 主线, often read cut: 「主」「主系」「Ⅲ主」
E_KEY = "e"
# The quest line's text, right of the E cap (the last way when E does nothing).
QUEST_LINE_FROM_E = (70, 0)
QUEST_LINE_POINT = (1640, 165)

# E on a step the game cannot walk to (第1章 「使用新鲜食材烹饪」): a banner says
# 「无法自动进行的探索。」 and only 快速进行任务 or the player gets past it.
NO_AUTO_WORDS = ("无法自动进行", "無法自動進行")
# E on a step whose spot the party already stands on: this banner and no more
# (第2章 「解除魔力屏障」: the orbs are broken by hand).
ARRIVED_WORDS = ("已完成自动移动", "已完成自動移動")

# Walking to the quest by itself: 「自動移動中：主線任務」 with a round ✕ under it.
WALK_WORDS = ("自動移動中", "自动移动中")
WALK_CANCEL_BELOW = 72
WALK_CANCEL_POINT = (960, 985)
# Whether the party really walks (Leo 「顯示移動中但是卡住了」「畫面有這種一直在動的
# 陷阱」: a magic circle and the quest line's marquee keep the whole picture
# moving).  Either cue says walking.  Looks 0.6 s apart in the recording, 62
# walking / 61 standing: minimap mean diff walking 9.7+ (1.5 and 2.7 at the two
# ends of a walk), standing at most 0.9 (two transition looks 2.3, 5.0); share
# of map tiles changed walking 0.75+ (0.22 on the last look), standing at most
# 0.18, in falling snow at most 0.44 (第13章, 26 looks).
# Fireflies over the minimap stir it even standing (第1章, 57 looks: median 1.5, top 4.9),
# so 6.0, under the 9.7 of a walk; a walk's two end looks read standing, too short for the 8 s.
MINIMAP = (206, 171, 66)  # centre x, y, radius
MINIMAP_WALKING = 6.0
TILE_DIFF = 6
TILES_WALKING = 0.6
TILE_GRID = (16, 9)
TILE_SIZE = 120

# The prompt over a quest NPC (Leo's frame 2026-11-07 「這時候要按一下f」): a white
# 「F」 key cap, right of it a dark pill with a gold diamond and the action.  It
# moves with the NPC.  The 「已完成自動移動」 banner says nothing about it (Leo).
# The gold decides: any NPC nearby shows the same cap and pill with a grey
# talk icon and its name (live 第13章 「F 华特波尔长老」), which is no quest step.
PROMPT_SCENE = (150, 120, 1650, 900)
PROMPT_TEXT_GAP = 100
PROMPT_LINE = 20
PROMPT_PICTURE_BOX = (150, 120, 1500, 900)  # left of the HUD's own quest diamond
# Leo's two samples 0.92-1.00; the 896 frames without a prompt at most 0.84.
PROMPT_PICTURE_MIN = 0.88
PROMPT_PILL_FROM_GOLD = 40  # right of the diamond: on the pill however short its words
# The quest icon is not always the diamond (第15章 「接受血刻印」: a gold box with a
# tick), so the key cap with a gold icon on the pill counts too.  The cap alone
# does not: every NPC's name prompt has it, and gold anywhere near is not enough
# either: the party's teleport glow behind 「F 好奇青年」 pressed F (第1章).
# Share of gold, three quest prompts / NPC prompts: icon cell 0.30-0.32 / 0,
# the words right of it 0 / 0.
PROMPT_CAP_MIN = 0.85
PROMPT_ICON_CELL = (50, 78, 14)  # from the key's centre: x from, x to, y either way
PROMPT_ICON_GOLD = 0.2
PROMPT_WORDS_CELL = (78, 170)
PROMPT_WORDS_GOLD = 0.03
PROMPT_PILL_FROM_CAP = 95
# A step on a thing, not a person (第1章 「触碰壁炉、桌子、书柜」): no pill at all,
# the skill bar's F button shows ❗ instead of its speech or hand icon.  On it
# 0.88-1.00 (0.67 under a bright sky, with the pill to tell it there); a speech
# icon 0.40.
F_BUTTON_PICTURE = ("f_button_bang.png", (1385, 855, 1440, 915), False, 0.8)
F_BUTTON_POINT = (1411, 888)

# A line of story waiting for Enter (Leo 「這是對話的時候才這樣」), in any of
# three looks: the black band at the bottom of a scene, black narration, a
# cream speech bubble over the speaker (it moves with them).
DIALOG_LINE_BOX = (300, 860, 1620, 990)
DIALOG_BAND = (990, 1080)
DIALOG_BAND_DARK = 15
DIALOG_NAME_MAX = 8
DIALOG_POINT = (960, 950)

# The chapter's step list (quick mode): 「前往當前任務」 bottom left,
# 「可獲得的獎勵」 right; the bottom-right pill says 自動進行 or 戰鬥.
LIST_WORDS = (
    "前往當前任務", "前往当前任务", "可獲得的獎勵", "可获得的奖励", "建議戰鬥力", "建议战斗力", "目前戰鬥力", "目前战斗力",
    # 简中 (live 2026-11-07): 前往当前探索, 当前战斗力, 推荐战斗力.
    "前往当前探索", "前往當前探索", "当前战斗力", "當前戰鬥力", "推荐战斗力", "推薦戰鬥力",
)
LIST_PILL_BOX = (1520, 980, 1920, 1080)
AUTO_GO_WORDS = ("自動進行", "自动进行")
LIST_BATTLE_WORDS = ("戰鬥", "战斗")
# Its REWARD popup: 「點擊畫面將回到上一個畫面。」 under the row of rewards.
REWARD_TAP_WORDS = ("點擊畫面將回到上一個畫面", "点击画面将回到上一个画面", "回到上一個畫面", "回到上一个画面")
REWARD_TAP_POINT = (960, 990)

# A difficulty cleared: the 冒險指南 book, its one button bottom right
# (with 「SPACE OR ENTER」 under it, read as FIELD before this).
BOOK_WORDS = ("冒險指南", "冒险指南")
BOOK_NEXT_WORDS = ("可進行", "可进行")
BOOK_DONE_WORD = "完成"
DIFFICULTIES = 3
ALL_DONE = "三个难度都完成"
# Short on purpose: live OCR read the title 「遊戲卡带收藏集？」.
SHELF_WORDS = ("收藏集", "珍藏集")
BOOK_GO_BOX = (1400, 920, 1920, 1080)
BOOK_GO_POINT = (1650, 991)
# The shelf: its title top left; only the cartridge marked 遊戲中 is ever
# pressed (「不要自己進下一章」), never the shelf's cursor or any other one.
SHELF_TITLE_BOX = (150, 0, 800, 100)
PLAYING_WORDS = ("遊戲中", "游戏中")
SHELF_BOX = (100, 100, 1860, 1040)
# The label sits low on the cartridge's picture; press the picture's middle.
CARTRIDGE_FROM_PLAYING = (-3, -29)

# A battle and its end.
BATTLE_WORDS = ("自動戰鬥中", "自动战斗中", "自動戰鬥結束", "自动战斗结束", "结束自动战斗", "結束自動戰鬥", "battleready")
# The SP counter under the battle (「SP 3/20 ?」), shown with auto on or off:
# a battle the player plays by hand has no 自動戰鬥 words.
SP_PATTERN = re.compile(r"sp\d{1,2}/\d{1,2}")  # 不是次数：只用来认出战斗画面，不读数
SP_COUNT = re.compile(r"\d{1,2}/\d{1,2}")  # 不是次数：只比前后有没有变
SP_BOX = (500, 1030, 1200, 1080)
RESULT_WORDS = ("missioncompleted", "victory")
LEAVE_WORDS = ("離開", "离开")
# 「TURN.1 BATTLE」 bottom right: the battle waits for the player's first turn.
TURN_BOX = (1500, 930, 1920, 1080)
TURN_ONE_PATTERN = re.compile(r"turn\.?[1il|](?!\d)")  # 不是次数：只看还是不是第一回合
# The game's auto battle toggle, top right (live 2026-11-07: pressed on TURN 1
# the battle starts by itself).
AUTO_POINT = (1488, 52)
DEFEAT_WORDS = ("defeat",)

# 主页's words in either language (home_confirmation has simplified ones
# only, so on a 繁中 game its check stays quiet): two groups of these is 主页.
HOME_GROUPS = (("我的小屋",), ("格鲁talk", "格魯talk"), ("街机游戏", "街機遊戲"), ("抽抽乐", "抽抽樂"))
HOME_GROUPS_LEAST = 2

# Loading: NOW LOADING bottom right, the BROWN DUST II logo on black.
LOADING_WORDS = ("nowloading", "browndust")

# The field itself (any one): the skill bar's SPACE / TAB caps, the money row.
FIELD_WORDS = ("space", "spage", "tab")


class Kind(Enum):
    SKIP = "跳过对话"  # F2
    SKIP_DIALOG = "跳过对话确认"  # Enter
    QUICK = "快速进行任务"  # click
    QUICK_ASK = "前往快速探索"  # click 立刻前往
    CHAPTER_DONE = "这一章打完了"  # the end
    EXIT_MENU = "只按 Esc 的菜单"  # Esc only
    LIST_AUTO = "自动进行"  # click
    LIST_BATTLE = "战斗"  # click
    REWARD = "奖励"  # tap
    GUIDE = "主线引导"  # E
    WALKING = "自动移动中"  # wait
    BATTLE = "战斗中"  # the player plays
    RESULT = "战斗结算"  # Enter
    DEFEAT = "战斗失败"  # stop
    LOADING = "加载中"  # wait
    PROMPT = "按 F 互动"  # F
    MANUAL = "这一步要自己做"  # press nothing until it is done
    DIALOG = "对话"  # Enter, line after line (no F2 row on this kind)
    FIELD = "场地（没有主线引导）"  # wait, then stop
    BOOK = "冒险指南"  # Enter (next difficulty) or the end
    SHELF = "游戏卡带收藏集"  # click the cartridge marked 遊戲中
    OTHER = "其他画面"  # Enter


@dataclass
class Reading:
    kind: Kind
    point: tuple[int, int] | None = None  # 1080p point to click, when there is one
    why: str = ""  # the cue that told it, for the log


def to_1080(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if (width, height) == (REF_W, REF_H):
        return frame
    return cv2.resize(frame, (REF_W, REF_H), interpolation=cv2.INTER_AREA)


def _white(part: np.ndarray) -> np.ndarray:
    gray = part if part.ndim == 2 else cv2.cvtColor(part, cv2.COLOR_BGR2GRAY)
    return ((gray > WHITE_MIN).astype(np.uint8)) * 255


@lru_cache(maxsize=1)
def _skip_template() -> np.ndarray | None:
    image = image_io.read(SKIP_TEMPLATE, cv2.IMREAD_GRAYSCALE)
    return None if image is None else _white(image)


def skip_icon(frame_1080: np.ndarray) -> tuple[float, tuple[int, int]]:
    """(score, 1080p centre) of the skip icon in the top-right row."""
    template = _skip_template()
    if template is None:
        return 0.0, SKIP_POINT
    x1, y1, x2, y2 = SKIP_SEARCH
    part = _white(frame_1080[y1:y2, x1:x2])
    if part.max() == 0:
        return 0.0, SKIP_POINT
    result = template_match_response(part, template)
    _low, score, _at, (x, y) = cv2.minMaxLoc(result)
    height, width = template.shape[:2]
    # The icon is the top part of the template, the F2 cap the bottom.
    return float(score), (x1 + x + width // 2, y1 + y + height // 3)


def _dark_strokes(grey: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (SKIP_KEYS_KERNEL, SKIP_KEYS_KERNEL))
    return cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, kernel)


def skip_keys(frame_1080: np.ndarray) -> tuple[float, tuple[int, int]]:
    """(score, 1080p point of the skip icon) from the 「F1 F2 F3」 caps'
    letters: dark on white whatever the map behind is."""
    template = _picture(SKIP_KEYS_TEMPLATE, False)
    if template is None:
        return 0.0, SKIP_POINT
    x1, y1, x2, y2 = SKIP_SEARCH
    part = _dark_strokes(cv2.cvtColor(frame_1080[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY))
    if part.std() == 0:
        return 0.0, SKIP_POINT
    _low, score, _at, (x, y) = cv2.minMaxLoc(template_match_response(part, template))
    fx, fy = SKIP_KEYS_F2
    return float(score), (x1 + x + fx, y1 + y + fy - SKIP_ICON_ABOVE_CAP)


def skip_row(frame_1080: np.ndarray) -> tuple[bool, tuple[int, int], str]:
    """The story's F1/F2/F3 row by either picture (any one is enough)."""
    score, point = skip_icon(frame_1080)
    if score >= SKIP_MIN:
        return True, point, f"跳过图示 {score:.2f}"
    keys, keys_point = skip_keys(frame_1080)
    if keys >= SKIP_KEYS_MIN:
        return True, keys_point, f"F1F2F3 键帽 {keys:.2f}（跳过图示 {score:.2f}）"
    return False, point, f"跳过图示 {score:.2f} / 键帽 {keys:.2f}"


# More pictures, looked at before any text (Leo 2026-11-06 「要頻繁辨識 最好
# 是連 圖像的一起要可以辨識」).  name: (file, search box, white-only?, least
# score).  Scores on the 334 recording frames:
# - the 跳過對話 dialog's key caps 「ESC」 / 「ENTER OR SPACE」 (tall or short card): dialog 1.00,
#   others at most 0.36;
# - the 「快速進行任務」 pill: field frames 0.84-0.97, no other frame over 0.5;
# - the 「✕ 自動戰鬥結束 / ESC」 pill: battle 0.96+, the result screen's 離開
#   pill 0.82 (so 0.9);
# - the quest's 「E」 key cap (Leo 2026-11-06 「自動尋路的那個e 應該也可以當作
#   一個辨識點」), cut from the live 4K field: cap on screen 0.75-1.00 (the
#   lowest over the roulette table), fading under a 開始/完成 banner 0.50-0.70,
#   no cap at most 0.48 (167 recording frames);
# - the ◇ under a line of story without the F1/F2/F3 row, or on black narration
#   (Leo 2026-11-07 「這就是我說的按enter的時候」): on it 0.73-0.97, others at most
#   0.58 (896 frames);
# - the same chevron dark on a cream bubble, anywhere in the scene;
# - the F prompt: see PROMPT_PICTURE_MIN.
# - the 「TURN.1」 half of the battle pill: TURN 1 0.98+, TURN 2 and later 0.80,
#   others at most 0.45 (480 live frames).
DATA = Path(__file__).resolve().parent / "data"
PICTURES = {
    Kind.SKIP_DIALOG: ("skip_dialog_keys.png", (700, 560, 1220, 980), True, 0.6),
    Kind.QUICK: ("quick_pill.png", (1500, 150, 1920, 280), False, 0.75),
    Kind.BATTLE: ("auto_battle_pill.png", (1550, 930, 1920, 1060), False, 0.9),
    Kind.GUIDE: ("quest_e.png", (1530, 120, 1620, 230), False, 0.62),
    Kind.DIALOG: ("dialog_next.png", (880, 950, 1040, 1060), True, 0.65),
    Kind.BOOK: ("book_go_pill.png", BOOK_GO_BOX, False, 0.8),
    Kind.SHELF: ("collection_title.png", SHELF_TITLE_BOX, False, 0.8),
}
# The same pill in another language, any one counts.
MORE_PICTURES = {Kind.QUICK: (("quick_pill_cn.png", (1500, 150, 1920, 280), False, 0.75),)}
TURN_ONE_PICTURE = ("turn1_pill.png", (1550, 930, 1880, 1060), False, 0.92)
# 遊戲中 is gold over the cartridge's own art, so only its gold pixels count:
# the label 0.58-1.00 (JPEG copy, original), anywhere else on the shelf 0.29.
# The OCR did not read it on the live shelf, so the gold bar under the
# cartridge (white on every other one) is the second cue.
DIALOG_CREAM_PICTURE = ("dialog_next_cream.png", (200, 100, 1720, 950), False, 0.8)
PLAYING_PICTURE = "playing_gold.png"
PLAYING_MIN = 0.45
PLAYING_BAR_PICTURE = "playing_bar.png"
PLAYING_BAR_MIN = 0.6
CARTRIDGE_FROM_BAR = (-2, -74)


@lru_cache(maxsize=None)
def _picture(name: str, white: bool) -> np.ndarray | None:
    image = image_io.read(DATA / name, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return _white(image) if white else image


def picture_score(frame_1080: np.ndarray, kind: Kind) -> tuple[float, tuple[int, int] | None]:
    """(score, 1080p centre) of ``kind``'s picture, (0, None) without one."""
    if kind not in PICTURES:
        return 0.0, None
    return _score(frame_1080, PICTURES[kind])


def _score(frame_1080: np.ndarray, picture: tuple) -> tuple[float, tuple[int, int] | None]:
    name, (x1, y1, x2, y2), white, _least = picture
    template = _picture(name, white)
    if template is None:
        return 0.0, None
    part = frame_1080[y1:y2, x1:x2]
    part = _white(part) if white else cv2.cvtColor(part, cv2.COLOR_BGR2GRAY)
    if part.std() == 0 or part.shape[0] < template.shape[0] or part.shape[1] < template.shape[1]:
        return 0.0, None
    result = template_match_response(part, template)
    _low, score, _at, (x, y) = cv2.minMaxLoc(result)
    height, width = template.shape[:2]
    return float(score), (x1 + x + width // 2, y1 + y + height // 2)


def picture_seen(frame_1080: np.ndarray, kind: Kind) -> tuple[bool, tuple[int, int] | None, float]:
    score, point = picture_score(frame_1080, kind)
    least = PICTURES[kind][3] if kind in PICTURES else 1.1
    if score < least:
        for picture in MORE_PICTURES.get(kind, ()):
            other, where = _score(frame_1080, picture)
            if other >= picture[3]:
                return True, where, other
    return score >= least, point, score


def _gold(part: np.ndarray) -> np.ndarray:
    blue, green, red = (part[..., i].astype(np.int16) for i in range(3))
    return (((red > 150) & (green > 120) & (blue < red - 50)).astype(np.uint8)) * 255


def playing_point(frame_1080: np.ndarray, boxes) -> tuple[int, int] | None:
    """The cartridge marked 遊戲中 on the shelf, None when it is not seen."""
    label = _find(boxes, PLAYING_WORDS, SHELF_BOX)
    centre = _centre(label) if label is not None else _gold_centre(frame_1080, PLAYING_PICTURE, PLAYING_MIN)
    if centre is not None:
        return centre[0] + CARTRIDGE_FROM_PLAYING[0], centre[1] + CARTRIDGE_FROM_PLAYING[1]
    centre = _gold_centre(frame_1080, PLAYING_BAR_PICTURE, PLAYING_BAR_MIN)
    if centre is not None:
        return centre[0] + CARTRIDGE_FROM_BAR[0], centre[1] + CARTRIDGE_FROM_BAR[1]
    return None


def _gold_centre(frame_1080: np.ndarray, name: str, least: float) -> tuple[int, int] | None:
    image = image_io.read(DATA / name, cv2.IMREAD_COLOR)
    if image is None:
        return None
    x1, y1, x2, y2 = SHELF_BOX
    part = _gold(frame_1080[y1:y2, x1:x2])
    if part.max() == 0:
        return None
    _low, score, _at, (x, y) = cv2.minMaxLoc(template_match_response(part, _gold(image)))
    if score < least:
        return None
    height, width = image.shape[:2]
    return x1 + x + width // 2, y1 + y + height // 2


def _quest_icon_beside(frame_1080: np.ndarray, x: int, y: int) -> bool:
    """A gold icon on the pill right of the key at (x, y), and none past it."""
    left, right, tall = PROMPT_ICON_CELL
    icon = frame_1080[max(0, y - tall) : y + tall, x + left : x + right]
    words = frame_1080[max(0, y - tall) : y + tall, x + PROMPT_WORDS_CELL[0] : x + PROMPT_WORDS_CELL[1]]
    if not icon.size or not words.size:
        return False
    return float((_gold(icon) > 0).mean()) >= PROMPT_ICON_GOLD and float((_gold(words) > 0).mean()) < PROMPT_WORDS_GOLD


def prompt_point(frame_1080: np.ndarray, boxes) -> tuple[tuple[int, int], str] | None:
    """(a point on its pill, the cue) when the F prompt shows, else None.
    By its look only: the action's words are never stored (Leo 「記不完」), and
    the gold is what tells it from any NPC's name prompt."""
    for key in boxes or ():
        if _name(key) != "f" or not _inside(key, PROMPT_SCENE):
            continue
        right = float(key.x) + float(key.width)
        _kx, ky = _centre(key)
        for box in boxes:
            if box is key or not _name(box):
                continue
            if 0 <= float(box.x) - right <= PROMPT_TEXT_GAP and abs(_centre(box)[1] - ky) <= PROMPT_LINE:
                if _quest_icon_beside(frame_1080, _kx, ky):
                    return _centre(box), "F 和金色图标"
    score = _score(frame_1080, F_BUTTON_PICTURE)[0]
    if score >= F_BUTTON_PICTURE[3]:
        return F_BUTTON_POINT, f"F 键惊叹号 {score:.2f}"
    x1, y1, x2, y2 = PROMPT_PICTURE_BOX
    gold = image_io.read(DATA / "prompt_gold.png", cv2.IMREAD_COLOR)
    scene = _gold(frame_1080[y1:y2, x1:x2])
    if gold is not None and scene.max() > 0:
        _low, score, _at, (x, y) = cv2.minMaxLoc(template_match_response(scene, _gold(gold)))
        if score >= PROMPT_PICTURE_MIN:
            height, width = gold.shape[:2]
            return (x1 + x + width // 2 + PROMPT_PILL_FROM_GOLD, y1 + y + height // 2), f"F 提示金菱形 {score:.2f}"
    cap = _picture("prompt_f_cap.png", False)
    if cap is None:
        return None
    grey = cv2.cvtColor(frame_1080[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    scores = template_match_response(grey, cap).copy()
    height, width = cap.shape[:2]
    for _spot in range(6):  # 不是重试：同一张图上看分数最高的几处
        _low, score, _at, (x, y) = cv2.minMaxLoc(scores)
        if score < PROMPT_CAP_MIN:
            return None
        cx, cy = x1 + x + width // 2, y1 + y + height // 2
        if _quest_icon_beside(frame_1080, cx, cy):
            return (cx + PROMPT_PILL_FROM_CAP, cy), f"F 键帽和金色 {score:.2f}"
        scores[max(0, y - 10) : y + 10, max(0, x - 10) : x + 10] = -1
    return None


def _cream(frame_1080: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> bool:
    """A flat cream area, as inside a speech bubble (stone floors are as
    bright but never this even)."""
    part = frame_1080[max(0, y1) : y2, max(0, x1) : x2].reshape(-1, 3).astype(np.float32)
    if part.size == 0:
        return False
    blue, green, red = part.mean(axis=0)
    return red > 200 and green > 195 and blue > 175 and red - blue < 40 and float(part.std(axis=0).max()) < 6


def _name_and_line(boxes) -> tuple:
    """A short name box with a longer line box under it, as (name, line)."""
    for name in boxes:
        words = _name(name)
        if not 1 <= len(words) <= DIALOG_NAME_MAX:
            continue
        nx, ny = _centre(name)
        for line in boxes:
            lx, ly = _centre(line)
            if line is not name and 20 <= ly - ny <= 70 and abs(lx - nx) <= 600 and len(_name(line)) > len(words):
                return name, line
    return None, None


def _read_dialog(frame_1080: np.ndarray, boxes) -> Reading | None:
    """The text cues of a line of story (the chevrons are in ``read_pictures``)."""
    in_band = [box for box in boxes if _inside(box, DIALOG_LINE_BOX)]
    top, bottom = DIALOG_BAND
    name, line = _name_and_line(in_band)
    if name is not None and float(frame_1080[top:bottom].mean()) < DIALOG_BAND_DARK:
        return Reading(Kind.DIALOG, DIALOG_POINT, name.name)
    name, line = _name_and_line(boxes)
    if name is not None:
        x, y = _centre(line)
        if _cream(frame_1080, x - 150, y + 22, x + 150, y + 60):
            return Reading(Kind.DIALOG, (x, y), name.name)
    return None


def dialog_line(frame_1080: np.ndarray, point) -> np.ndarray:
    """Where this line of story is written: the bottom rows, or a bubble."""
    if point is None or point[1] >= DIALOG_POINT[1] - 50:
        return frame_1080[850:1010, 300:1620]
    x, y = point
    return frame_1080[max(0, y - 130) : y + 40, max(0, x - 720) : x + 40]


def turn_one(frame_1080: np.ndarray, boxes) -> bool:
    """「TURN.1 BATTLE」 is showing: the text or the picture, any one."""
    corner = "".join(_name(box) for box in boxes or () if _inside(box, TURN_BOX))
    if TURN_ONE_PATTERN.search(corner):
        return True
    return _score(frame_1080, TURN_ONE_PICTURE)[0] >= TURN_ONE_PICTURE[3]


def sp_text(boxes) -> str:
    """The 「SP 3/20」 counter as read ("" when not read): the player acted
    when it changes."""
    found = SP_PATTERN.search(_text(boxes or ()))
    if found:
        return found.group(0).removeprefix("sp")
    # On the planning screen its icon is not read: 「0/20？」 alone.
    for box in boxes or ():
        if _inside(box, SP_BOX):
            found = SP_COUNT.search(_name(box))
            if found:
                return found.group(0)
    return ""


def _read_book(frame_1080: np.ndarray, boxes, text: str) -> Reading | None:
    go = _find(boxes, SHELF_WORDS, BOOK_GO_BOX)
    seen, point, score = picture_seen(frame_1080, Kind.BOOK)
    title = _find(boxes, BOOK_WORDS)
    if go is None and not seen and title is None:
        return None
    where = _centre(go) if go is not None else point or BOOK_GO_POINT
    # All three 完成 and nothing 可進行: the cartridge is finished.  Anything
    # short of that reads as "go on": the shelf only ever returns to this cartridge.
    finished = text.count(BOOK_DONE_WORD) >= DIFFICULTIES and not any(
        normalize_ocr_text(word) in text for word in BOOK_NEXT_WORDS
    )
    return Reading(Kind.BOOK, where, ALL_DONE if finished else (go.name if go else f"冒险指南 {score:.2f}"))


def _read_shelf(frame_1080: np.ndarray, boxes) -> Reading | None:
    title = _find(boxes, SHELF_WORDS, SHELF_TITLE_BOX)
    seen, _point, score = picture_seen(frame_1080, Kind.SHELF)
    if title is None and not seen:
        return None
    return Reading(Kind.SHELF, playing_point(frame_1080, boxes), title.name if title else f"收藏集标题 {score:.2f}")


# The 跳過對話 dialog's 確認 sits right of its ENTER OR SPACE cap's centre
# line, above it (key caps template: ESC left, ENTER OR SPACE right).
DIALOG_CONFIRM_FROM_KEYS = (70, -29)


def read_pictures(frame_1080: np.ndarray) -> Reading | None:
    """The screen from pictures alone (no OCR), or None when they do not tell."""
    seen, point, score = picture_seen(frame_1080, Kind.SKIP_DIALOG)
    if seen:
        confirm = (point[0] + DIALOG_CONFIRM_FROM_KEYS[0], point[1] + DIALOG_CONFIRM_FROM_KEYS[1])
        return Reading(Kind.SKIP_DIALOG, confirm, f"跳过对话按键图 {score:.2f}")
    seen, skip_point, why = skip_row(frame_1080)
    if seen:
        return Reading(Kind.SKIP, skip_point, why)
    seen, point, score = picture_seen(frame_1080, Kind.BATTLE)
    if seen:
        return Reading(Kind.BATTLE, None, f"自动战斗结束图 {score:.2f}")
    seen, point, score = picture_seen(frame_1080, Kind.DIALOG)
    if seen:
        return Reading(Kind.DIALOG, DIALOG_POINT, f"对话下一句图 {score:.2f}")
    score, point = _score(frame_1080, DIALOG_CREAM_PICTURE)
    if score >= DIALOG_CREAM_PICTURE[3] and _cream(frame_1080, point[0] - 130, point[1] - 12, point[0] - 25, point[1] + 12):
        return Reading(Kind.DIALOG, point, f"对话框下一句图 {score:.2f}")
    return None


def home_seen(boxes) -> bool:
    """主页 from the whole-frame OCR (any one with the tool's own home check)."""
    text = _text(boxes or ())
    return sum(any(word in text for word in group) for group in HOME_GROUPS) >= HOME_GROUPS_LEAST


def _name(box) -> str:
    return normalize_ocr_text(getattr(box, "name", ""))


def _inside(box, area) -> bool:
    x1, y1, x2, y2 = area
    cx = float(box.x) + float(box.width) / 2
    cy = float(box.y) + float(box.height) / 2
    return x1 <= cx <= x2 and y1 <= cy <= y2


def _centre(box) -> tuple[int, int]:
    return round(float(box.x) + float(box.width) / 2), round(float(box.y) + float(box.height) / 2)


def _find(boxes, words, area=None, exact: bool = False):
    wanted = [normalize_ocr_text(word) for word in words]
    for box in boxes:
        if area is not None and not _inside(box, area):
            continue
        name = _name(box)
        if not name:
            continue
        if exact and name in wanted:
            return box
        if not exact and any(word in name for word in wanted):
            return box
    return None


def _text(boxes) -> str:
    return "".join(_name(box) for box in boxes)


def read(frame_1080: np.ndarray, boxes) -> Reading:
    """The screen ``frame_1080`` shows, from ``boxes`` (OCR of the whole
    1080p frame).  First match wins; the order is what Leo put first."""
    boxes = list(boxes or ())
    text = _text(boxes)

    # The skip dialog first: its card also says 主線 and the scene's row may
    # still show behind it.
    pictured = read_pictures(frame_1080)
    if pictured is not None and pictured.kind != Kind.BATTLE:
        if pictured.kind == Kind.SKIP_DIALOG:
            confirm = _find(boxes, CONFIRM_WORDS, SKIP_DIALOG_BOX)
            if confirm is not None:
                pictured.point = _centre(confirm)
        return pictured
    dialog = _find(boxes, SKIP_DIALOG_WORDS, SKIP_DIALOG_BOX)
    if dialog is not None:
        confirm = _find(boxes, CONFIRM_WORDS, SKIP_DIALOG_BOX)
        return Reading(Kind.SKIP_DIALOG, _centre(confirm) if confirm else None, dialog.name)

    leaving = _find(boxes, EXIT_WORDS) or _find(boxes, TALENT_WORDS, TALENT_BOX)
    if leaving is not None:
        return Reading(Kind.EXIT_MENU, None, leaving.name)

    done = _find(boxes, CHAPTER_DONE_WORDS)
    if done is not None:
        return Reading(Kind.CHAPTER_DONE, None, done.name)

    go = _find(boxes, QUICK_ASK_GO_WORDS, QUICK_ASK_BOX)
    if go is not None and _find(boxes, QUICK_ASK_WORDS, QUICK_ASK_BOX) is not None:
        return Reading(Kind.QUICK_ASK, _centre(go), go.name)

    seen, point, why = skip_row(frame_1080)
    if seen:
        return Reading(Kind.SKIP, point, why)
    x1, y1, x2, y2 = SKIP_SEARCH
    f2 = _find(boxes, ("F2",), SKIP_SEARCH, exact=True)
    if f2 is not None:
        cx, cy = _centre(f2)
        return Reading(Kind.SKIP, (cx, max(y1, cy - 43)), "F2")
    # 「F2」 lost on a bright map (live: read as 「a」), its neighbours read.
    for cap, from_f2 in SKIP_CAP_FROM_F2.items():
        other = _find(boxes, (cap,), SKIP_SEARCH, exact=True)
        if other is not None:
            cx, cy = _centre(other)
            return Reading(Kind.SKIP, (cx - from_f2, max(y1, cy - 43)), cap)

    if any(word in text for word in DEFEAT_WORDS):
        return Reading(Kind.DEFEAT, None, "DEFEAT")

    leave = _find(boxes, LEAVE_WORDS, (1300, 900, 1920, 1080))
    if any(word in text for word in RESULT_WORDS) or (leave is not None and "reward" in text):
        return Reading(Kind.RESULT, _centre(leave) if leave else None, "VICTORY")

    tap = _find(boxes, REWARD_TAP_WORDS)
    if tap is not None:
        return Reading(Kind.REWARD, REWARD_TAP_POINT, tap.name)

    if pictured is not None:  # the battle pill (checked after DEFEAT/VICTORY)
        return pictured
    if any(normalize_ocr_text(word) in text for word in BATTLE_WORDS):
        return Reading(Kind.BATTLE, None, "自动战斗/BATTLE READY")
    if SP_PATTERN.search(text) or field_battle.in_battle(boxes):
        return Reading(Kind.BATTLE, None, "SP/TURN")

    if turn_one(frame_1080, boxes):
        return Reading(Kind.BATTLE, None, "TURN 1")

    shelf = _read_shelf(frame_1080, boxes)
    if shelf is not None:
        return shelf
    book = _read_book(frame_1080, boxes, text)
    if book is not None:
        return book

    listing = _find(boxes, LIST_WORDS)
    if listing is not None:
        go = _find(boxes, AUTO_GO_WORDS, LIST_PILL_BOX)
        if go is not None:
            return Reading(Kind.LIST_AUTO, _centre(go), go.name)
        battle = _find(boxes, LIST_BATTLE_WORDS, LIST_PILL_BOX)
        if battle is not None:
            return Reading(Kind.LIST_BATTLE, _centre(battle), battle.name)

    dialog = _read_dialog(frame_1080, boxes)
    if dialog is not None:
        return dialog

    if any(word in text for word in LOADING_WORDS):
        return Reading(Kind.LOADING, None, "LOADING")

    walking = _find(boxes, WALK_WORDS)
    if walking is not None:
        x, y = _centre(walking)
        return Reading(Kind.WALKING, (x, y + WALK_CANCEL_BELOW), "自动移动中")

    # Before 快速進行任務: Leo pressed F here with the pill showing too.
    prompt = prompt_point(frame_1080, boxes)
    if prompt is not None:
        return Reading(Kind.PROMPT, prompt[0], prompt[1])

    quick = _find(boxes, QUICK_WORDS, QUEST_BOX)
    if quick is not None:
        return Reading(Kind.QUICK, _centre(quick), quick.name)
    seen, point, score = picture_seen(frame_1080, Kind.QUICK)
    if seen:
        return Reading(Kind.QUICK, point, f"快速进行任务图 {score:.2f}")

    no_auto = _find(boxes, NO_AUTO_WORDS)
    if no_auto is not None:
        return Reading(Kind.MANUAL, None, no_auto.name)

    seen, point, score = picture_seen(frame_1080, Kind.GUIDE)
    line = (point[0] + QUEST_LINE_FROM_E[0], point[1] + QUEST_LINE_FROM_E[1]) if seen else QUEST_LINE_POINT
    quest = [box for box in boxes if _inside(box, QUEST_BOX)]
    if any(MAIN_MARK in getattr(box, "name", "") for box in quest) or any(
        _name(box) == E_KEY for box in quest
    ):
        return Reading(Kind.GUIDE, line, "主线/E")
    if seen:
        return Reading(Kind.GUIDE, line, f"E 键图 {score:.2f}")

    if any(word in text for word in FIELD_WORDS):
        return Reading(Kind.FIELD, None, "SPACE/TAB")

    return Reading(Kind.OTHER, None, "")


def quick_ask_cancel(boxes) -> tuple[int, int] | None:
    cancel = _find(boxes, QUICK_ASK_CANCEL_WORDS, QUICK_ASK_BOX)
    return _centre(cancel) if cancel is not None else None


def quest_text(boxes) -> str:
    """The quest line as read, without its 主线 mark and the quick pill."""
    words = []
    for box in boxes or ():
        name = _name(box)
        if not _inside(box, QUEST_BOX) or not name or name == E_KEY:
            continue
        if MAIN_MARK in getattr(box, "name", "") or any(normalize_ocr_text(word) in name for word in QUICK_WORDS):
            continue
        words.append(name)
    return "".join(words)


def arrived(boxes) -> bool:
    return _find(boxes or (), ARRIVED_WORDS) is not None


def quick_point(frame_1080: np.ndarray, boxes) -> tuple[int, int] | None:
    """The 「快速進行任務」 pill, by its words or its picture."""
    quick = _find(boxes, QUICK_WORDS, QUEST_BOX)
    if quick is not None:
        return _centre(quick)
    seen, point, _score_ = picture_seen(frame_1080, Kind.QUICK)
    return point if seen else None


def _map_tiles() -> np.ndarray:
    """The tiles of the picture that show the map, not the HUD."""
    columns, rows = TILE_GRID
    keep = np.ones((rows, columns), bool)
    for row in range(rows):
        for column in range(columns):
            x, y = column * TILE_SIZE + TILE_SIZE // 2, row * TILE_SIZE + TILE_SIZE // 2
            keep[row, column] = not (
                y < 120  # money row
                or (x < 340 and y < 300)  # minimap
                or (x >= 1500 and y < 280)  # quest line (a marquee while walking)
                or (x >= 1480 and y >= 700)  # skills
                or (640 <= x < 1280 and y >= 860)  # the walking banner
            )
    return keep


def minimap_change(before: np.ndarray, after: np.ndarray) -> float:
    x, y, radius = MINIMAP
    grey = [
        cv2.cvtColor(image[y - radius : y + radius, x - radius : x + radius], cv2.COLOR_BGR2GRAY)
        for image in (before, after)
    ]
    circle = np.zeros(grey[0].shape, np.uint8)
    cv2.circle(circle, (radius, radius), radius, 255, -1)
    return float(cv2.absdiff(grey[0], grey[1])[circle > 0].mean())


def tiles_changed(before: np.ndarray, after: np.ndarray) -> float:
    """The share of map tiles that changed: a camera pan moves nearly all."""
    columns, rows = TILE_GRID
    side = 30
    grey = [
        cv2.cvtColor(cv2.resize(image, (columns * side, rows * side), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        for image in (before, after)
    ]
    change = cv2.absdiff(grey[0], grey[1]).astype(np.float32).reshape(rows, side, columns, side).mean(axis=(1, 3))
    return float((change[_map_tiles()] >= TILE_DIFF).mean())


def party_walking(before: np.ndarray | None, after: np.ndarray) -> bool:
    """Either cue is enough: only both quiet can call a walk stuck."""
    if before is None:
        return True
    return minimap_change(before, after) >= MINIMAP_WALKING or tiles_changed(before, after) >= TILES_WALKING


def moved(before: np.ndarray | None, after: np.ndarray, at_least: float = 2.0) -> bool:
    """Whether the picture changed (the camera follows a walking character,
    an animation plays): mean grey difference of small copies."""
    if before is None:
        return True
    small = [
        cv2.cvtColor(cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        for image in (before, after)
    ]
    return float(np.mean(cv2.absdiff(small[0], small[1]))) >= at_least
