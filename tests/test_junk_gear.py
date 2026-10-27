import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.utils.junk_gear import (
    GearItem,
    agreed_rarity,
    classify,
    colour_rarity,
    leading_new_cells,
    load_exclusive_stars,
    new_marker_ratio,
    ocr_rarity,
)


def label(hues):
    """A label image whose coloured pixels use the given OpenCV hues."""
    hsv = np.zeros((40, 40, 3), dtype=np.uint8)
    hsv[:, :, 1] = 200
    hsv[:, :, 2] = 220
    for index, hue in enumerate(hues):
        hsv[:, index * 40 // len(hues) : (index + 1) * 40 // len(hues), 0] = hue
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)



def _blank():
    return np.zeros((1080, 1920, 3), np.uint8)


def _grid_passes(task, rarity="R"):
    """The grid shows an unlocked, unworn, unenhanced item of ``rarity``."""
    task._badged_cells = lambda: set()
    task._older_cell_kept = lambda *_a, **_k: ""
    task._grid_rarity = lambda _frame, _cell: rarity


def _filter_stubs(task, original=None):
    """The bag filter reads ``original`` and every change works."""
    state = original or {"grade": None, "worn": True}
    task._saved_filter = lambda: None
    task._save_filter = lambda _state: None
    task._clear_saved_filter = lambda: None
    task._read_bag_filter = lambda: dict(state)
    task.filter_sets = []
    task._set_bag_filter = lambda wanted: task.filter_sets.append(dict(wanted)) or True

class JunkRulesTest(unittest.TestCase):
    STARS = {"掠夺之手": 4, "卢戈制衬衫": 3, "噬血者": 5, "恋的头饰": 5}

    def item(self, name, rarity, **flags):
        return GearItem(name, rarity, flags.get("equipped", False),
                        flags.get("locked", False), flags.get("enhanced", False))

    def test_live_items_from_2026_09_26(self):
        self.assertTrue(classify(self.item("掠夺之手", "R"), self.STARS)[0])
        self.assertTrue(classify(self.item("飞翅骷髅", "R"), self.STARS)[0])
        self.assertTrue(classify(self.item("卢戈制衬衫", "UR"), self.STARS)[0])
        self.assertFalse(classify(self.item("噬血者", "UR"), self.STARS)[0])

    def test_uncertain_items_are_kept(self):
        self.assertFalse(classify(self.item("未知装备", "UR"), self.STARS)[0])
        self.assertFalse(classify(self.item("掠夺之手", None), self.STARS)[0])
        self.assertFalse(classify(self.item("某装备", "N"), self.STARS)[0])

    def test_equipped_locked_or_enhanced_are_never_junk(self):
        for flag in ("equipped", "locked", "enhanced"):
            self.assertFalse(classify(self.item("掠夺之手", "R", **{flag: True}), self.STARS)[0])

    def test_toggles(self):
        self.assertFalse(
            classify(self.item("掠夺之手", "SR"), self.STARS, dismantle_r_sr=False)[0]
        )
        self.assertFalse(
            classify(self.item("卢戈制衬衫", "UR"), self.STARS, dismantle_low_star_ur=False)[0]
        )


class RarityReadingTest(unittest.TestCase):
    def test_ocr_tokens(self):
        self.assertEqual("UR", ocr_rarity("JR"))
        self.assertEqual("UR", ocr_rarity("UR"))
        self.assertEqual("R", ocr_rarity("R"))
        self.assertEqual("SR", ocr_rarity("SR"))
        self.assertIsNone(ocr_rarity("掠夺之手"))

    def test_label_colours(self):
        self.assertEqual("R", colour_rarity(label([106])))
        self.assertEqual("SR", colour_rarity(label([140])))
        self.assertEqual("UR", colour_rarity(label([30, 60, 100, 140, 160])))

    def test_text_and_colour_must_agree(self):
        # A UR whose "U" was dropped by OCR must not become an R.
        self.assertIsNone(agreed_rarity("R", label([30, 60, 100, 140, 160])))
        self.assertEqual("R", agreed_rarity("R", label([106])))

    def test_live_label_crops_if_available(self):
        shots = Path(".local-dev/shots")
        cases = {"label_it0.png": "R", "label_it_904.png": "UR", "label_it_lock.png": "UR"}
        if not all((shots / name).exists() for name in cases):
            self.skipTest("live label crops not present")
        for name, expected in cases.items():
            self.assertEqual(expected, colour_rarity(cv2.imread(str(shots / name))), name)


class NewMarkerTest(unittest.TestCase):
    COLUMNS = (778, 904, 1030, 1156, 1282, 1408, 1534, 1660)
    ROWS = (207, 333, 459, 585, 711, 837)

    def frame_with_markers(self, cells):
        frame = np.full((1080, 1920, 3), (60, 40, 40), dtype=np.uint8)
        for row, column in cells:
            x, y = self.COLUMNS[column] + 42, self.ROWS[row] - 68
            cv2.rectangle(frame, (x + 4, y + 4), (x + 22, y + 22), (0, 150, 255), -1)
        return frame

    def test_contiguous_new_items_from_the_top_left(self):
        frame = self.frame_with_markers([(0, 0), (0, 1), (0, 2), (0, 3)])
        self.assertEqual(
            [(0, 0), (0, 1), (0, 2), (0, 3)],
            leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=10),
        )

    def test_scan_stops_at_the_first_unmarked_cell_and_at_the_cap(self):
        frame = self.frame_with_markers([(0, 0), (0, 2)])
        self.assertEqual([(0, 0)], leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=10))
        frame = self.frame_with_markers([(0, c) for c in range(8)] + [(1, 0)])
        self.assertEqual(9, len(leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=10)))
        self.assertEqual(3, len(leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=3)))

    def test_no_marker_means_nothing(self):
        frame = self.frame_with_markers([])
        self.assertEqual([], leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=10))

    def test_live_bag_frames_if_available(self):
        # Both frames (star sort and newest-first sort) had one new item.
        for name in ("bn2.png", "so4.png"):
            path = Path(".local-dev/shots") / name
            if not path.exists():
                self.skipTest("live bag frames not present")
            frame = cv2.imread(str(path))
            self.assertGreater(new_marker_ratio(frame, (778, 207)), 0.2, name)
            self.assertEqual(
                [(0, 0)], leading_new_cells(frame, self.COLUMNS, self.ROWS, cap=10), name
            )

    def test_table_covers_the_live_items(self):
        stars = load_exclusive_stars()
        for name, star in (("掠夺之手", 4), ("卢戈制衬衫", 3), ("飞翅骷髅", 4),
                           ("J收藏品", 4), ("噬血者", 5), ("恋的头饰", 5)):
            self.assertEqual(star, stars.get(name), name)


if __name__ == "__main__":
    unittest.main()


class JunkTaskParsingTest(unittest.TestCase):
    def test_sort_labels(self):
        from types import SimpleNamespace as Box

        from src.tasks.JunkGearTask import active_sort_label

        self.assertEqual(
            "按星级从高到低排序",
            active_sort_label([Box(name="按星级从高到低排序↓"), Box(name="按获得时间排序")]),
        )
        self.assertEqual(
            "按获得时间从晚到早排序",
            active_sort_label([Box(name="按星级排序"), Box(name="按获得时间从晚到早排序▼")]),
        )


class JunkSafetyTest(unittest.TestCase):
    """Guards added after the 2026-09-26 stability review."""

    @staticmethod
    def _task():
        from types import SimpleNamespace

        from src.tasks.JunkGearTask import JunkGearTask

        task = object.__new__(JunkGearTask)
        task.name = "爛装强化分解"
        task.config = {}
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: task.info.setdefault("warnings", []).append(a[0])
        task.sleep = lambda *_a: None
        task._executor = SimpleNamespace()
        return task

    def test_cell_similarity_separates_same_and_other_items(self):
        from src.tasks.JunkGearTask import SELECTION_MATCH_MIN, cell_similarity

        rng = np.random.default_rng(7)
        first = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        other = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        self.assertGreater(cell_similarity(first, first.copy(), (0, 0)), 0.99)
        self.assertLess(cell_similarity(first, other, (0, 0)), SELECTION_MATCH_MIN)

    def test_wait_detail_needs_the_requested_state(self):
        task = self._task()
        states = iter([True, True, False])
        task._detail_open = lambda: next(states)
        self.assertTrue(task._wait_detail(False, timeout=60))
        task._detail_open = lambda: True
        self.assertFalse(task._wait_detail(False, timeout=0))

    def test_a_stale_popup_keeps_every_item(self):
        # The detail popup never closes: nothing is judged, and the run is a
        # failure (None), not "no junk".
        from unittest import mock

        task = self._task()
        clicks = []
        task._click_reference = lambda x, y, after_sleep=0: clicks.append((x, y))
        task._wait_detail = lambda open_, timeout=0: open_
        _grid_passes(task, rarity="SR")
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            self.assertIsNone(task._classify_cells([(0, 0), (0, 1)], {}, _blank(), grade="SR"))
        self.assertEqual([], clicks)

    def test_selection_is_cancelled_when_cells_moved(self):
        from src.tasks import JunkGearTask as module

        task = self._task()
        clicks = []
        selection = {"on": False}

        def click(x, y, after_sleep=0):
            clicks.append((x, y))
            selection["on"] = (x, y) == module.ONE_CLICK_ENHANCE_POINT

        task._click_reference = click
        task._selection_count = lambda: 0 if selection["on"] else None
        task._bottom_right_text = lambda: "取消" if selection["on"] else "一键分解"
        rng = np.random.default_rng(3)
        classified = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        moved = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        task.capture_frame = lambda: moved
        # Cancelled and back on the bag: this batch is not dismantled (None),
        # the run goes on (Leo 2026-10-11 「又整個失敗吧」).
        self.assertIsNone(task._enhance_and_dismantle([(0, 0)], classified))
        # Only 一键强化 and 取消: no cell was selected.
        self.assertEqual(
            [module.ONE_CLICK_ENHANCE_POINT, module.SELECTION_CANCEL_POINT], clicks
        )

    def test_saved_sort_round_trip(self):
        import tempfile
        from unittest import mock

        from src.tasks import JunkGearTask as module

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "configs" / "junk_gear_sort.json"
            with mock.patch.object(module, "SORT_STATE_FILE", path):
                self.assertIsNone(module.JunkGearTask._saved_sort())
                module.JunkGearTask._save_sort("按星级从高到低排序")
                self.assertEqual("按星级从高到低排序", module.JunkGearTask._saved_sort())
                module.JunkGearTask._clear_saved_sort()
                self.assertIsNone(module.JunkGearTask._saved_sort())

    def test_unrestorable_saved_sort_stops_before_switching(self):
        import json
        import tempfile
        import time
        from unittest import mock

        task = self._task()
        task._open_equipment_bag = lambda: True
        _filter_stubs(task)
        task._saved_sort = lambda: "按星级从高到低排序"
        task._restore_sort = lambda original: False
        task._switch_to_newest_first = mock.Mock()
        with tempfile.TemporaryDirectory() as folder:
            # The first failure of a fresh save (review #22: later ones drop it).
            path = Path(folder) / "junk_gear_sort.json"
            path.write_text(
                json.dumps({"original": "按星级从高到低排序", "saved": time.time()}),
                encoding="utf-8",
            )
            with (
                mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={}),
                mock.patch("src.tasks.JunkGearTask._sort_state_file", return_value=path),
            ):
                self.assertFalse(task.run_claim())
        task._switch_to_newest_first.assert_not_called()

    def test_stop_mid_run_clicks_nothing_more(self):
        from unittest import mock

        from ok.task.exceptions import TaskDisabledException

        task = self._task()
        task._open_equipment_bag = lambda: True
        _filter_stubs(task)
        task._saved_sort = lambda: None
        task._clear_saved_sort = mock.Mock()
        task._switch_to_newest_first = lambda: "按星级从高到低排序"
        task._restore_sort = mock.Mock()

        def stop():
            raise TaskDisabledException()

        task.capture_frame = stop
        with mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={}):
            with self.assertRaises(TaskDisabledException):
                task.run_claim()
        # The sort is restored on the next run from the saved file instead.
        task._restore_sort.assert_not_called()


class SelectionRetryTest(unittest.TestCase):
    """Leo 2026-10-11 「你不會又點一次沒點到 或者 沒辨識到 又整個失敗吧」: a
    pick tap that did not take is cancelled and picked again once; a second
    miss leaves this batch, and the run goes on.  Only the planned cells are
    ever tapped."""

    CELLS = [(0, 0), (0, 1)]

    def _task(self, cell_misses=0, enter_misses=0, cancel_works=True, counter_reads=True):
        from unittest import mock

        from src.tasks import JunkGearTask as module

        clock = [0.0]
        for target, value in (
            ("monotonic", lambda: clock[0]),
            ("SLOW_PC_GRACE_SECONDS", 0),
        ):
            patcher = mock.patch(f"src.tasks.JunkGearTask.{target}", value)
            patcher.start()
            self.addCleanup(patcher.stop)
        task = JunkSafetyTest._task()
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        frame = np.random.default_rng(5).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        task.classified = frame
        task.capture_frame = lambda: frame
        screen = {"selection": False, "count": 0}
        misses = {"cell": cell_misses, "enter": enter_misses}
        task.clicks = []
        cell_points = {(module.GRID_COLUMNS[c], module.GRID_ROWS[r]) for r, c in self.CELLS}

        def click(x, y, after_sleep=0):
            task.clicks.append((x, y))
            clock[0] += after_sleep
            if (x, y) == module.ONE_CLICK_ENHANCE_POINT:
                if misses["enter"]:
                    misses["enter"] -= 1
                else:
                    screen.update(selection=True, count=0)
            elif (x, y) == module.SELECTION_CANCEL_POINT:
                screen["selection"] = not cancel_works
            elif (x, y) in cell_points:
                if misses["cell"]:
                    misses["cell"] -= 1
                else:
                    screen["count"] += 1

        task._click_reference = click
        task._selection_count = lambda: (
            screen["count"] if screen["selection"] and counter_reads else None
        )
        task._bottom_right_text = lambda: "取消" if screen["selection"] else "一键分解"
        task._prepare_enhance_dialog = lambda planned: True
        task._enhance_start_box = lambda: "开始强化"
        task.started = []
        task._click_reference_box = lambda box, after_sleep=0: task.started.append(box)
        task._settle_enhance_result = lambda planned: True
        task.cell_points = cell_points
        return task, module

    def test_a_missed_pick_is_picked_again(self):
        task, module = self._task(cell_misses=1)
        self.assertTrue(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertEqual(1, task.clicks.count(module.SELECTION_CANCEL_POINT))
        self.assertEqual(["开始强化"], task.started)

    def test_two_wrong_counts_leave_this_batch(self):
        task, module = self._task(cell_misses=99)
        self.assertIsNone(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertEqual(2, task.clicks.count(module.SELECTION_CANCEL_POINT))
        self.assertEqual([], task.started)
        self.assertNotIn(module.SELECTION_CONFIRM_POINT, task.clicks)

    def test_only_planned_cells_are_tapped(self):
        task, module = self._task(cell_misses=99)
        task._enhance_and_dismantle(self.CELLS, task.classified)
        others = {
            module.ONE_CLICK_ENHANCE_POINT,
            module.SELECTION_CANCEL_POINT,
        }
        self.assertTrue(all(c in task.cell_points or c in others for c in task.clicks))

    def test_a_missed_enhance_tap_is_tapped_once_more(self):
        task, module = self._task(enter_misses=1)
        self.assertTrue(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertEqual(2, task.clicks.count(module.ONE_CLICK_ENHANCE_POINT))

    def test_enhance_tap_dead_twice_leaves_this_batch(self):
        task, module = self._task(enter_misses=99)
        self.assertIsNone(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertEqual([module.ONE_CLICK_ENHANCE_POINT] * 2, task.clicks)

    def test_a_cancel_that_does_not_leave_selection_is_a_failure(self):
        task, _module = self._task(cell_misses=99, cancel_works=False)
        self.assertIs(False, task._enhance_and_dismantle(self.CELLS, task.classified))

    def test_an_unread_counter_picks_nothing_and_goes_on(self):
        # Selection mode opened (取消 where 一键分解 was) but N/2000 reads
        # nothing: no cell is tapped, 取消 goes back to the bag.
        task, module = self._task(counter_reads=False)
        self.assertIsNone(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertEqual(
            [module.ONE_CLICK_ENHANCE_POINT, module.SELECTION_CANCEL_POINT], task.clicks
        )

    def test_cancel_is_never_tapped_while_the_bag_shows_dismantle(self):
        # On the bag the 取消 spot is 一键分解.
        task, module = self._task()
        self.assertTrue(task._cancel_selection())
        self.assertEqual([], task.clicks)

    def test_a_wrong_enhance_dialog_cancels_and_goes_on(self):
        task, module = self._task()
        task._prepare_enhance_dialog = lambda planned: False
        self.assertIsNone(task._enhance_and_dismantle(self.CELLS, task.classified))
        self.assertIn(module.ENHANCE_CANCEL_POINT, task.clicks)
        self.assertEqual([], task.started)


try:
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
except ImportError:  # pragma: no cover - the tool always ships onnxocr
    ONNXPaddleOcr = None


class BagButtonsReadTest(unittest.TestCase):
    """The 取消 spot of selection mode is 一键分解 on the bag, so the tool
    must read 一键分解 there.  Frame: Leo's 4K bag after the 10-11 real run."""

    @unittest.skipIf(ONNXPaddleOcr is None, "onnxocr not installed")
    def test_the_dismantle_button_reads_where_cancel_would_be(self):
        from src.tasks.JunkGearTask import BOTTOM_RIGHT_BUTTON_ROI

        folder = Path(__file__).parent / "fixtures" / "junk_gear"
        crop = cv2.imread(str(folder / "bag_bottom_buttons_leo_4k_at_1080.jpg"))
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[950 : 950 + crop.shape[0], 1150 : 1150 + crop.shape[1]] = crop
        x, y, w, h = BOTTOM_RIGHT_BUTTON_ROI
        engine = ONNXPaddleOcr(use_angle_cls=False, use_openvino=True)
        text = "".join(t for _b, (t, _s) in engine.ocr(frame[y : y + h, x : x + w])[0] or [])
        self.assertIn("分解", text)


class EnhanceResultTest(unittest.TestCase):
    """The result overlay closes on a tap on blank space; an unread result
    gets that tap once (Leo 10-11 fixed-position last resort)."""

    def _task(self, results, bag_after_tap=True):
        from unittest import mock

        from src.tasks import JunkGearTask as module

        clock = [0.0]
        patcher = mock.patch("src.tasks.JunkGearTask.monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        task = JunkSafetyTest._task()
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        task.capture_frame = lambda: None
        texts = iter(results)
        task._roi_boxes = lambda _f, _roi, _name: [SimpleNamespace(name=next(texts, ""))]
        task.clicks = []
        screen = {"bag": False}

        def click(x, y, after_sleep=0):
            task.clicks.append((x, y))
            clock[0] += after_sleep
            screen["bag"] = bag_after_tap

        task._click_reference = click
        task._title_visible = lambda *_a: screen["bag"]
        return task, module

    def test_a_read_result_is_closed_and_counted(self):
        task, module = self._task(["强化结果 已分解共2个装备"])
        self.assertTrue(task._settle_enhance_result(2))
        self.assertEqual([module.NEUTRAL_TAP_POINT], task.clicks)

    def test_an_unread_result_gets_one_blank_tap(self):
        task, module = self._task([])
        self.assertTrue(task._settle_enhance_result(2))
        self.assertEqual([module.NEUTRAL_TAP_POINT], task.clicks)

    def test_no_bag_after_the_tap_is_a_failure(self):
        task, module = self._task([], bag_after_tap=False)
        self.assertFalse(task._settle_enhance_result(2))
        self.assertEqual([module.NEUTRAL_TAP_POINT], task.clicks)


class TitleParsingTest(unittest.TestCase):
    """Live 2026-09-27: 拉菲娜's SR E.P.G was kept as unreadable."""

    @staticmethod
    def _box(name, x):
        from types import SimpleNamespace

        return SimpleNamespace(name=name, x=x, y=340, width=60, height=24)

    def _parse(self, *boxes):
        from src.tasks.JunkGearTask import JunkGearTask

        name, rarity = JunkGearTask._name_and_rarity(list(boxes))
        return (name.name if name else None, rarity.name if rarity else None)

    def test_separate_boxes(self):
        parsed = self._parse(self._box("E.P.G", 500), self._box("SR", 580))
        self.assertEqual(("E.P.G", "SR"), parsed)

    def test_rarity_glued_to_the_name(self):
        self.assertEqual(("E.P.G", "SR"), self._parse(self._box("E.P.G SR", 500)))

    def test_rarity_touching_a_chinese_name(self):
        # Live 2K 2026-09-29: no space between the name and the italic R.
        self.assertEqual(("冰雪红宝石", "R"), self._parse(self._box("冰雪红宝石R X", 500)))
        self.assertEqual(("冰雪红宝石", "UR"), self._parse(self._box("冰雪红宝石UR", 500)))

    def test_stray_mark_after_the_rarity(self):
        parsed = self._parse(self._box("E.P.G", 500), self._box("SR X", 580))
        self.assertEqual(("E.P.G", "SR"), parsed)

    def test_no_rarity_stays_unreadable(self):
        self.assertEqual(("E.P.G", None), self._parse(self._box("E.P.G", 500)))


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "junk_gear"


class GridShortcutTest(unittest.TestCase):
    """User 2026-09-27: R/SR off the grid label; locked cells never touched."""

    def _placed(self, crop, box, cell=(0, 0)):
        from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS

        frame = np.zeros((1080, 1920, 3), np.uint8)
        dx, dy, _w, _h = box
        x, y = GRID_COLUMNS[cell[1]] + dx, GRID_ROWS[cell[0]] + dy
        frame[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
        return frame

    def test_live_labels(self):
        from src.utils.junk_gear import grid_label_rarity

        sr = cv2.imread(str(FIXTURES / "grid_label_sr.png"))
        ur = cv2.imread(str(FIXTURES / "grid_label_ur.png"))
        self.assertEqual("SR", grid_label_rarity(sr))  # beside golden gauntlet art
        self.assertEqual("UR", grid_label_rarity(ur))

    def test_live_padlock(self):
        from src.tasks.JunkGearTask import GRID_LOCK_SEARCH_BOX, grid_cell_locked

        on = cv2.imread(str(FIXTURES / "grid_lock_on.png"))
        off = cv2.imread(str(FIXTURES / "grid_lock_off.png"))
        self.assertTrue(grid_cell_locked(self._placed(on, GRID_LOCK_SEARCH_BOX), (0, 0)))
        self.assertFalse(grid_cell_locked(self._placed(off, GRID_LOCK_SEARCH_BOX), (0, 0)))

    def _task(self):
        from src.tasks.JunkGearTask import JunkGearTask

        task = object.__new__(JunkGearTask)
        task.config = {}
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.clicks = []
        task._click_reference = lambda x, y, after_sleep=0: task.clicks.append((x, y))
        # No frame: the ✕ is pressed at its usual place.
        task.capture_frame = lambda: None
        return task

    def test_locked_cell_is_never_clicked_or_dismantled(self):
        from unittest import mock

        task = self._task()
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=True):
            self.assertEqual([], task._classify_cells([(0, 0)], {}, np.zeros((1080, 1920, 3))))
        self.assertEqual([], task.clicks)

    def test_a_cell_of_another_grade_is_never_opened(self):
        # The filter shows one grade; a label read as anything else (UR, or
        # unread) is kept unopened (Leo 2026-10-11 「只拆 R/SR」).
        from unittest import mock

        for read in ("UR", "R", None):
            task = self._task()
            _grid_passes(task, rarity=read)
            with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
                self.assertEqual([], task._classify_cells([(0, 0)], {}, _blank(), grade="SR"))
            self.assertEqual([], task.clicks)

    def test_a_grid_sr_is_opened_before_it_counts(self):
        # SR comes as 5★ exclusives too (翼角头盔 SR, Leo's bag 2026-10-11).
        from unittest import mock

        task = self._task()
        _grid_passes(task, rarity="SR")
        task._wait_detail = lambda open_, timeout=0: open_ is False or True
        opened = []
        task._read_detail = lambda: opened.append(1) or (None, "")
        task.sleep = lambda *a: None
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            task._classify_cells([(0, 0)], {}, _blank(), grade="SR")
        self.assertTrue(opened)

    def test_the_5_star_sr_setting_reaches_the_rule(self):
        from unittest import mock

        from src.tasks.JunkGearTask import FIVE_STAR_SR_KEY
        from src.utils.junk_gear import GearItem

        task = self._task()
        # On, SR never reaches it: dismantled off the grid (test below).
        for setting in (False,):
            task.config = {FIVE_STAR_SR_KEY: setting}
            _grid_passes(task, rarity="SR")
            task._wait_detail = lambda *a, **k: True
            item = GearItem("翼角头盔", "SR", False, False, False, owner_line="格兰希特")
            task._read_detail = lambda: (item, "专用装备")
            task.sleep = lambda *a: None
            task.press_and_confirm = lambda *a, **k: mock.Mock(confirmed=True)
            seen = []
            with (
                mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False),
                mock.patch(
                    "src.tasks.JunkGearTask.classify_low_grade",
                    side_effect=lambda *a, **k: seen.append(k["five_star_sr"]) or (False, "x"),
                ),
            ):
                task._classify_cells([(0, 0)], {}, _blank(), grade="SR")
            self.assertEqual([setting], seen)

    def test_5_star_on_skips_opening_filtered_sr(self):
        # Leo 2026-10-15 「sr就不用點開了 直接r sr全拆」.
        from unittest import mock

        from src.tasks.JunkGearTask import FIVE_STAR_SR_KEY

        task = self._task()
        task.config = {FIVE_STAR_SR_KEY: True}
        _grid_passes(task, rarity="SR")
        task._wait_detail = lambda *a, **k: self.fail("detail opened")
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            self.assertEqual(
                [(0, 0), (0, 1)],
                task._classify_cells([(0, 0), (0, 1)], {}, _blank(), grade="SR"),
            )
        self.assertEqual([], task.clicks)

    def test_5_star_on_skips_opening_sr_in_every_pass(self):
        # Unfiltered and 「!」 passes too (Leo 2026-10-15 「你直接拆sr」).
        from unittest import mock

        from src.tasks.JunkGearTask import FIVE_STAR_SR_KEY

        task = self._task()
        task.config = {FIVE_STAR_SR_KEY: True}
        _grid_passes(task, rarity="SR")
        task._wait_detail = lambda *a, **k: self.fail("detail opened")
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            self.assertEqual([(0, 0)], task._classify_cells([(0, 0)], {}, _blank(), grade=None))
        self.assertEqual([], task.clicks)

    def test_5_star_on_still_keeps_locked_and_enhanced_sr(self):
        from unittest import mock

        from src.tasks.JunkGearTask import FIVE_STAR_SR_KEY

        task = self._task()
        task.config = {FIVE_STAR_SR_KEY: True}
        _grid_passes(task, rarity="SR")
        task._older_cell_kept = lambda *_a, **_k: "已强化"
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            self.assertEqual([], task._classify_cells([(0, 0)], {}, _blank(), grade="SR"))
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=True):
            self.assertEqual([], task._classify_cells([(0, 0)], {}, _blank(), grade="SR"))

    def test_a_grid_r_is_junk_without_opening_it(self):
        # Leo 2026-10-11 「r不點開」.
        from unittest import mock

        task = self._task()
        _grid_passes(task, rarity="R")
        task._wait_detail = lambda *a, **k: self.fail("detail opened")
        with mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False):
            self.assertEqual([(0, 0)], task._classify_cells([(0, 0)], {}, _blank(), grade="R"))
        self.assertEqual([], task.clicks)


class NewBadgeLabelTest(unittest.TestCase):
    """Live 2026-09-27: the yellow "!" beside a new item's label hid its R."""

    def test_labels_next_to_the_new_badge(self):
        from src.utils.junk_gear import grid_label_rarity

        r_new = cv2.imread(str(FIXTURES / "grid_label_r_new.png"))
        ur_new = cv2.imread(str(FIXTURES / "grid_label_ur_new.png"))
        self.assertEqual("R", grid_label_rarity(r_new))
        self.assertEqual("UR", grid_label_rarity(ur_new))

    def test_ocr_with_the_badge_glued_on(self):
        from src.tasks.JunkGearTask import grid_label_text_matches

        self.assertTrue(grid_label_text_matches("R!", "R"))
        self.assertTrue(grid_label_text_matches("RI", "R"))
        self.assertTrue(grid_label_text_matches("SR 1", "SR"))
        self.assertFalse(grid_label_text_matches("UR", "R"))
        self.assertFalse(grid_label_text_matches("UR", "SR"))
        self.assertFalse(grid_label_text_matches("", "R"))


class SortMenuSearchTest(unittest.TestCase):
    """Live 2026-09-28 at 1080p: 6-notch jumps skipped the middle option."""

    def test_small_steps_find_an_option_in_the_middle(self):
        from types import SimpleNamespace

        from src.tasks.JunkGearTask import JunkGearTask

        pages = [["按获得时间"], ["按星级"], ["按强化从高到低排序"], ["按套装"], ["按套装"]]
        position = [0]
        task = object.__new__(JunkGearTask)
        task._sort_menu_boxes = lambda: [SimpleNamespace(name=n) for n in pages[position[0]]]
        task._boxes_text = lambda boxes: " ".join(b.name for b in boxes)

        def scroll(_point, notches, **_kwargs):
            step = 1 if notches > 0 else -1
            position[0] = max(0, min(len(pages) - 1, position[0] + step))

        task.scroll_client = scroll
        boxes = task._find_sort_option("按强化从")
        self.assertEqual("按强化从高到低排序", boxes[0].name)


class GridLabelCertaintyTest(unittest.TestCase):
    """Leo 2026-09-30: R/SR are judged on the grid without opening them."""

    @staticmethod
    def _label(*hues):
        import cv2
        import numpy as np

        # One vertical stripe per hue (OpenCV hue 0-179), full saturation/value.
        stripes = [np.full((32, 12, 3), (h, 255, 255), np.uint8) for h in hues]
        return cv2.cvtColor(np.hstack(stripes), cv2.COLOR_HSV2BGR)

    def test_pure_blue_is_certainly_r(self):
        from src.utils.junk_gear import grid_label_colour_certain

        self.assertTrue(grid_label_colour_certain(self._label(110, 112, 108), "R"))
        self.assertFalse(grid_label_colour_certain(self._label(110, 112, 108), "SR"))

    def test_pure_purple_is_certainly_sr(self):
        from src.utils.junk_gear import grid_label_colour_certain

        self.assertTrue(grid_label_colour_certain(self._label(140, 145, 150), "SR"))

    def test_any_green_is_never_certain(self):
        from src.utils.junk_gear import grid_label_colour_certain

        # A UR gradient: green, blue and purple bands.
        self.assertFalse(grid_label_colour_certain(self._label(60, 110, 140), "R"))
        self.assertFalse(grid_label_colour_certain(self._label(110, 110, 110, 110, 110, 60), "R"))

    def test_cyan_tinted_r_at_2k(self):
        from src.utils.junk_gear import grid_label_colour_certain, grid_label_rarity

        # Live 2K: R letters span hue 90-109 (the old 35-95 green band made
        # every R unsure).
        cyan_r = self._label(92, 97, 102, 106, 106, 106)
        self.assertEqual("R", grid_label_rarity(cyan_r))
        self.assertTrue(grid_label_colour_certain(cyan_r, "R"))

    def test_new_r_with_a_red_trace_from_its_badge(self):
        from src.utils.junk_gear import grid_label_colour_certain, grid_label_rarity

        # Live 2K 2026-10-22: 「绿0.00 青蓝0.94 紫0.00」 beside the new 「!」
        # (6 % red) was left 「认不出」 and the R kept.
        r_with_red = self._label(*([106] * 16 + [3]))
        self.assertEqual("R", grid_label_rarity(r_with_red))
        self.assertTrue(grid_label_colour_certain(r_with_red, "R"))
        # With purple as well it is not certain (the label OCR decides).
        self.assertFalse(grid_label_colour_certain(self._label(*([106] * 14 + [3, 140, 140])), "R"))

    def test_ur_gradient_or_green_n_is_never_r(self):
        from src.utils.junk_gear import grid_label_colour_certain, grid_label_rarity

        gradient = self._label(40, 70, 90, 100, 105, 110, 130, 150)
        self.assertNotIn(grid_label_rarity(gradient), ("R", "SR"))
        self.assertFalse(grid_label_colour_certain(gradient, "R"))
        green_n = self._label(60, 62, 65)
        self.assertNotIn(grid_label_rarity(green_n), ("R", "SR"))
        self.assertFalse(grid_label_colour_certain(green_n, "R"))

    def test_live_2k_labels(self):
        from src.utils.junk_gear import grid_label_colour_certain, grid_label_rarity

        # 珍藏集 at 2560x1440 resized to 1080 like the bag frame (2026-09-30).
        r = cv2.imread(str(FIXTURES / "grid_label_r_2k.png"))
        sr = cv2.imread(str(FIXTURES / "grid_label_sr_2k.png"))
        ur = cv2.imread(str(FIXTURES / "grid_label_ur_2k.png"))
        self.assertEqual("R", grid_label_rarity(r))
        self.assertTrue(grid_label_colour_certain(r, "R"))
        self.assertEqual("SR", grid_label_rarity(sr))
        self.assertTrue(grid_label_colour_certain(sr, "SR"))
        self.assertEqual("UR", grid_label_rarity(ur))
        self.assertFalse(grid_label_colour_certain(ur, "R"))
        self.assertFalse(grid_label_colour_certain(ur, "SR"))

    def test_u_in_the_read_blocks_the_colour_shortcut(self):
        from src.utils.junk_gear import label_text_looks_ur

        self.assertTrue(label_text_looks_ur("UR"))
        self.assertTrue(label_text_looks_ur("JR!"))
        self.assertFalse(label_text_looks_ur(""))
        self.assertFalse(label_text_looks_ur("R!"))
        self.assertFalse(label_text_looks_ur("SR"))


class LoneDigitsTest(unittest.TestCase):
    def test_letters_read_for_a_lone_digit(self):
        from src.tasks.enhance_dialog import lone_digits

        # Live 2K 2026-09-30: 已选择装备 "4" read as "a".
        self.assertEqual("4", lone_digits("a"))
        self.assertEqual("10", lone_digits("lO"))
        self.assertEqual("7", lone_digits("7"))
        self.assertEqual("强化", lone_digits("强化"))
        self.assertEqual("abcd", lone_digits("abcd"))


class PendingListGoneTest(unittest.TestCase):
    """The "!" version carried junk in a file; a filtered bag shows the same
    junk next run, so the old file is only removed."""

    def test_the_old_list_is_removed(self):
        import tempfile
        from unittest import mock

        from src.tasks.JunkGearTask import JunkGearTask

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "junk_gear_pending.json"
            path.write_text("{}", encoding="utf-8")
            with mock.patch("src.tasks.JunkGearTask._pending_file", return_value=path):
                object.__new__(JunkGearTask)._clear_pending()
            self.assertFalse(path.exists())


def _fake_press_clock(test):
    """press_and_confirm on a clock that ``task.sleep`` moves (no real waits)."""
    from functools import partial
    from unittest import mock

    from src.utils.press_confirm import press_and_confirm

    clock = [0.0]
    patcher = mock.patch(
        "src.tasks.BaseBD2Task._press_and_confirm",
        partial(press_and_confirm, clock=lambda: clock[0]),
    )
    patcher.start()
    test.addCleanup(patcher.stop)
    return lambda seconds: clock.__setitem__(0, clock[0] + seconds)


class DetailPressTest(unittest.TestCase):
    """A lost click on a new item or on the detail ✕ ended as "no junk": the
    run counted as done and those items lost their "!" for good."""

    def _task(self, opens_on, closes_on):
        """The popup opens on the ``opens_on``-th cell click and closes on the
        ``closes_on``-th ✕, blank-space or Esc press (0: never)."""
        from unittest import mock

        from src.tasks.JunkGearTask import (
            DETAIL_BLANK_TAP_POINT,
            DETAIL_CLOSE_POINT,
            JunkGearTask,
        )

        task = object.__new__(JunkGearTask)
        task.config = {}
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        # No frame: the ✕ is pressed at its usual place.
        task.capture_frame = lambda: None
        task.warnings = []
        task.log_warning = lambda message, **k: task.warnings.append(message)
        task.sleep = _fake_press_clock(self)
        task.cell_clicks, task.close_clicks = [], []
        state = {"open": False}

        def click(x, y, after_sleep=0):
            if (x, y) in (DETAIL_CLOSE_POINT, DETAIL_BLANK_TAP_POINT, ("Esc", None)):
                task.close_clicks.append((x, y))
                if len(task.close_clicks) == closes_on:
                    state["open"] = False
            else:
                task.cell_clicks.append((x, y))
                if len(task.cell_clicks) == opens_on:
                    state["open"] = True

        task._click_reference = click

        def escape(after_sleep=0):
            click("Esc", None)
            return True

        task.tap_escape = escape
        task._wait_detail = lambda open_, timeout=0: state["open"] == open_
        # A real 3★ exclusive with its owner line: only the clicks are tested.
        task._read_detail = lambda: (
            GearItem("猎人之弓", "SR", False, False, False, owner_line="莉兹内"), "专用装备"
        )
        _grid_passes(task, rarity="SR")
        patcher = mock.patch("src.tasks.JunkGearTask.grid_cell_locked", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    @staticmethod
    def _classify(cells, task):
        return task._classify_cells(cells, {"猎人之弓": 3}, _blank(), grade="SR")

    def test_a_lost_cell_click_is_pressed_once_more_while_the_grid_shows(self):
        task = self._task(opens_on=2, closes_on=1)
        self.assertEqual([(0, 0)], self._classify([(0, 0)], task))
        self.assertEqual(2, len(task.cell_clicks))
        self.assertEqual(1, len(task.close_clicks))

    def test_a_cell_that_never_opens_is_a_failure(self):
        task = self._task(opens_on=0, closes_on=1)
        self.assertIsNone(self._classify([(0, 0), (0, 1)], task))
        self.assertEqual(2, len(task.cell_clicks))
        self.assertEqual([], task.close_clicks)
        self.assertEqual(1, len(task.warnings))

    def test_a_lost_close_is_pressed_again_only_while_the_popup_shows(self):
        task = self._task(opens_on=1, closes_on=2)
        self.assertEqual([(0, 0)], self._classify([(0, 0)], task))
        self.assertEqual(2, len(task.close_clicks))

    def test_a_popup_that_never_closes_is_a_failure(self):
        task = self._task(opens_on=1, closes_on=0)
        self.assertIsNone(self._classify([(0, 0), (0, 1)], task))
        # Two ✕ presses, two blank-space taps and two Esc at most, and the
        # next item is never clicked.
        from src.tasks.JunkGearTask import DETAIL_BLANK_TAP_POINT, DETAIL_CLOSE_POINT

        self.assertEqual(
            [DETAIL_CLOSE_POINT] * 2 + [DETAIL_BLANK_TAP_POINT] * 2 + [("Esc", None)] * 2,
            task.close_clicks,
        )
        self.assertEqual(1, len(task.cell_clicks))

    def test_a_close_lost_on_the_x_is_done_by_a_blank_space_tap(self):
        # Player 2026-10-12: two ✕ presses showed nothing (the ✕ of a taller
        # popup was elsewhere); Leo 「點空白處也可以關」.
        from src.tasks.JunkGearTask import DETAIL_BLANK_TAP_POINT

        task = self._task(opens_on=1, closes_on=3)
        self.assertEqual([(0, 0)], self._classify([(0, 0)], task))
        self.assertEqual(DETAIL_BLANK_TAP_POINT, task.close_clicks[-1])


class SortLabelTest(unittest.TestCase):
    """Review #22: one misread of the player's sort, saved, failed every
    later run until the file was deleted by hand."""

    def test_a_label_one_character_off_is_the_same_sort(self):
        from src.tasks.JunkGearTask import same_sort

        self.assertTrue(same_sort("按稀有从高到低排序", "按稀有度从高到低排序"))
        self.assertTrue(same_sort("按强化从高到低排序", "按强化阶段从高到低排序"))
        self.assertFalse(same_sort("按稀有度从低到高排序", "按稀有度从高到低排序"))
        self.assertFalse(same_sort("按星级从高到低排序", "按级别从高到低排序"))
        self.assertFalse(same_sort("按获得时间从早到晚排序", "按获得时间从晚到早排序"))

    @staticmethod
    def _menu(active, kinds=("获得时间", "稀有度", "星级"), reads=()):
        """A sort menu showing ``active`` on top; ``reads`` are what the first
        reads see instead (the menu fading in)."""
        from types import SimpleNamespace as Box

        from src.tasks.JunkGearTask import (
            SORT_MENU_CLOSE_POINT,
            JunkGearTask,
            sort_category,
            sort_direction,
        )

        task = object.__new__(JunkGearTask)
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.sleep = lambda *a: None
        task.scroll_client = lambda *a, **k: None
        task.saved = []
        task._save_sort = task.saved.append
        task._clear_saved_sort = lambda: None
        task.menu = {"active": active, "open": True}
        pending = list(reads)

        def click(x, y, **_kwargs):
            # The menu closes now that closing is checked.
            if (x, y) == SORT_MENU_CLOSE_POINT:
                task.menu["open"] = False

        def open_menu():
            task.menu["open"] = True
            return boxes()

        def boxes():
            if not task.menu["open"]:
                return []
            label = pending.pop(0) if pending else task.menu["active"]
            current = sort_category(task.menu["active"])
            return [Box(name=label)] + [Box(name=f"按{k}排序") for k in kinds if k != current]

        def pick(box, after_sleep=0):
            first, second = ("晚到早", "早到晚") if "获得时间" in box.name else ("高到低", "低到高")
            if sort_direction(box.name):  # the active option flips
                kind = sort_category(task.menu["active"])
                now = sort_direction(task.menu["active"])
                direction = second if now == first else first
            else:
                kind, direction = sort_category(box.name), first
            task.menu["active"] = f"按{kind}从{direction}排序"

        task._sort_menu_boxes = boxes
        task._open_sort_menu = open_menu
        task._click_reference = click
        task._click_reference_box = pick
        return task

    def test_the_sort_is_saved_once_two_reads_agree(self):
        task = self._menu("按稀有度从高到低排序", reads=("按稀有从高到低排序",))
        self.assertEqual("按稀有度从高到低排序", task._switch_to_newest_first())
        self.assertEqual(["按稀有度从高到低排序"], task.saved)
        self.assertEqual("按获得时间从晚到早排序", task.menu["active"])

    def test_a_sort_that_never_reads_the_same_is_not_saved(self):
        flicker = ("按稀有从高到低排序", "按稀从高到低排序") * 2
        task = self._menu("按稀有度从高到低排序", reads=flicker)
        self.assertIsNotNone(task._switch_to_newest_first())
        self.assertEqual([], task.saved)

    def test_any_sort_kind_read_twice_is_saved(self):
        # Leo 2026-10-11: 「按攻击力从高到低排序」 was not saved (fixed list).
        task = self._menu("按攻击力从高到低排序", kinds=("获得时间", "攻击力"))
        self.assertEqual("按攻击力从高到低排序", task._switch_to_newest_first())
        self.assertEqual(["按攻击力从高到低排序"], task.saved)

    def test_a_stat_sort_is_restored_not_its_percent_neighbour(self):
        # Leo's menu lists 按攻击力排序 right above 按攻击力百分比排序.
        task = self._menu("按获得时间从晚到早排序", kinds=("获得时间", "攻击力百分比", "攻击力"))
        self.assertTrue(task._restore_sort("按攻击力从高到低排序"))
        self.assertEqual("按攻击力从高到低排序", task.menu["active"])

    def test_a_saved_label_missing_a_character_is_restored(self):
        task = self._menu("按获得时间从晚到早排序")
        self.assertTrue(task._restore_sort("按稀有从高到低排序"))
        self.assertEqual("按稀有度从高到低排序", task.menu["active"])


class SavedSortRecoveryTest(unittest.TestCase):
    """Review #22: a saved sort that cannot be restored no longer blocks
    every run; after the second failure (or when old) it is dropped."""

    def setUp(self):
        import tempfile
        from unittest import mock

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "junk_gear_sort.json"
        patcher = mock.patch("src.tasks.JunkGearTask._sort_state_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        stars = mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={})
        stars.start()
        self.addCleanup(stars.stop)

    def _run(self):
        from src.tasks.JunkGearTask import JunkGearTask

        task = object.__new__(JunkGearTask)
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.warnings = []
        task.log_warning = lambda message, **k: task.warnings.append((message, k.get("notify")))
        task._colours_distorted = lambda: False
        task._open_equipment_bag = lambda: True
        _filter_stubs(task)
        task._restore_sort = lambda _label: False
        task.stages = []
        # Reaching the switch means the run went on.  It does not switch,
        # and the run goes on with the bag's own sort.
        task._switch_to_newest_first = lambda: task.stages.append("切到获得时间") or None
        task.config = {}
        task._clear_pending = lambda: None
        task._dismantle_filtered = lambda *a: (True, "", True)
        task._restore_bag_detail_view = lambda: None
        task._leave_to_home = lambda *a: True
        task._claim_fail = lambda stage: task.stages.append(stage) or False
        task.run_claim()
        return task

    def _write(self, state):
        import json

        self.path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_the_second_failed_restore_drops_it_and_goes_on(self):
        import time

        self._write({"original": "按稀有从高到低排序", "saved": time.time()})
        self.assertEqual(["恢复上次的背包排序"], self._run().stages)
        self.assertTrue(self.path.exists())
        task = self._run()
        self.assertEqual(["切到获得时间"], task.stages)
        self.assertFalse(self.path.exists())
        self.assertTrue(any(notify for _message, notify in task.warnings))

    def test_an_old_save_is_dropped_at_its_first_failure(self):
        import time

        for state in (
            {"original": "按稀有从高到低排序", "saved": time.time() - 3 * 24 * 3600},
            {"original": "按稀有从高到低排序"},  # written before the date was kept
        ):
            self._write(state)
            self.assertEqual(["切到获得时间"], self._run().stages)
            self.assertFalse(self.path.exists())


class ArrowSortLabelTest(unittest.TestCase):
    """Player 2026-10-11 (v0.1.23, 1080p windowed): the menu read
    「按魔法抵抗排序 | 按暴击率排序 | 按暴击伤害排序 | 有自定义标记优先▼」 and the
    run stopped: only labels with 从…到… counted as the active one."""

    def test_the_arrow_marks_the_active_option(self):
        from types import SimpleNamespace

        from src.tasks.JunkGearTask import active_sort_label

        boxes = [
            SimpleNamespace(name=text)
            for text in ("按魔法抵抗排序", "按暴击率排序", "按暴击伤害排序", "有自定义标记优先▼")
        ]
        self.assertEqual("有自定义标记优先", active_sort_label(boxes))

    def test_a_direction_still_wins(self):
        from types import SimpleNamespace

        from src.tasks.JunkGearTask import active_sort_label

        boxes = [
            SimpleNamespace(name="有自定义标记优先▼"),
            SimpleNamespace(name="按强化从高到低排序↓"),
        ]
        self.assertEqual("按强化从高到低排序", active_sort_label(boxes))
        self.assertIsNone(active_sort_label([SimpleNamespace(name="按攻击力排序")]))


class CraftNWhenNothingDismantledTest(unittest.TestCase):
    """B站 渐崩渐晰 2026-10-11: two days without a dismantle missed the daily
    装备分解; no test covered a run that dismantled nothing.  Such a run now
    crafts one N item and dismantles it (Leo 2026-10-11)."""

    def _task(self, junk_cells, dismantle_ok=True, craft_ok=True):
        from unittest import mock

        from src.tasks.JunkGearTask import JunkGearTask

        task = object.__new__(JunkGearTask)
        task.config = {}
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.sleep = lambda *a: None
        task._colours_distorted = lambda: False
        task._open_equipment_bag = lambda: True
        task._saved_sort = lambda: None
        task._clear_saved_sort = lambda: None
        task._switch_to_newest_first = lambda: "按获得时间从新到旧排序"
        task._restore_sort = lambda _label: True
        task._restore_bag_detail_view = lambda: None
        task._still_grid_frame = lambda: object()
        task._clear_pending = lambda: None
        _filter_stubs(task)
        # Every shown item is junk here.
        task._classify_cells = lambda cells, stars, frame, grade="R", fresh=False: list(cells)
        task._enhance_and_dismantle = mock.Mock(return_value=dismantle_ok)
        task._open_craft_page = mock.Mock(return_value=True)
        task._open_n_recipe = lambda: True
        task._craft = mock.Mock(return_value=craft_ok)
        task._craft_back_to_bag = lambda: True
        task._leave_to_home = lambda *a: True
        task.stages = []
        task._claim_fail = lambda stage: task.stages.append(stage) or False
        patches = (
            mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={}),
            # R shows ``junk_cells``, SR nothing.
            mock.patch(
                "src.tasks.JunkGearTask.occupied_cells",
                side_effect=lambda *a, shown=iter([junk_cells]): next(shown, []),
            ),
            mock.patch("src.tasks.JunkGearTask.SLOW_PC_GRACE_SECONDS", 0),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return task

    def test_no_junk_crafts_and_dismantles_one_n_item(self):
        task = self._task([])
        self.assertTrue(task.run_claim())
        task._craft.assert_called_once_with(5, 1)

    def test_dismantled_junk_crafts_nothing(self):
        task = self._task([(0, 0)])
        self.assertTrue(task.run_claim())
        task._enhance_and_dismantle.assert_called_once()
        task._open_craft_page.assert_not_called()

    def test_a_failed_craft_says_so(self):
        task = self._task([], craft_ok=False)
        self.assertFalse(task.run_claim())
        self.assertEqual(["制作 N 装备分解"], task.stages)


class AfterGachaNewMarkedTest(unittest.TestCase):
    """Leo 2026-10-11: right after 抽抽乐, only the yellow 「!」 items, the
    bag's filter and sort untouched; dismantled → no filter pass; nothing
    dismantled (or not after 抽抽乐) → the filter flow as before."""

    def _task(self, marked, after_gacha=True, dismantle_ok=True):
        from unittest import mock

        from src.tasks.JunkGearTask import AFTER_GACHA_KEY, JunkGearTask

        task = object.__new__(JunkGearTask)
        task.config = {AFTER_GACHA_KEY: after_gacha}
        task.info_set = lambda *a: None
        task.log_info = lambda *a, **k: None
        task.log_warning = lambda *a, **k: None
        task.sleep = lambda *a: None
        task._colours_distorted = lambda: False
        task._open_equipment_bag = lambda: True
        task._saved_sort = lambda: None
        task._clear_saved_sort = lambda: None
        task._switch_to_newest_first = mock.Mock(return_value="按获得时间从新到旧排序")
        task._restore_sort = lambda _label: True
        task._restore_bag_detail_view = lambda: None
        task._still_grid_frame = lambda: object()
        task._clear_pending = lambda: None
        _filter_stubs(task)
        task._read_bag_filter = mock.Mock(return_value={"grade": None, "worn": True})
        task.judged = []
        task._classify_cells = lambda cells, stars, frame, grade="R", fresh=False: task.judged.append(
            (grade, list(cells))
        ) or list(cells)
        task._enhance_and_dismantle = mock.Mock(return_value=dismantle_ok)
        task._dismantle_crafted_n = lambda: True
        task._leave_to_home = lambda *a: True
        task._claim_fail = lambda stage: False
        patches = (
            mock.patch("src.tasks.JunkGearTask.load_exclusive_stars", return_value={}),
            mock.patch("src.tasks.JunkGearTask.leading_new_cells", return_value=marked),
            mock.patch("src.tasks.JunkGearTask.occupied_cells", return_value=[]),
            mock.patch("src.tasks.JunkGearTask.SLOW_PC_GRACE_SECONDS", 0),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return task

    def test_marked_items_dismantled_leave_filter_and_sort_alone(self):
        task = self._task([(2, 3), (4, 0)])
        self.assertTrue(task.run_claim())
        self.assertEqual([(None, [(2, 3), (4, 0)])], task.judged)
        task._read_bag_filter.assert_not_called()
        task._switch_to_newest_first.assert_not_called()
        self.assertEqual([], task.filter_sets)

    def test_no_marked_item_goes_on_with_the_filter(self):
        task = self._task([])
        self.assertTrue(task.run_claim())
        task._read_bag_filter.assert_called_once()
        self.assertEqual("R", task.filter_sets[0]["grade"])

    def test_marked_items_not_dismantled_go_on_with_the_filter(self):
        from unittest import mock

        task = self._task([(0, 0)])
        task._enhance_and_dismantle = mock.Mock(return_value=None)  # batch skipped
        self.assertTrue(task.run_claim())
        task._read_bag_filter.assert_called_once()

    def test_new_items_all_kept_are_written_in_the_report(self):
        # Leo 2026-10-13 「如果真的有這種情況 報表要寫」.
        from unittest import mock

        task = self._task([(0, 0), (0, 1), (0, 2)])

        def kept_all(cells, stars, frame, grade="R", fresh=False):
            task.judged.append((grade, list(cells)))
            task._kept_reasons = ["UR", "UR", "稀有度认不出"] if grade is None else []
            return []

        task._classify_cells = kept_all
        with mock.patch("src.tasks.JunkGearTask.run_report.add_current_note") as note:
            self.assertTrue(task.run_claim())
        note.assert_called_once_with("新装备 3 件都没拆；保留：UR 2 件、稀有度认不出 1 件")

    def test_new_junk_not_dismantled_says_so_in_the_report(self):
        from unittest import mock

        task = self._task([(0, 0)])
        task._enhance_and_dismantle = mock.Mock(return_value=None)
        with mock.patch("src.tasks.JunkGearTask.run_report.add_current_note") as note:
            self.assertTrue(task.run_claim())
        self.assertEqual(
            "新装备 1 件都没拆；认出 1 件烂装，一键强化没选成没拆", note.call_args_list[0].args[0]
        )

    def test_new_items_dismantled_add_no_note(self):
        from unittest import mock

        task = self._task([(0, 0)])
        with mock.patch("src.tasks.JunkGearTask.run_report.add_current_note") as note:
            self.assertTrue(task.run_claim())
        note.assert_not_called()

    def test_not_after_the_gacha_skips_the_marked_pass(self):
        task = self._task([(0, 0)], after_gacha=False)
        self.assertTrue(task.run_claim())
        self.assertNotIn((None, [(0, 0)]), task.judged)
        task._read_bag_filter.assert_called_once()

    def _counted(self, marked, cap):
        from unittest import mock

        task = self._task(marked)
        task.config["最多处理件数"] = cap
        task._enhance_and_dismantle = mock.Mock(return_value=None)  # nothing dismantled
        task._front_items = mock.Mock(return_value=(object(), []))
        task._dismantle_crafted_n = mock.Mock(return_value=True)
        return task

    def test_marked_items_only_looked_at_leave_the_count_to_the_filter(self):
        # Player 2026-10-13: ten new items with 「!」, none junk, used up
        # 最多处理件数, so 一键日常 showed 完成 in 20 s and nothing was
        # dismantled; on its own the same bag was dismantled.  Kept items
        # are not handled ones (the card: 「没有拆到时，背包先筛选出 R…」).
        task = self._counted([(0, 0), (0, 1), (0, 2)], cap=5)
        self.assertTrue(task.run_claim())
        self.assertEqual(5, task._front_items.call_args_list[0].args[0])
        for call in task._front_items.call_args_list:
            self.assertLessEqual(call.args[0], 5)
        task._dismantle_crafted_n.assert_called_once()

    def test_a_full_count_of_kept_new_items_still_runs_the_filter(self):
        task = self._counted([(0, 0), (0, 1)], cap=2)
        self.assertTrue(task.run_claim())
        task._front_items.assert_called()
        self.assertEqual(2, task._front_items.call_args_list[0].args[0])


class NewMarkedLiveTest(unittest.TestCase):
    """Leo's 4K bag 2026-10-11 (his own sort): five new items with 「!」 in
    row 1 (SR bow, locked UR, R, R, UR), read from the front up to the
    first item without one; a bag of enhanced UR has none."""

    def _grid(self, name):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        crop = cv2.imread(str(Path(__file__).parent / "fixtures" / "junk_gear" / name))
        frame[140 : 140 + crop.shape[0], 700 : 700 + crop.shape[1]] = crop
        return frame

    def test_the_five_new_items_and_no_other(self):
        from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS
        from src.utils.junk_gear import leading_new_cells

        frame = self._grid("grid_new_marked_leo_4k_at_1080.jpg")
        self.assertEqual(
            [(0, c) for c in range(5)], leading_new_cells(frame, GRID_COLUMNS, GRID_ROWS, 40)
        )

    def test_one_item_drawn_from_the_gacha_is_read_alone(self):
        # Leo's 4K bag right after one 抽抽乐 draw (15:24Z): one R at the front.
        from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS
        from src.utils.junk_gear import leading_new_cells

        frame = self._grid("grid_one_new_r_after_gacha_leo_4k_at_1080.jpg")
        self.assertEqual([(0, 0)], leading_new_cells(frame, GRID_COLUMNS, GRID_ROWS, 40))

    def test_colourful_ur_labels_are_not_marks(self):
        from src.tasks.GearTasks import GRID_COLUMNS, GRID_ROWS
        from src.utils.junk_gear import leading_new_cells

        frame = self._grid("grid_ur_no_marks_leo_4k_at_1080.jpg")
        self.assertEqual([], leading_new_cells(frame, GRID_COLUMNS, GRID_ROWS, 40))
