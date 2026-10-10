import unittest

import numpy as np

from src.tasks.claim_page import SETTLED_BRIGHTNESS_RATIO, ClaimButton, ClaimPageMixin


def frame(title_level: int, body_level: int, height: int = 2160, width: int = 3840):
    image = np.full((height, width, 3), body_level, dtype=np.uint8)
    image[: round(110 / 1080 * height), : round(760 / 1920 * width)] = title_level
    return image


class SettleBrightnessTest(unittest.TestCase):
    def test_emptied_page_content_does_not_count_as_an_overlay(self):
        # Claiming all mail darkens the list area but not the title bar.
        before = ClaimPageMixin._frame_brightness(frame(title_level=36, body_level=60))
        after = ClaimPageMixin._frame_brightness(frame(title_level=36, body_level=20))
        self.assertGreaterEqual(after, before * SETTLED_BRIGHTNESS_RATIO)

    def test_overlay_dimming_the_title_bar_is_detected(self):
        before = ClaimPageMixin._frame_brightness(frame(title_level=74, body_level=56))
        dimmed = ClaimPageMixin._frame_brightness(frame(title_level=15, body_level=25))
        self.assertLess(dimmed, before * SETTLED_BRIGHTNESS_RATIO)

    def test_works_at_1080p_too(self):
        self.assertAlmostEqual(
            ClaimPageMixin._frame_brightness(frame(40, 90, 1080, 1920)),
            ClaimPageMixin._frame_brightness(frame(40, 10, 2160, 3840)),
            delta=1.0,
        )


class TitleWaitTest(unittest.TestCase):
    """Live 2026-09-27: 17 s of an unchanged 消耗品 page looked like a freeze."""

    def _task(self, titles):
        from types import SimpleNamespace
        from unittest.mock import patch

        clock = [0.0]
        reads = iter(titles)
        task = object.__new__(ClaimPageMixin)
        task.config = {}
        task.claim_log_name = "test"
        task.capture_frame = lambda: None
        task._page_title_text = lambda _f, _l: next(reads)
        task._match = lambda *_a: SimpleNamespace(score=-1.0)
        task.info_set = lambda *_a: None
        task.log_info = lambda *_a, **_k: None
        task._save_flow_diagnostic = lambda *_a: None
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        patcher = patch("src.tasks.claim_page.monotonic", lambda: clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        return task, clock

    def test_unchanged_other_title_stops_the_wait_early(self):
        task, clock = self._task(["消耗品149/320"] * 40)
        self.assertFalse(task._wait_for_title("装备", ("装备",)))
        self.assertLessEqual(clock[0], 4.0)

    def test_loading_without_a_title_waits_for_the_page(self):
        task, _clock = self._task([""] * 12 + ["装备450/800"])
        self.assertTrue(task._wait_for_title("装备", ("装备",)))

    def test_title_changing_during_a_transition_is_not_cut_short(self):
        task, _clock = self._task(["消耗品"] * 5 + [""] * 4 + ["装备"])
        self.assertTrue(task._wait_for_title("装备", ("装备",)))


class ClaimAllConfirmTest(unittest.TestCase):
    """A swallowed 全部领取 press left the page unchanged, which read as
    「无新奖励或已直接领取」 with the rewards still there (press audit 10-09)."""

    BUTTON = ClaimButton((1200, 930, 720, 150), ("全部领取",))

    def _task(self, lands=(1,), popup_hides_button=False):
        from types import SimpleNamespace

        from src.tasks.RewardClaimTasks import MailRewardTask
        from src.utils.press_confirm import press_and_confirm

        game = {"lit": True, "presses": 0, "settled": 0}
        clock = [0.0]
        box = SimpleNamespace(name="全部领取", x=1500, y=980, width=200, height=50)

        def capture():
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            image[980:1030, 1500:1700] = 252 if game["lit"] else 127
            return image

        def press(_target, **_kwargs):
            game["presses"] += 1
            if game["presses"] in lands:
                game["lit"] = False

        task = object.__new__(MailRewardTask)
        task.claim_log_name = "test"
        task.info = {}
        task.info_set = lambda key, value: task.info.__setitem__(key, value)
        task.log_info = lambda *_a, **_k: None
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        task.capture_frame = capture
        task._roi_boxes = lambda *_a: [] if popup_hides_button and not game["lit"] else [box]
        task._click_box = press
        task._sleep_after_recognition = lambda: None
        task._save_flow_diagnostic = lambda *_a: None
        task._settle_after_claim = lambda *_a: game.__setitem__("settled", 1) or True
        task.press_and_confirm = lambda label, do, confirmed, **options: press_and_confirm(
            label, do, confirmed, sleep=task.sleep, log=task.log_info, clock=lambda: clock[0],
            **options,
        )
        return task, game

    def test_swallowed_press_is_pressed_again_then_reported_as_failure(self):
        task, game = self._task(lands=())
        self.assertFalse(task._claim_all("普通邮箱", self.BUTTON, ("邮箱",)))
        self.assertEqual(2, game["presses"])
        self.assertEqual(0, game["settled"])
        self.assertIn("未领到", task.info["普通邮箱结果"])

    def test_button_turning_grey_is_claimed_with_one_press(self):
        task, game = self._task(lands=(1,))
        self.assertTrue(task._claim_all("普通邮箱", self.BUTTON, ("邮箱",)))
        self.assertEqual((1, 1), (game["presses"], game["settled"]))

    def test_first_press_lost_second_lands(self):
        task, game = self._task(lands=(2,))
        self.assertTrue(task._claim_all("每日任务", self.BUTTON, ("每日任务",)))
        self.assertEqual((2, 1), (game["presses"], game["settled"]))

    def test_reward_popup_covering_the_button_counts(self):
        task, game = self._task(lands=(1,), popup_hides_button=True)
        self.assertTrue(task._claim_all("普通邮箱", self.BUTTON, ("邮箱",)))
        self.assertEqual(1, game["presses"])


if __name__ == "__main__":
    unittest.main()


class OverrideSignatureTest(unittest.TestCase):
    """Live 2026-09-28: a shared helper added to ClaimPageMixin had the name
    of CraftGearTask's own method, and craft gear crashed on the bag page."""

    def test_task_overrides_keep_the_mixin_signatures(self):
        import importlib
        import inspect
        import pkgutil

        import src.tasks as tasks_pkg

        for module_info in pkgutil.iter_modules(tasks_pkg.__path__):
            importlib.import_module(f"src.tasks.{module_info.name}")

        def subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from subclasses(sub)

        shared = {
            name: member
            for name, member in vars(ClaimPageMixin).items()
            if inspect.isfunction(member)
        }
        for cls in set(subclasses(ClaimPageMixin)):
            for name, base in shared.items():
                override = vars(cls).get(name)
                if override is None or not inspect.isfunction(override):
                    continue
                with self.subTest(cls=cls.__name__, method=name):
                    self.assertEqual(
                        list(inspect.signature(base).parameters),
                        list(inspect.signature(override).parameters),
                    )
