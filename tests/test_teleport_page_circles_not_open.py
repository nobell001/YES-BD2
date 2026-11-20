"""Player v0.3.16 (简中 1920x1080, 桌面分身) 2026-11-15: 每周跑图 skipped every
card, each 「…的传送页上未识别到传送阵」.  The report's teleport page
(战斗Ⅱ 卢戈森林深处) shows the circles grey, without the gold ring and number
an activated circle has: they were not yet opened in the player's game, and
every chapter's town was reached while its battle maps were not.

Opening them is the player's part (Leo 2026-11-15 「沒開是用戶的問題 改成說:
疑似未開齊地圖傳送陣 … 提示用戶就好了」): the card is still skipped, and the
message says so in those words.

Player on bilibili 2026-11-20 (Leo 「傳送門沒開 要說」): 跑图 still said only
「跑图部分流程未完成」 with no reason, and the player found the unopened
circles himself.  The words now also lead the card's skip note, the 问题摘要's
「停在」, the run's 状态 line (the run log row) and a 一键日常 row, in 简中 and
in 繁中."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

from src.tasks import failure_reason
from src.tasks.DailyBatchTask import failure_note
from src.tasks.map_trade.collector import Collector
from src.tasks.map_trade.models import (
    CARD_BY_ID,
    CollectionResult,
    MapPageMode,
    NavigationResult,
    ScreenState,
)
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.navigator_sandbox import CIRCLES_NOT_OPEN, circles_not_open_message
from src.tasks.map_trade.vision import Vision
from src.tasks.MapCollectionTask import MapCollectionTask
from src.ui.traditional import to_traditional

FIXTURES = Path(__file__).resolve().parent / "fixtures/map_trade"
# The report's own small picture of the page (287x161), brought to 1080p.
PLAYER_PAGE = FIXTURES / "map_pages/luge_deep_no_active_circle_player_summary_thumb.png"
# Leo's page with an activated circle (gold ring, 「1」), the same size.
OPEN_PAGE = FIXTURES / "loading_live/teleport_page_ch8_p95_33_p99_136.jpg"


def _read(path):
    frame = cv2.imread(str(path))
    assert frame is not None, path
    return cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_CUBIC)


def _navigator(frame):
    logs = []
    task = SimpleNamespace(
        config={},
        ocr=lambda **_k: [],
        info_set=lambda *_a: None,
        log_info=lambda text, **_k: logs.append(text),
        sleep=lambda *_a: None,
    )
    vision = Vision(task)
    vision.capture = lambda: frame
    vision.click_client = lambda *_a, **_k: None
    navigator = Navigator(task, vision)
    navigator._status = lambda *_a: None
    navigator.logs = logs
    return navigator


class CirclesNotOpenTest(unittest.TestCase):
    def test_grey_circles_on_the_players_page_are_not_taken_for_usable_ones(self):
        frame = _read(PLAYER_PAGE)
        self.assertEqual((), _navigator(frame)._teleport_map_teleports(frame))

    def test_an_activated_circle_is_still_found(self):
        # Leo's 繁中 client (移動魔法陣, 戰鬥Ⅱ 盜賊的祕密基地): the circle is
        # found by its look, in either language; no hint there.
        frame = cv2.imread(str(OPEN_PAGE))
        self.assertEqual(1, len(_navigator(frame)._teleport_map_teleports(frame)))

    def test_the_skip_tells_the_player_the_circles_are_not_all_open(self):
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[2]  # 卢戈森林深处
        navigator = _navigator(_read(PLAYER_PAGE))
        closed = []
        navigator._close_confirmed_map_page = lambda modes, **_k: (
            closed.append(modes) or NavigationResult(True, ScreenState.SANDBOX, "关了")
        )
        # The area map: 战斗 卢戈森林 (the report's own read), not the target.
        navigator.current_collection_target = lambda _card: card.targets[1].key
        context = SimpleNamespace(
            map_page_mode=MapPageMode.DIRECT_TELEPORT,
            resolved_target_key=target.key,
            teleports=(),
            raw_text="战斗Ⅱ卢戈森林深处",
        )
        result = navigator._click_collection_destination(card, target, context)
        self.assertFalse(result.success)
        self.assertEqual(1, len(closed))  # the page is not left over the field
        self.assertTrue(result.message.startswith("疑似未开齐地图传送阵"))
        self.assertIn("卢戈森林深处", result.message)
        self.assertNotIn("未识别到", result.message)

    def test_standing_on_the_target_is_still_an_arrival(self):
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[2]
        navigator = _navigator(_read(PLAYER_PAGE))
        navigator._close_confirmed_map_page = lambda modes, **_k: NavigationResult(
            True, ScreenState.SANDBOX, "关了"
        )
        navigator.current_collection_target = lambda _card: target.key
        context = SimpleNamespace(map_page_mode=MapPageMode.DIRECT_TELEPORT)
        result = navigator._after_teleport_that_never_started(card, target, context, pressed=False)
        self.assertTrue(result.success)

    def test_the_other_page_kind_says_the_same(self):
        # The 生成魔法阵 page with no usable circle said 「未识别到传送阵地图
        # 传送阵，无法安全传送」.
        card = CARD_BY_ID["Q_sp1"]
        target = card.targets[2]
        navigator = _navigator(_read(PLAYER_PAGE))
        context = SimpleNamespace(
            map_page_mode=MapPageMode.GENERATE_TELEPORT,
            resolved_target_key=target.key,
            teleports=(),
            raw_text="战斗Ⅱ卢戈森林深处",
        )
        result = navigator._click_collection_destination(card, target, context)
        self.assertFalse(result.success)
        self.assertEqual(circles_not_open_message("卢戈森林深处"), result.message)


def _collector():
    collector = object.__new__(Collector)
    stages = {}
    collector.task = SimpleNamespace(
        log_warning=lambda *_a, **_k: None,
        info_set=stages.__setitem__,
    )
    collector.stages = stages
    collector._skill_skips = {}
    collector._unconfirmed_cards = set()
    collector._skipped_cards = []
    collector._skip_reasons = {}
    return collector


def _skip(collector, card_id, reason):
    card = CARD_BY_ID[card_id]
    collector._skipped_cards.append(card)
    collector._skip_reasons[card.card_id] = reason
    return card


class CirclesNotOpenReachThePlayerTest(unittest.TestCase):
    """The skip reason travels: card note -> phase message -> 状态 / 问题摘要."""

    def _skipped_run(self):
        collector = _collector()
        # How the collector words it: 「前往<map>失败（<navigator's message>）」.
        _skip(collector, "Q_sp1", f"前往卢戈森林深处失败（{circles_not_open_message('卢戈森林深处')}）")
        _skip(collector, "Q_sp3", f"前往卢戈森林失败（{circles_not_open_message('卢戈森林')}）")
        _skip(collector, "Q_sp5", "回主城失败（没按到小地图的≡按钮）")
        return collector, collector._with_skipped_cards(
            CollectionResult(True, message="本周已支持的可采集卡带已经处理完毕")
        )

    def test_the_run_message_leads_with_the_unopened_circles(self):
        collector, result = self._skipped_run()
        self.assertFalse(result.success)
        self.assertTrue(result.message.startswith(CIRCLES_NOT_OPEN), result.message)
        lead = result.message.split("；")[0]
        self.assertIn(f"{CARD_BY_ID['Q_sp1'].label}（卢戈森林深处）", lead)
        self.assertIn(f"{CARD_BY_ID['Q_sp3'].label}（卢戈森林）", lead)
        self.assertIn("请先在游戏里走到那张图开启传送阵", result.message)
        # The other card keeps its own reason, and is not called unopened.
        self.assertIn("回主城失败（没按到小地图的≡按钮）", result.message)
        self.assertNotIn(CARD_BY_ID["Q_sp5"].label, lead)
        # The 问题摘要's 「停在」 says it too.
        self.assertIn(CIRCLES_NOT_OPEN, collector.stages["当前阶段"])

    def test_other_skips_are_worded_as_before(self):
        collector = _collector()
        _skip(collector, "Q_sp5", "回主城失败（没按到小地图的≡按钮）")
        result = collector._with_skipped_cards(CollectionResult(True, message=""))
        self.assertNotIn(CIRCLES_NOT_OPEN, result.message)
        self.assertNotIn(CIRCLES_NOT_OPEN, collector.stages["当前阶段"])

    def _phase_run(self, message):
        statuses = {}
        problems = []
        task = object.__new__(MapCollectionTask)
        task.config = {}
        task.info_set = statuses.__setitem__
        task.log_info = lambda *_a, **_k: None
        task.log_warning = lambda *_a, **_k: None
        task.log_error = lambda *_a, **_k: None
        task.log_completion = lambda *_a, **_k: None
        task._save_diagnostic = lambda *_a: None
        task._note_phase_problem = lambda how, note: problems.append(note)
        navigator = SimpleNamespace(
            return_home=lambda: NavigationResult(True, ScreenState.HOME, "主页")
        )
        ok = task._run_phases(
            navigator,
            (("地图采集", None, lambda: CollectionResult(False, message=message)),),
        )
        self.assertFalse(ok)
        return statuses, problems

    def test_the_status_line_says_why_not_only_unfinished(self):
        _, result = self._skipped_run()
        statuses, problems = self._phase_run(result.message)
        status = statuses["状态"]
        self.assertTrue(status.startswith("跑图部分流程未完成："), status)
        self.assertIn(CIRCLES_NOT_OPEN, status)
        self.assertIn("卢戈森林深处", status)
        # The 问题摘要 keeps the whole message.
        self.assertIn(CIRCLES_NOT_OPEN, problems[0])
        # Its reason is seen as one: the failure reason step leaves it alone.
        self.assertTrue(failure_reason.has_reason(status, "每周跑图"))
        # A 一键日常 row (cut short) still names it.
        row = failure_note(SimpleNamespace(name="每周跑图", info={"状态": status}))
        self.assertIn(CIRCLES_NOT_OPEN, row)

    def test_a_long_reason_is_cut_on_the_status_line(self):
        statuses, _problems = self._phase_run(CIRCLES_NOT_OPEN + "：" + "很长" * 200)
        self.assertLess(len(statuses["状态"]), 140)
        self.assertTrue(statuses["状态"].endswith("…。"))

    def test_without_a_message_the_status_stays_as_before(self):
        statuses, _problems = self._phase_run("")
        self.assertEqual("跑图部分流程未完成。", statuses["状态"])

    def test_traditional_chinese_players_read_it_in_their_words(self):
        # The app set to 繁中 shows these lines through OpenCC (s2twp).
        _, result = self._skipped_run()
        statuses, _problems = self._phase_run(result.message)
        shown = to_traditional(statuses["状态"])
        self.assertIn("疑似未開齊地圖傳送陣", shown)
        self.assertIn("跑圖部分流程未完成", shown)
        self.assertIn("請先在遊戲裡走到那張圖開啟傳送陣", to_traditional(result.message))
        self.assertIn("盧戈森林深處的傳送頁上沒有可用的傳送陣", to_traditional(circles_not_open_message("卢戈森林深处")))


if __name__ == "__main__":
    unittest.main()
