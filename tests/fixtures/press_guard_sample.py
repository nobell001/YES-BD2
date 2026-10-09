from time import monotonic


def run(task):
    task.press_and_confirm("ok", lambda: task.click(1, 2), lambda: True)
    task.click(3, 4)  # 不用确认：the next step looks for the popup
    task.click(5, 6)
    end_at = monotonic() + 1
    while monotonic() <= end_at:
        pass
