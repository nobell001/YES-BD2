"""press_next: after a press, the listed screens, then the remedies in order."""

import unittest

from src.utils.press_next import NOTHING_LISTED, Next, per_frame, press_next
from src.utils.wait_limits import LOADING_MAX_SECONDS


class Game:
    """Screens shown one per look; the last one stays."""

    def __init__(self, *screens):
        self.screens = list(screens)
        self.now = 0.0
        self.events = []

    def capture(self):
        screen = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        return {"screen": screen}  # a new frame object each look

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now

    def act(self, name, *then_show):
        def run(*_frame):
            self.events.append(name)
            if then_show:
                self.screens = list(then_show)

        return run

    def page(self, name):
        return lambda frame: frame["screen"] == name

    def run(self, nexts, **kwargs):
        return press_next(
            "进商店",
            self.act("press"),
            nexts,
            capture=self.capture,
            sleep=self.sleep,
            log=lambda message: self.events.append(("log", message)),
            clock=self.clock,
            **kwargs,
        )


def shop_steps(game, **extra):
    return (
        Next("商店页", game.page("shop"), goal=True),
        Next("出售弹窗", game.page("sale dialog"), then=game.act("close dialog", "shop")),
        Next("加载中", game.page("loading"), loading=True),
        Next("商人菜单", game.page("menu"), before=True),
        *extra.get("more", ()),
    )


class PressNextTest(unittest.TestCase):
    def test_the_goal_on_the_first_look_ends_the_step(self):
        game = Game("shop")
        outcome = game.run(shop_steps(game))

        self.assertTrue(outcome)
        self.assertEqual(("商店页", ""), (outcome.screen, outcome.remedy))
        self.assertEqual(["press"], game.events)

    def test_a_listed_popup_is_handled_and_the_list_looked_at_again(self):
        game = Game("sale dialog")
        outcome = game.run(shop_steps(game))

        self.assertTrue(outcome)
        self.assertEqual(["press", "close dialog"], [e for e in game.events if isinstance(e, str)])

    def test_a_popup_that_does_not_close_is_handled_only_twice(self):
        game = Game("sale dialog")
        steps = (
            Next("商店页", game.page("shop"), goal=True),
            Next("出售弹窗", game.page("sale dialog"), then=game.act("close dialog")),
        )
        outcome = game.run(steps)

        self.assertFalse(outcome)
        self.assertEqual("出售弹窗", outcome.screen)
        self.assertEqual(2, game.events.count("close dialog"))

    def test_loading_is_looked_through_and_not_counted_as_stuck(self):
        game = Game(*(["loading"] * 60), "shop")
        outcome = game.run(shop_steps(game), poll=0.5)

        self.assertTrue(outcome)
        self.assertEqual("", outcome.remedy)
        self.assertGreater(game.now, 20.0)

    def test_loading_stops_at_the_loading_limit(self):
        game = Game("loading")
        outcome = game.run(shop_steps(game), poll=0.5)

        self.assertFalse(outcome)
        self.assertEqual("加载中", outcome.screen)
        self.assertLessEqual(game.now, LOADING_MAX_SECONDS + 1.0)

    def test_still_on_the_screen_pressed_from_presses_once_more(self):
        game = Game("menu")
        presses = []

        def press():
            presses.append("press")
            if len(presses) == 2:  # the first press was dropped
                game.screens = ["shop"]

        outcome = press_next(
            "进商店",
            press,
            shop_steps(game),
            capture=game.capture,
            sleep=game.sleep,
            log=lambda _m: None,
            clock=game.clock,
        )

        self.assertTrue(outcome)
        self.assertEqual("补按", outcome.remedy)
        self.assertEqual(2, len(presses))

    def test_the_remedies_go_in_order_press_again_key_usual_place(self):
        game = Game("menu")
        outcome = game.run(
            shop_steps(game),
            key=("F2", game.act("F2")),
            fixed=game.act("usual place", "shop"),
        )

        self.assertTrue(outcome)
        self.assertEqual("固定位置", outcome.remedy)
        self.assertEqual(
            ["press", "press", "F2", "usual place"],
            [e for e in game.events if isinstance(e, str)],
        )

    def test_a_spend_press_only_looks_and_is_never_pressed_again(self):
        game = Game("menu")
        outcome = game.run(
            shop_steps(game),
            key=("F2", game.act("F2")),
            fixed=game.act("usual place"),
            harmless=False,
        )

        self.assertFalse(outcome)
        self.assertEqual(["press"], [e for e in game.events if isinstance(e, str)])

    def test_no_remedy_once_the_screen_moved_on_to_something_unlisted(self):
        game = Game("somewhere else")
        outcome = game.run(
            shop_steps(game),
            key=("F2", game.act("F2")),
            fixed=game.act("usual place"),
        )

        self.assertFalse(outcome)
        self.assertEqual(NOTHING_LISTED, outcome.screen)
        self.assertEqual(["press"], [e for e in game.events if isinstance(e, str)])

    def test_the_failure_says_what_was_seen_in_player_words(self):
        game = Game("menu")
        game.run(shop_steps(game))

        logs = [e[1] for e in game.events if isinstance(e, tuple)]
        self.assertEqual("进商店：没看到商店页，最后看到的是商人菜单。", logs[-1])

    def test_a_step_without_a_goal_is_refused(self):
        game = Game("menu")
        with self.assertRaises(ValueError):
            game.run((Next("商人菜单", game.page("menu"), before=True),))


class PerFrameTest(unittest.TestCase):
    def test_one_read_per_frame(self):
        reads = []
        state = per_frame(lambda frame: reads.append(frame) or "shop")
        first, second = {"n": 1}, {"n": 2}

        self.assertEqual("shop", state(first))
        self.assertEqual("shop", state(first))
        self.assertEqual("shop", state(second))
        self.assertEqual([first, second], reads)


if __name__ == "__main__":
    unittest.main()
