from time import monotonic


def run(task):
    task.press_and_confirm("ok", lambda: task.click(1, 2), lambda: True)
    task.click(3, 4)  # 不用确认：the next step looks for the popup
    task.click(5, 6)
    end_at = monotonic() + 1
    while monotonic() <= end_at:
        pass
    press_next("ok", lambda: task.click(7, 8), ())
    end_at = monotonic() + 2  # 自己等：sample


def _click_close(task):
    task.click(9, 10)  # 不用确认：sample helper, its callers are checked


def leave(task):
    _click_close(task)
    task._click_close()  # 不用确认：sample
    press_next("ok", lambda: _click_close(task), ())


def _press_twice(task):  # 会补点：sample, presses again by itself
    task.click(11, 12)  # 不用确认：sample


def _click_via_helper(task):
    _click_close(task)  # 不用确认：sample


def go(task):
    _press_twice(task)
    _click_via_helper(task)
