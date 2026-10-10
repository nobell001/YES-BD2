import unittest

from src.compat.main_window_geometry import (
    MAIN_WINDOW_GEOMETRY_DEBOUNCE_MS,
    fit_first_open_size,
    forget_off_screen_position,
    patch_main_window_first_open_size,
    patch_main_window_geometry_events,
    visible_on_a_screen,
)


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _Timer:
    instances = []

    def __init__(self, parent):
        self.parent = parent
        self.single_shot = False
        self.interval = 0
        self.starts = 0
        self.stops = 0
        self.active = False
        self.timeout = _Signal()
        self.instances.append(self)

    def setSingleShot(self, value):
        self.single_shot = value

    def setInterval(self, value):
        self.interval = value

    def start(self):
        self.starts += 1
        self.active = True

    def stop(self):
        self.stops += 1
        self.active = False

    def isActive(self):
        return self.active


class MainWindowGeometryCompatibilityTest(unittest.TestCase):
    def setUp(self):
        _Timer.instances.clear()

    def test_top_level_events_share_one_timer_and_close_flushes_it(self):
        class FakeMainWindow:
            def __init__(self):
                self.moves = 0
                self.resizes = 0
                self.updates = 0
                self.filtered = 0
                self.closes = 0

            def moveEvent(self, _event):
                self.moves += 1

            def resizeEvent(self, _event):
                self.resizes += 1

            def closeEvent(self, _event):
                self.closes += 1

            def eventFilter(self, _obj, _event):
                self.filtered += 1
                return "original"

            def update_ok_config(self):
                self.updates += 1

        original_event_filter = FakeMainWindow.eventFilter
        patch_main_window_geometry_events(FakeMainWindow, _Timer)
        window = FakeMainWindow()

        for _index in range(20):
            window.moveEvent(object())
            window.resizeEvent(object())

        self.assertEqual(1, len(_Timer.instances))
        timer = _Timer.instances[0]
        self.assertTrue(timer.single_shot)
        self.assertEqual(MAIN_WINDOW_GEOMETRY_DEBOUNCE_MS, timer.interval)
        self.assertEqual(40, timer.starts)
        self.assertEqual(0, window.updates)
        self.assertIs(original_event_filter, FakeMainWindow.eventFilter)
        self.assertEqual("original", window.eventFilter(window, object()))
        self.assertEqual(1, window.filtered)

        window.closeEvent(object())

        self.assertEqual(1, timer.stops)
        self.assertFalse(timer.isActive())
        self.assertEqual(1, window.updates)
        self.assertEqual(1, window.closes)


class _Rect:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class _Screen:
    def __init__(self, width, height):
        self.rect = _Rect(width, height)

    def availableGeometry(self):
        return self.rect


class FirstOpenSizeTest(unittest.TestCase):
    def test_default_size_is_leos_4k_window(self):
        from src.config import config

        size = config["window_size"]
        self.assertEqual((1335, 1020), (size["width"], size["height"]))

    def test_default_width_fits_eight_task_cards_per_row(self):
        from src.config import config

        # sidebar 224, page margins 28 + 28, cards 118 wide with 10 between
        content = config["window_size"]["width"] - 224 - 56
        self.assertGreaterEqual((content + 10) // (118 + 10), 8)

    def test_big_screens_keep_the_default_size(self):
        # 2K at 125%, 2K at 100% and 4K at 175% all have room for it.
        self.assertEqual((1335, 997), fit_first_open_size(1335, 997, 600, 450, 2048, 1112))
        self.assertEqual((1335, 997), fit_first_open_size(1335, 997, 600, 450, 2560, 1380))
        self.assertEqual((1335, 997), fit_first_open_size(1335, 997, 600, 450, 2194, 1206))

    def test_big_screens_keep_the_size_with_the_week_row(self):
        # 10-09: 1020 tall for the 本周任务 row; 2K at 125% (1023 usable) still fits.
        for screen in ((2048, 1112), (2560, 1380), (2194, 1206)):
            self.assertEqual((1335, 1020), fit_first_open_size(1335, 1020, 600, 450, *screen))

    def test_1080p_keeps_eight_cards_per_row(self):
        # 1080p at 100% leaves about 1920x1032: full width, a bit shorter.
        self.assertEqual((1335, 949), fit_first_open_size(1335, 997, 600, 450, 1920, 1032))

    def test_small_screens_shrink_but_not_below_the_minimum(self):
        # 1080p at 125% leaves about 1536x824 logical pixels.
        self.assertEqual((1335, 758), fit_first_open_size(1335, 997, 600, 450, 1536, 824))
        self.assertEqual((900, 700), fit_first_open_size(1335, 997, 900, 700, 800, 600))

    def test_patch_passes_the_fitted_size_on(self):
        class FakeMainWindow:
            def __init__(self, screen):
                self._screen = screen
                self.calls = []

            def screen(self):
                return self._screen

            def set_window_size(self, width, height, min_width, min_height):
                self.calls.append((width, height, min_width, min_height))

        patch_main_window_first_open_size(FakeMainWindow, screens=lambda: [])
        patch_main_window_first_open_size(FakeMainWindow, screens=lambda: [])

        small = FakeMainWindow(_Screen(1536, 824))
        small.set_window_size(1335, 997, 600, 450)
        no_screen = FakeMainWindow(None)
        no_screen.set_window_size(1335, 997, 600, 450)

        self.assertEqual([(1335, 758, 600, 450)], small.calls)
        self.assertEqual([(1335, 997, 600, 450)], no_screen.calls)


class OffScreenWindowTest(unittest.TestCase):
    """Audit #54: saved on a second monitor that was later unplugged."""

    MAIN = (0, 0, 2560, 1400)
    RIGHT = (2560, 0, 1920, 1040)

    def test_a_window_on_a_screen_is_visible(self):
        self.assertTrue(visible_on_a_screen((300, 200, 1335, 997), [self.MAIN]))
        self.assertTrue(visible_on_a_screen((3000, 100, 1335, 997), [self.MAIN, self.RIGHT]))
        # Mostly off the edge, but the title bar still shows.
        self.assertTrue(visible_on_a_screen((2400, 100, 1335, 997), [self.MAIN]))

    def test_a_window_on_an_unplugged_monitor_is_not(self):
        self.assertFalse(visible_on_a_screen((3000, 100, 1335, 997), [self.MAIN]))
        self.assertFalse(visible_on_a_screen((2500, 100, 1335, 997), [self.MAIN]))

    def test_the_saved_position_is_forgotten_only_when_off_screen(self):
        config = {
            "window_x": 3000,
            "window_y": 100,
            "window_width": 1335,
            "window_height": 997,
            "window_maximized": True,
        }
        self.assertTrue(forget_off_screen_position(config, [self.MAIN]))
        self.assertEqual(
            (0, 0, False), (config["window_x"], config["window_y"], config["window_maximized"])
        )
        self.assertEqual(1335, config["window_width"])

        kept = {"window_x": 300, "window_y": 200, "window_width": 1335, "window_height": 997}
        self.assertFalse(forget_off_screen_position(kept, [self.MAIN]))
        self.assertEqual(300, kept["window_x"])

    def test_no_screens_or_no_saved_size_changes_nothing(self):
        config = {"window_x": 3000, "window_y": 100, "window_width": 1335, "window_height": 997}
        self.assertFalse(forget_off_screen_position(config, []))
        self.assertFalse(forget_off_screen_position({"window_x": 3000}, [self.MAIN]))
        self.assertFalse(forget_off_screen_position(None, [self.MAIN]))

    def test_the_patch_clears_it_before_ok_restores_it(self):
        class FakeMainWindow:
            def __init__(self):
                self.ok_config = {
                    "window_x": 3000,
                    "window_y": 100,
                    "window_width": 1335,
                    "window_height": 997,
                }
                self.seen = None

            def screen(self):
                return None

            def set_window_size(self, *_args):
                self.seen = self.ok_config["window_x"]

        patch_main_window_first_open_size(FakeMainWindow, screens=lambda: [self.MAIN])
        window = FakeMainWindow()
        window.set_window_size(1335, 997, 600, 450)
        self.assertEqual(0, window.seen)


if __name__ == "__main__":
    unittest.main()
