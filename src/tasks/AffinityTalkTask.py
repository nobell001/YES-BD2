"""亲密度谈心 (Leo 2026-10-21): talk to costumes on the 亲密度 page.

主页 → 亲密度 → list of costumes.  LV20 costumes are talked up to 谈心记录
15/15 (no daily limit at LV20) and remembered by name once full, so they
are never opened again.  Below LV20 each costume can be talked once a day,
three talks in all (「今日剩余谈心次数」).  At LV20 the first answer is
pressed without reading (the answer no longer matters); below LV20 the
answer comes from the souseha bank (affinity/data/counseling.json).
The plan is in affinity/plan.py, the page reading in affinity/screen.py.

Keyboard first (Leo 2026-10-21 「鍵盤操作為優先… 可以點快捷鍵 就用快捷鍵」,
a keyboard stability test): back is Esc, the talk lines F2 (skip) or
Space, the answers 1 / 2.  Each key is checked by the screen it should
change; when it changed nothing the mouse does the step, and a key that
never worked is left alone for the rest of the run (the run report says
which keys worked).  The 主页 entry, the cards, the 谈心 button and its
「进行谈心」 dialog show no key and are clicked.  Esc when a talk screen
stays unchanged (STUCK_SECONDS).
"""

from __future__ import annotations

from time import monotonic

import cv2
from qfluentwidgets import FluentIcon

from src.tasks import run_report
from src.tasks.affinity import answers, plan, record, screen
from src.tasks.BaseBD2Task import KEY_TAP_SECONDS, PROBE_OUTPUT_DIR
from src.tasks.claim_page import (
    BACK_BUTTON_POINT,
    OVERLAY_DISMISS_KEYWORDS,
    REWARD_DIALOG_TITLES,
)
from src.tasks.RewardClaimTasks import _ClaimTaskBase
from src.utils.known_popups import CONFIRM_TEXT
from src.utils.ocr_utils import keyword_match_count, normalize_ocr_text
from src.utils.wait_limits import STUCK_SECONDS

LABEL = "亲密度谈心"
ENTRY_POINT = (361, 257)  # 主页 left column, under 公会 (2K 2026-10-21)
HOME_ENTRY_ROI = (60, 80, 520, 320)
HOME_ICON_ABOVE_LABEL = 40  # label 「亲密度」 at y 300, its icon at 257
# Game keys, filled in from the live frames (None: the game shows no key).
ENTRY_KEY: str | None = None
TALK_KEY: str | None = None
# Keys tried before the mouse (Windows virtual-key codes).  The talk scene
# shows F1 log / F2 skip / F3 auto top right (F2 hidden on the answer
# screen) and 1 / 2 on the answers (4K clone 2026-10-21).
BACK_KEY = "Esc"
# The 「进行谈心」 dialog shows no key and Enter did nothing there (4K clone
# 2026-10-21, 0 of 2): it is clicked.
CONFIRM_KEY: str | None = None
SKIP_KEY = "F2"
ADVANCE_KEY = "Space"
ADVANCE_KEYS = (SKIP_KEY, ADVANCE_KEY)  # skip to the answers / the end, else line by line
CHOICE_KEYS = ("1", "2")
KEY_CODES = {
    "Esc": 0x1B,
    "Enter": 0x0D,
    "Space": 0x20,
    "F2": 0x71,
    "1": 0x31,
    "2": 0x32,
}
SKIP_WORD = ("跳过",)
# A key that changed nothing this many times, and never worked, is dropped.
KEY_GIVE_UP_MISSES = 2
# A talk key pressed and the screen still unchanged this long: the next way.
ADVANCE_KEY_SECONDS = 3.0
# The talk scene: lines are tapped on; the choice buttons sit in the middle.
# Calibrate on the live probe frames.
TALK_ADVANCE_POINT = (960, 1000)
CHOICE_ROI = (360, 200, 1200, 640)
CHOICE_MIN_CHARS = 3
# Short answers (「不。」「是的。」, 4K clone 10-21 使徒) count when centred on
# the buttons' column and ending like a sentence: a lone glyph read off the
# art (「漆」 on 明月's hat) is neither.
CHOICE_SHORT_CENTRE = 960
CHOICE_SHORT_SLACK = 120
CHOICE_SENTENCE_ENDS = "。！？…!?.~～"
# Answer buttons still up this long after a press: the press missed, answer again.
CHOICE_RETRY_SECONDS = 2.5
CHOICE_COLUMN_SLACK = 160
CHOICE_GAP = (40, 260)
TALK_MAX_SECONDS = 120.0
TALK_TAP_INTERVAL = 0.8
# A LV20 costume never gets more than this many talks in one run (15 is full).
FINISH_MAX_TALKS = screen.RECORD_FULL
GRID_SCROLL_POINT = (960 / 1920, 600 / 1080)
GRID_SCROLL_ROUNDS = 4
PROBE_MAX_FRAMES = 1500
# Between the two reads of a panel that must agree.
DETAIL_CONFIRM_SECONDS = 0.3
# A card pressed that shows no 谈心 panel, the list then back: most likely a
# costume the player does not own (greyed on the list, YES-BD2 #58).  Skipped
# and told, not a failure; it is tried again the next day.
NO_PANEL = "no_panel"



def no_panel_note(costumes: list[str]) -> str:
    """Why costumes on the list were left alone (YES-BD2 #58)."""
    names = "、".join(f"「{name}」" for name in dict.fromkeys(costumes))
    return f"点了{names}没出现谈心面板（可能还没拥有这件服装），跳过了，其他服装照常谈心。"


def locked_note(costumes: list[str]) -> str:
    """Why LV15 costumes waiting for 潜力释放 were not talked to today."""
    names = "、".join(dict.fromkeys(costumes))
    return (
        f"{names}还没释放潜力（停在 LV15，谈心不会涨亲密度），"
        "排在会涨的服装后面，今天的谈心次数用完了没轮到。"
    )

class AffinityTalkTask(_ClaimTaskBase):
    claim_log_name = "affinity"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "亲密度谈心"
        self.description = (
            "主页 → 亲密度。LV20 的服装谈到 15/15，谈满后不再打开；"
            "未满 LV20 的每天谈 3 次，按题库选答案。"
        )
        self.icon = FluentIcon.HEART
        # Hidden: the first live look (Leo 2026-10-21 「你自己錄 自己測」): one
        # LV20 talk only, every frame of it saved.
        self.default_config["_试跑只谈一次"] = False
        # Hidden: keep every frame of a full test run too (Leo 「做完整測試 找錯誤」).
        self.default_config["_存每个画面"] = False

    # -- flow -----------------------------------------------------------------------

    def run_claim(self) -> bool:
        self._record = record.load()
        self._today = record.game_day()
        self._keys: dict[str, list[int]] = {}  # key -> [worked, missed]
        if not self._open_list():
            return self._claim_fail("打开亲密度")
        cards, talks_left = self._read_list()
        if not cards:
            self._note_why("亲密度列表上没读到任何服装")
            self._save_flow_diagnostic("affinity_list_unread")
            self._go_home()
            return self._claim_fail("读取服装列表")
        work = plan.make_plan(cards, self._record, self._today, talks_left)
        self._probe = bool(self.config.get("_试跑只谈一次", False))
        self._probe_frames = 0
        self._keep_frames = self._probe or bool(self.config.get("_存每个画面", False))
        if self._keep_frames:
            self._keep_probe_frame("list", self.capture_frame())
        if self._probe:
            work = plan.Plan(work.finish, [], work.talks_left)
        self.info_set("服装数量", len(cards))
        self.info_set("待谈满", "、".join(c.costume for c in work.finish) or "-")
        self.info_set("今日剩余谈心次数", "-" if talks_left is None else talks_left)
        problems: list[str] = []
        no_panel: list[str] = []
        opened = 0
        self._talks = 0
        for card in work.finish:
            why = self._finish_costume(card)
            if why == NO_PANEL:
                no_panel.append(card.costume)
            elif why:
                problems.append(f"{card.costume}：{why}")
            else:
                opened += 1
            if self._probe and self._talks:
                break
        left = talks_left
        locked_skipped: list[str] = []
        for index, card in enumerate(work.daily):
            if left is not None and left <= 0:
                talked = self._record.talked_today(self._today)
                locked_skipped += [
                    c.costume for c in work.daily[index:]
                    if c.key in self._record.locked and c.key not in talked
                ]
                break
            outcome = self._daily_talk(card, allow_locked=self._only_locked_left(card, work))
            if outcome == NO_PANEL:
                no_panel.append(card.costume)
                continue
            if outcome == "talked":
                left = None if left is None else left - 1
            elif outcome == "locked":
                locked_skipped.append(card.costume)
            elif outcome not in ("used", "maxed"):
                problems.append(f"{card.costume}：{outcome}")
                continue
            opened += 1
        if no_panel:
            note = no_panel_note(no_panel)
            self.log_info(f"{LABEL}：{note}")
            if opened:
                run_report.add_current_note(note)
            else:
                # Not one panel opened: the presses are what fails, not the costumes.
                problems.append(note)
        if locked_skipped:
            # Leo 2026-10-22 「維持原做法 但報表說一下就好」.
            note = locked_note(locked_skipped)
            self.log_info(f"{LABEL}：{note}")
            run_report.add_current_note(note)
        record.save(self._record)
        self._report_keys()
        if not self._go_home():
            return self._claim_fail("亲密度返回主页")
        if problems:
            self._note_why("；".join(problems[:3]))
            return self._claim_fail("谈心")
        return True

    def _go_home(self) -> bool:
        """Esc; the back arrow; then the usual way home (back moves, H, Esc)."""
        if self._key(BACK_KEY, after_sleep=1.0):
            home = self._wait_for_home_confirmation(f"{LABEL} Esc 返回主页", timeout=5.0)
            self._key_result(BACK_KEY, home)
            if home:
                return True
            self.log_info(f"{LABEL}：Esc 没回到主页，改点返回箭头。")
        if self._leave_to_home(LABEL, screen.LIST_TITLE):
            return True
        from src.tasks.recovery import recover_to_home

        self.log_info(f"{LABEL}：返回箭头没回到主页，改用通用回主页。")
        return bool(recover_to_home(self))

    # -- keys -------------------------------------------------------------------------

    def _key_usable(self, name: str) -> bool:
        worked, missed = self._keys.get(name, [0, 0])
        return bool(worked) or missed < KEY_GIVE_UP_MISSES

    def _key(self, name: str, after_sleep: float = 0.0) -> bool:
        """Press one of the keys tried before the mouse; False when it is
        dropped for this run or the game is not in front (nothing sent)."""
        if not hasattr(self, "_keys"):
            self._keys = {}
        if not self._key_usable(name):
            return False
        if not self._send_game_key(KEY_CODES[name], KEY_TAP_SECONDS):
            self.info_set("快捷键", f"{name} 未发送：游戏窗口不在最前面")
            self.log_warning(f"游戏窗口不在最前面，{name} 没有发送，改用鼠标。")
            return False
        self.info_set("快捷键", name)
        self.sleep(after_sleep)
        return True

    def _key_result(self, name: str, worked: bool, drop: bool = False) -> None:
        """What the key did; ``drop`` when it did harm (stop using it)."""
        counts = self._keys.setdefault(name, [0, 0])
        if worked:
            counts[0] += 1
            return
        counts[1] += 1
        if drop:
            counts[0] = 0
            counts[1] = max(counts[1], KEY_GIVE_UP_MISSES)
        if not self._key_usable(name):
            self.log_info(f"{LABEL}：{name} 键没有作用，这次改用鼠标。")

    def _report_keys(self) -> None:
        if not getattr(self, "_keys", None):
            return
        summary = "、".join(
            f"{name} {'有用' if worked else '没用'}（{worked} 次成功，{missed} 次没反应）"
            for name, (worked, missed) in self._keys.items()
        )
        self.info_set("快捷键结果", summary)
        self.log_info(f"{LABEL}：快捷键结果：{summary}")

    def _only_locked_left(self, card, work) -> bool:
        """A locked costume is talked only when no unlocked one is left."""
        return all(
            other.key in self._record.locked
            for other in work.daily
            if other.key not in self._record.talked_today(self._today)
        )

    # -- list page --------------------------------------------------------------------

    def _list_visible(self, frame) -> bool:
        if not self._title_visible(frame, screen.LIST_TITLE, LABEL):
            return False
        # The detail page keeps the 亲密度 title: the grid is told by its cards.
        boxes = self._reference_boxes(frame, screen.LIST_GRID_ROI, "亲密度列表")
        return bool(screen.parse_cards(boxes))

    def _open_list(self) -> bool:
        if ENTRY_KEY and self._wait_for_home_confirmation(f"{LABEL}入口前主页确认", timeout=3.0):
            self.info_set("当前阶段", f"打开{LABEL}（快捷键 {ENTRY_KEY}）")
            if self.tap_key(ENTRY_KEY, after_sleep=0.8) and self._wait_for_title(
                LABEL, screen.LIST_TITLE, timeout=4.0, quiet=True
            ):
                return True
            self.log_info(f"{LABEL}：快捷键 {ENTRY_KEY} 没打开亲密度，改用鼠标。")
        if self._open_page_from_home(LABEL, ENTRY_POINT, screen.LIST_TITLE):
            return True
        # Fallbacks (Leo 2026-10-21 「都要有備用方案 包含進卡帶這些」): the
        # 亲密度 label read on 主页 (the icon may have moved), then once more
        # from a fresh 主页.
        label = self._home_entry_label()
        if label is not None:
            self.log_info(f"{LABEL}：固定位置没打开，改点主页上读到的「亲密度」字。")
            self._click_reference(*label, after_sleep=0.8)  # 不用确认：下一行等标题
            if self._wait_for_title(LABEL, screen.LIST_TITLE, quiet=True):
                return True
        from src.tasks.recovery import recover_to_home

        self.log_info(f"{LABEL}：没进到亲密度，回主页再试一次。")
        if recover_to_home(self):
            return self._open_page_from_home(LABEL, ENTRY_POINT, screen.LIST_TITLE)
        return False

    def _home_entry_label(self) -> tuple[int, int] | None:
        """Where 主页 shows the word 亲密度 (reference px), the icon above it."""
        boxes = self._reference_boxes(self.capture_frame(), HOME_ENTRY_ROI, "主页亲密度入口")
        box = self._box_with(boxes, screen.LIST_TITLE)
        if box is None:
            return None
        return round(box.x + box.width / 2), round(box.y - HOME_ICON_ABOVE_LABEL)

    def _grid_cards(self) -> list:
        boxes = self._wait_boxes(
            screen.LIST_GRID_ROI,
            "亲密度列表",
            lambda found: bool(screen.parse_cards(found)),
            timeout=4.0,
            reference=True,
        )
        return screen.parse_cards(boxes)

    def _read_list(self) -> tuple[list, int | None]:
        """Every card (scrolling while new ones show) and the talks left today."""
        read = self.look_again(self._remaining_read, "今日剩余谈心次数")
        talks_left = read[0] if read else None
        if talks_left is None:
            # Unread: each costume's own 1/1 still decides, so nothing is pressed blind.
            self.log_info(f"{LABEL}：没读到今日剩余谈心次数，改看每件服装的 1/1。")
        cards = self._grid_cards()
        # A card whose Lv line went unread on one frame is missing from that
        # read: a second read, the fuller one counts.
        again = self._grid_cards()
        if len(again) > len(cards):
            self.log_info(f"{LABEL}：第二次读列表多读到 {len(again) - len(cards)} 件。")
            cards = again
        self._scrolled = 0
        known = {c.key for c in cards}
        for _round in range(GRID_SCROLL_ROUNDS):
            if len(cards) < 3 * 13:  # three full rows fit; fewer never scroll
                break
            self.scroll_client(GRID_SCROLL_POINT, -1, count=5, interval=0.05, after_sleep=0.8)
            self._scrolled += 1
            more = [c for c in self._grid_cards() if c.key not in known]
            if not more:
                break
            known.update(c.key for c in more)
            cards += more
        self.info_set("服装列表", "、".join(f"{c.costume}Lv{c.level}" for c in cards)[:300])
        return cards, talks_left

    def _remaining_read(self) -> tuple[int] | None:
        """(talks left today,) — a tuple, so 0 counts as read."""
        boxes = self._roi_boxes(self.capture_frame(), screen.LIST_REMAINING_ROI, "剩余谈心次数")
        left = screen.read_remaining(self._boxes_text(boxes))
        return None if left is None else (left,)

    def _back_to_list(self) -> bool:
        """Esc, then the back arrow (3 tries), then 主页 and 亲密度 again."""
        arrow_tries = 3
        if self._key(BACK_KEY, after_sleep=1.0):
            back = self._poll(lambda: self._list_visible(self.capture_frame()), 3.0)
            if back:
                self._key_result(BACK_KEY, True)
                return True
            if self._wait_for_home_confirmation(f"{LABEL} Esc 后", timeout=1.5):
                # Esc left 亲密度 altogether: the arrow from now on.
                self.log_info(f"{LABEL}：Esc 退回了主页，重新打开亲密度，之后改点返回箭头。")
                self._key_result(BACK_KEY, False, drop=True)
                self._scrolled = 0
                if self._open_list():
                    return True
                arrow_tries = 0  # on 主页: the arrow is no way back
            else:
                self._key_result(BACK_KEY, False)
                self.log_info(f"{LABEL}：Esc 没回到列表，改点返回箭头。")
        for _attempt in range(arrow_tries):
            self._click_reference(*BACK_BUTTON_POINT, after_sleep=1.0)  # 不用确认：下一行看列表
            if self._poll(lambda: self._list_visible(self.capture_frame()), 4.0):
                return True
        from src.tasks.recovery import recover_to_home

        self.log_info(f"{LABEL}：没回到服装列表，回主页重新打开亲密度。")
        self._scrolled = 0
        if recover_to_home(self) and self._open_list():
            return self._list_visible(self.capture_frame()) or bool(self._grid_cards())
        self._note_why("从服装面板回不到亲密度列表")
        return False

    def _open_card(self, card) -> screen.Detail | str | None:
        """Press a card on the list (found again by name: the list may have
        moved) and read its detail panel; NO_PANEL when none shows and the
        list is back (a costume not owned, YES-BD2 #58)."""
        target = next((c for c in self._grid_cards() if c.key == card.key), None)
        if target is None and self._scrolled:
            self.scroll_client(GRID_SCROLL_POINT, 1, count=5 * self._scrolled, interval=0.05)
            self._scrolled = 0
            target = next((c for c in self._grid_cards() if c.key == card.key), None)
        if target is None:
            for _round in range(GRID_SCROLL_ROUNDS):
                self.scroll_client(GRID_SCROLL_POINT, -1, count=5, interval=0.05, after_sleep=0.8)
                self._scrolled += 1
                target = next((c for c in self._grid_cards() if c.key == card.key), None)
                if target is not None:
                    break
        if target is None:
            self.log_info(f"{LABEL}：列表上找不到「{card.costume}」。")
            return None
        self.info_set("当前阶段", f"打开 {card.costume}（{card.character}）")
        detail = None
        for attempt in range(2):
            self._click_reference(*target.press, after_sleep=1.0)  # 不用确认：下一行读面板
            detail = self._settled_detail(card.key, f"{card.costume}详情")
            if detail or not self._list_visible(self.capture_frame()):
                break
            # Still on the list: the press was lost; once more.
            self.log_info(f"{LABEL}：点了「{card.costume}」还在列表，再点一次。")
        if not detail:
            self.log_info(f"{LABEL}：点了「{card.costume}」，没读到它的谈心面板。")
            # Back on the list: skip this one and go on with the others.
            return NO_PANEL if self._back_to_list() else None
        return detail

    # -- detail page --------------------------------------------------------------------

    def _read_detail(self, expected_key: str | None = None, frame=None) -> screen.Detail | None:
        frame = self.capture_frame() if frame is None else frame
        # The 谈心 button first: on a talk screen the header box holds only
        # the F1/F2/F3 badges, which cost an empty read and its 2x/3x rereads
        # on every look (4K clone 2026-10-21); the panel itself reads at once.
        button = self._boxes_text(self._roi_boxes(frame, screen.DETAIL_TALK_BUTTON_ROI, "谈心按钮"))
        if keyword_match_count(button, screen.TALK_WORD) < 1:
            return None
        header = self._reference_boxes(frame, screen.DETAIL_HEADER_ROI, "谈心面板")
        detail = screen.parse_detail(header, button)
        if detail.level is None or detail.record is None:
            return None
        if detail.record[1] != screen.RECORD_FULL or detail.record[0] > screen.RECORD_FULL:
            return None  # 谈心记录 is n/15: anything else is a misread
        if expected_key and not screen.same_costume(detail, expected_key):
            self.log_info(f"{LABEL}：打开的是「{detail.key}」，不是「{expected_key}」。")
            return None
        self.info_set(
            "谈心面板",
            f"{detail.costume} Lv{detail.level} 记录{detail.record[0]}/{detail.record[1]}"
            + ("" if detail.daily is None else f" 今日{detail.daily}/1")
            + (" 未释放潜力" if detail.locked else ""),
        )
        return detail

    def _settled_detail(self, key: str, label: str) -> screen.Detail | None:
        """The panel read on two frames that agree on its numbers (Lv, 谈心记录,
        today's talk): one misread 15/15 would retire a costume for good, a
        misread 1/1 would press 谈心 with no talk left.  A third read breaks
        a disagreement; still none: nothing is trusted (None)."""
        first = self.look_again(lambda: self._read_detail(key), label)
        if first is None:
            return None
        for _attempt in range(2):
            self.sleep(DETAIL_CONFIRM_SECONDS)
            again = self._read_detail(key)
            if again is not None and _numbers(again) == _numbers(first):
                return again
            if again is not None:
                first = again
        self.log_info(f"{LABEL}：{label}的数字两次读得不一样，不采用。")
        return None

    def _finish_costume(self, card) -> str:
        """Talk a LV20 costume up to 15/15; "" when full (remembered)."""
        detail = self._open_card(card)
        if detail is None or detail == NO_PANEL:
            return detail or "没打开"
        talks = 0
        stalls = 0
        if getattr(self, "_keep_frames", False):
            self._keep_probe_frame(f"detail_{card.costume}", self.capture_frame())
        talk_limit = 1 if getattr(self, "_probe", False) else FINISH_MAX_TALKS
        while detail.record[0] < screen.RECORD_FULL and talks < talk_limit:
            before = detail.record[0]
            if not self._talk_once(card, first_answer=True):
                self._back_to_list()
                return "谈心没完成"
            talks += 1
            self._talks = getattr(self, "_talks", 0) + 1
            detail = self._settled_detail(card.key, "谈心后面板") or detail
            if detail.record[0] <= before:
                stalls += 1
                if stalls >= 2:
                    self._back_to_list()
                    return f"谈了两次，谈心记录还是 {detail.record[0]}/15"
        if detail.level >= screen.MAX_LEVEL and detail.record[0] >= screen.RECORD_FULL:
            self._record.done.add(card.key)
            record.save(self._record)
            self.log_info(f"{LABEL}：「{card.costume}」已谈满 15/15，记下来以后不再打开。")
        self.info_add("谈心次数", talks)
        self._back_to_list()
        return ""

    def _daily_talk(self, card, allow_locked: bool) -> str:
        """One talk on a costume below LV20: talked / used / locked / maxed / why."""
        detail = self._open_card(card)
        if detail is None or detail == NO_PANEL:
            return detail or "没打开"
        if getattr(self, "_keep_frames", False):
            self._keep_probe_frame(f"detail_{card.costume}", self.capture_frame())
        if detail.level >= screen.MAX_LEVEL:
            # Reached LV20 since the list was read: finished another day.
            self._back_to_list()
            return "maxed"
        if detail.locked:
            self._record.locked.add(card.key)
        else:
            self._record.locked.discard(card.key)
        if detail.daily == 0:
            self._record.mark_talked(card.key, self._today)
            self._back_to_list()
            return "used"
        if detail.locked and not allow_locked:
            self._back_to_list()
            return "locked"
        before = detail.record[0]
        if not self._talk_once(card, first_answer=False):
            self._back_to_list()
            return "谈心没完成"
        self._record.mark_talked(card.key, self._today)
        record.save(self._record)
        after = self._settled_detail(card.key, "谈心后面板")
        if after and after.record[0] <= before and after.daily != 0:
            self.log_info(f"{LABEL}：「{card.costume}」谈完记录没变。")
        self.info_add("谈心次数", 1)
        self._back_to_list()
        return "talked"

    # -- one talk ------------------------------------------------------------------------

    def _press_talk(self, card) -> bool:
        """谈心 by its key first, then the button, then 确认 on the dialog it
        opens (「将与 X 进行谈心」, 取消 / 确认; 2K clone 2026-10-21); True
        once the talk has started (the panel left)."""

        def started() -> bool:
            return self._talk_dialog() is not None or self._read_detail() is None

        pressed = False
        if TALK_KEY and self.tap_key(TALK_KEY, after_sleep=0.8):
            pressed = self._poll(started, 2.0)
            if not pressed:
                self.log_info(f"{LABEL}：快捷键 {TALK_KEY} 没开始谈心，改用鼠标。")
        if not pressed:
            self.info_set("当前阶段", f"{card.costume}：按谈心")

            def press() -> None:
                # The 谈心 word read on the button; its usual place when unread.
                boxes = self._reference_boxes(
                    self.capture_frame(), screen.DETAIL_TALK_BUTTON_ROI, "谈心按钮"
                )
                word = self._box_with(boxes, screen.TALK_WORD)
                if word is not None:
                    point = (round(word.x + word.width / 2), round(word.y + word.height / 2))
                else:
                    point = screen.DETAIL_TALK_BUTTON_POINT
                self._click_reference(*point, after_sleep=0.8)  # 不用确认：press_and_confirm 内

            pressed = bool(
                self.press_and_confirm(
                    f"{card.costume}谈心", press, started, still_before=lambda: not started()
                )
            )
        if not pressed:
            return False
        return self._confirm_talk(card)

    def _talk_dialog(self, frame=None):
        """The 确认 box of the 「进行谈心」 dialog, or None when it is not up."""
        frame = self.capture_frame() if frame is None else frame
        boxes = self._reference_boxes(frame, screen.TALK_DIALOG_ROI, "谈心确认框")
        text = normalize_ocr_text(self._boxes_text(boxes))
        confirm = self._box_with(boxes, (CONFIRM_TEXT,))
        if confirm is None:
            return None
        if "进行谈心" in text or "谈心记录" in text or self._box_with(boxes, ("取消",)):
            return confirm
        return None

    def _confirm_talk(self, card) -> bool:
        """CONFIRM_KEY when set, then 确认 (read, else its place) until the
        dialog and panel are gone."""
        if (
            CONFIRM_KEY
            and self._talk_dialog() is not None
            and self._key(CONFIRM_KEY, after_sleep=1.0)
        ):
            if self._talk_dialog() is None:
                if self._read_detail() is None:
                    self._key_result(CONFIRM_KEY, True)
                    return True
                # Enter closed the dialog without a talk (it is 取消): press
                # 谈心 again, this time clicking 确认.
                self.log_info(f"{LABEL}：Enter 关掉了确认框却没开始谈心，改点确认。")
                self._key_result(CONFIRM_KEY, False, drop=True)
                return self._press_talk(card)
            self._key_result(CONFIRM_KEY, False)
            self.log_info(f"{LABEL}：Enter 没按掉确认框，改点确认。")
        for attempt in range(3):
            confirm = self._talk_dialog()
            if confirm is None:
                if self._read_detail() is None:
                    return True  # no dialog (or already confirmed): talk running
                if attempt:
                    break
                self.sleep(0.6)
                continue
            self.info_set("当前阶段", f"{card.costume}：确认谈心")
            if attempt < 2:
                self._click_reference(  # 不用确认：下一轮看确认框
                    round(confirm.x + confirm.width / 2),
                    round(confirm.y + confirm.height / 2),
                    after_sleep=1.0,
                )
            else:
                self.log_info(f"{LABEL}：确认没按到，改点确认的固定位置。")
                self._click_reference(
                    *screen.TALK_DIALOG_CONFIRM_POINT, after_sleep=1.0
                )  # 不用确认：之后看确认框
        if self._talk_dialog() is None and self._read_detail() is None:
            return True
        self.log_info(f"{LABEL}：「{card.costume}」谈心确认框没按掉。")
        self._save_flow_diagnostic("affinity_talk_confirm_failed")
        if self._talk_dialog() is not None:
            self.tap_escape(after_sleep=1.0)
        return False

    def _poll(self, check, seconds: float) -> bool:
        end_at = monotonic() + seconds
        while True:
            if check():
                return True
            if monotonic() >= end_at:
                return False
            self.sleep(0.3)

    def _talk_once(self, card, first_answer: bool) -> bool:
        """Press 谈心, tap through the lines, answer, and settle back on the panel."""
        if not self._press_talk(card):
            self._note_why(f"「{card.costume}」按了谈心没有反应")
            return False
        bank_costume = None if first_answer else answers.find_costume(card.costume, card.character)
        answered = False
        answered_at = 0.0
        answered_by_key: str | None = None
        advance = [k for k in ADVANCE_KEYS if self._key_usable(k)]
        current = advance.pop(0) if advance else None  # the key moving the talk on
        presses = taps = 0  # key presses since the screen last moved / mouse taps
        started = monotonic()
        last_thumb, same_since = None, monotonic()
        while monotonic() - started < TALK_MAX_SECONDS:
            frame = self.capture_frame()
            if getattr(self, "_keep_frames", False):
                self._keep_probe_frame(f"talk_{card.costume}", frame)
            boxes = self._roi_boxes(frame, None, "谈心画面")
            text = self._boxes_text(boxes)
            if self._close_reward(frame, boxes, text):
                same_since = monotonic()
                continue
            if self._read_detail(frame=frame) is not None:
                if not answered:
                    self.log_info(f"{LABEL}：「{card.costume}」回到面板，没看到选项。")
                if answered_by_key:
                    self._key_result(answered_by_key, True)
                if current and not taps:
                    if current == SKIP_KEY and not answered:
                        # Skipped past the answers: never again this run.
                        self.log_info(f"{LABEL}：{SKIP_KEY} 跳过了选项，之后不用它。")
                        self._key_result(SKIP_KEY, False, drop=True)
                    else:
                        self._key_result(current, True)
                return True
            thumb = self._region_thumbs(frame, ((0, 0, 1920, 1080),))
            if last_thumb is not None and not self._thumbs_changed(last_thumb, thumb):
                if monotonic() - same_since >= STUCK_SECONDS:
                    self.log_info(f"{LABEL}：谈心画面 {STUCK_SECONDS:.0f} 秒没变化，按 Esc。")
                    self._save_flow_diagnostic("affinity_talk_stuck")
                    self.tap_escape(after_sleep=1.0)
                    same_since = monotonic()
            else:
                last_thumb, same_since = thumb, monotonic()
                presses = 0
            if keyword_match_count(text, SKIP_WORD) >= 1 and self._box_with(boxes, (CONFIRM_TEXT,)):
                # A 「跳过」 question after F2: 确认.
                self.log_info(f"{LABEL}：跳过要确认，按确认。")
                self._click_box(self._box_with(boxes, (CONFIRM_TEXT,)), after_sleep=0.8)
                continue
            choices = self._choices(frame)
            retry = False
            if answered and (monotonic() - answered_at < CHOICE_RETRY_SECONDS or len(choices) < 2):
                choices = []
            elif answered:
                retry = True
                self.log_info(f"{LABEL}：「{card.costume}」选完选项还在，再选一次。")
                if answered_by_key:
                    self._key_result(answered_by_key, False)
                    answered_by_key = None
            if len(choices) >= 2:
                pick = (
                    answers.Pick(0, False, "LV20 直接选第一个")
                    if first_answer
                    else answers.pick_answer([c.name for c in choices], bank_costume)
                )
                chosen = choices[pick.index]
                self.info_set("谈心选项", " / ".join(c.name for c in choices))
                self.log_info(f"{LABEL}：「{card.costume}」选「{chosen.name}」（{pick.why}）。")
                key = CHOICE_KEYS[pick.index] if pick.index < len(CHOICE_KEYS) else None
                if not retry and key and self._key(key, after_sleep=1.0):
                    answered_by_key = key
                else:
                    self._click_reference(  # 不用确认：选项还在会再选
                        round(chosen.x + chosen.width / 2),
                        round(chosen.y + chosen.height / 2),
                        after_sleep=1.0,
                    )
                answered, answered_at = True, monotonic()
                continue
            self.info_set("谈心画面 OCR", text[:120] or "-")
            if current and presses and monotonic() - same_since >= ADVANCE_KEY_SECONDS:
                # The key pressed and nothing moved: the next way for this talk.
                nxt = advance.pop(0) if advance else None
                self.log_info(
                    f"{LABEL}：{current} {ADVANCE_KEY_SECONDS:.0f} 秒没让对话往下，"
                    f"改{'按 ' + nxt if nxt else '点画面'}。"
                )
                self._key_result(current, False)
                current, presses = nxt, 0
                same_since = monotonic()
            if current and self._key(current, after_sleep=TALK_TAP_INTERVAL):
                presses += 1
            else:
                taps += 1
                self._click_reference(
                    *TALK_ADVANCE_POINT, after_sleep=TALK_TAP_INTERVAL
                )  # 不用确认：每轮看画面
        self._note_why(f"「{card.costume}」谈心 {TALK_MAX_SECONDS:.0f} 秒没回到面板")
        self._save_flow_diagnostic("affinity_talk_timeout")
        return False

    def _close_reward(self, frame, boxes: list, text: str) -> bool:
        """The 15/15 diamond reward (like the mail's): its 点击画面 line, or
        确认 under a reward title.  True when something was pressed."""
        press = self._box_with(boxes, OVERLAY_DISMISS_KEYWORDS)
        if press is None and keyword_match_count(text, REWARD_DIALOG_TITLES) >= 1:
            press = self._box_with(boxes, (CONFIRM_TEXT,))
        if press is None:
            return False
        self._save_reward_picture(frame)
        self.log_info(f"{LABEL}：关闭奖励弹窗（{getattr(press, 'name', '')}）。")
        self._click_box(press, after_sleep=0.8)
        return True

    def _keep_probe_frame(self, name: str, frame) -> None:
        """Test runs: each new screen, numbered, as a small jpg
        (probe_outputs/affinity_probe_*); the same screen again is not kept."""
        if frame is None or getattr(self, "_probe_frames", 0) >= PROBE_MAX_FRAMES:
            return
        thumb = self._region_thumbs(frame, ((0, 0, 1920, 1080),))
        last = getattr(self, "_probe_thumb", None)
        if last is not None and not self._thumbs_changed(last, thumb):
            return
        self._probe_thumb = thumb
        self._probe_frames = getattr(self, "_probe_frames", 0) + 1
        try:
            PROBE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            small = cv2.resize(frame[:, :, :3], (1600, 900), interpolation=cv2.INTER_AREA)
            path = PROBE_OUTPUT_DIR / f"affinity_probe_{self._probe_frames:04d}_{name}.jpg"
            ok, data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                path.write_bytes(data.tobytes())
        except (OSError, cv2.error):
            pass

    def _choices(self, frame) -> list:
        """The answer buttons: two or more lines stacked in one column in
        CHOICE_ROI (reference boxes, top first)."""
        boxes = [b for b in self._reference_boxes(frame, CHOICE_ROI, "谈心选项") if choice_line(b)]
        return stacked_choices(boxes)


def _numbers(detail: screen.Detail) -> tuple:
    return detail.level, detail.record, detail.daily, detail.locked


def choice_line(box) -> bool:
    """A line that can be an answer: long enough, or short but centred."""
    chars = len(normalize_ocr_text(box.name))
    if chars >= CHOICE_MIN_CHARS:
        return True
    raw = str(box.name).strip()
    centre = float(box.x) + float(box.width) / 2
    return (
        chars >= 1
        and raw[-1:] in CHOICE_SENTENCE_ENDS
        and abs(centre - CHOICE_SHORT_CENTRE) <= CHOICE_SHORT_SLACK
    )


def stacked_choices(boxes: list) -> list:
    """Lines centred in one column, one below the other at a button's spacing."""
    boxes = sorted(boxes, key=lambda b: float(b.y))
    best: list = []
    for anchor in boxes:
        centre = float(anchor.x) + float(anchor.width) / 2
        column = [anchor]
        for other in boxes:
            if other is anchor or float(other.y) <= float(column[-1].y):
                continue
            gap = float(other.y) - float(column[-1].y)
            other_centre = float(other.x) + float(other.width) / 2
            if (
                abs(other_centre - centre) <= CHOICE_COLUMN_SLACK
                and CHOICE_GAP[0] <= gap <= CHOICE_GAP[1]
            ):
                column.append(other)
        if len(column) > len(best):
            best = column
    return best if len(best) >= 2 else []
