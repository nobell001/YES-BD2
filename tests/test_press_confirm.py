import unittest

from src.utils.press_confirm import RETRY_AFTER_SECONDS, press_and_confirm, wait_for


class FakeGame:
    """A button whose press lands only on the presses listed in ``lands``."""

    def __init__(self, lands=(1,), shows_after=0.0, moves_on_after=None):
        self.now = 0.0
        self.presses = 0
        self.lands = set(lands)
        self.shows_after = shows_after
        self.moves_on_after = moves_on_after
        self.landed_at = None
        self.logs = []
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def press(self):
        self.presses += 1
        if self.presses in self.lands and self.landed_at is None:
            self.landed_at = self.now

    def confirmed(self):
        return self.landed_at is not None and self.now - self.landed_at >= self.shows_after

    def still_before(self):
        if self.moves_on_after is not None and self.now >= self.moves_on_after:
            return False
        return self.landed_at is None

    def run(self, **options):
        options.setdefault("still_before", self.still_before)
        return press_and_confirm(
            "测试按钮",
            self.press,
            self.confirmed,
            sleep=self.sleep,
            log=self.logs.append,
            clock=self.clock,
            **options,
        )


class PressAndConfirmTest(unittest.TestCase):
    def test_a_press_that_lands_is_pressed_once(self):
        game = FakeGame(lands=(1,))

        outcome = game.run()

        self.assertTrue(outcome)
        self.assertEqual((1, "confirmed"), (outcome.presses, outcome.reason))
        self.assertEqual([], game.logs)

    def test_a_lost_press_is_pressed_once_more_after_1_5_seconds(self):
        game = FakeGame(lands=(2,))

        outcome = game.run()

        self.assertTrue(outcome)
        self.assertEqual((2, "confirmed-after-retry"), (outcome.presses, outcome.reason))
        self.assertIn(RETRY_AFTER_SECONDS, game.sleeps)
        self.assertEqual(1.5, RETRY_AFTER_SECONDS)

    def test_a_slow_screen_that_catches_up_is_not_pressed_again(self):
        # landed on the first press, but the game takes 4 s to show it
        game = FakeGame(lands=(1, 2), shows_after=4.0)

        outcome = game.run(timeout=3.0)

        self.assertTrue(outcome)
        self.assertEqual((1, "late"), (outcome.presses, outcome.reason))

    def test_no_second_press_once_the_screen_moved_elsewhere(self):
        game = FakeGame(lands=(), moves_on_after=1.0)

        outcome = game.run()

        self.assertFalse(outcome)
        self.assertEqual((1, "moved-on"), (outcome.presses, outcome.reason))

    def test_without_a_before_check_it_never_presses_twice(self):
        game = FakeGame(lands=(2,))

        outcome = game.run(still_before=None)

        self.assertFalse(outcome)
        self.assertEqual(1, game.presses)

    def test_spending_presses_use_no_retry(self):
        game = FakeGame(lands=())

        outcome = game.run(retries=0)

        self.assertFalse(outcome)
        self.assertEqual((1, "not-confirmed"), (outcome.presses, outcome.reason))
        self.assertTrue(any("未确认" in line for line in game.logs))

    def test_two_lost_presses_are_reported_not_confirmed(self):
        game = FakeGame(lands=())

        outcome = game.run()

        self.assertFalse(outcome)
        self.assertEqual((2, "not-confirmed"), (outcome.presses, outcome.reason))


class WaitForTest(unittest.TestCase):
    def test_zero_timeout_still_looks_once(self):
        looks = []

        result = wait_for(lambda: looks.append(1) or "seen", 0.0, sleep=lambda _s: None)

        self.assertEqual("seen", result)
        self.assertEqual(1, len(looks))

    def test_overrun_clock_still_looks_once(self):
        # the clock already jumped past the deadline before the first look
        times = iter([0.0, 10.0, 10.0])
        looks = []

        result = wait_for(
            lambda: looks.append(1) or None,
            1.0,
            sleep=lambda _s: None,
            clock=lambda: next(times),
        )

        self.assertIsNone(result)
        self.assertEqual(1, len(looks))

    def test_keeps_looking_until_the_timeout(self):
        game = FakeGame()
        seen_at = 2.0

        result = wait_for(
            lambda: game.now >= seen_at,
            3.0,
            sleep=game.sleep,
            clock=game.clock,
        )

        self.assertTrue(result)
        self.assertGreaterEqual(game.now, seen_at)


if __name__ == "__main__":
    unittest.main()
