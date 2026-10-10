"""Put the player's skill group back after the tool switched it.

Leo's rule: the tool puts back what it switched, and never picks a group for
the player.  跑图 switches groups only when the bottom four slots show none
of 探查/吸收/召集/压制 (collector_skills._open_skill_menu); the group the
player had before that first switch is put back while the skill bar is
still on screen.  An unreadable start group is not guessed, and a stop
presses nothing more: both only say so in the log.
"""

from __future__ import annotations

import sys

from src.tasks.map_trade.action_icons import selected_skill_group
from src.tasks.map_trade.collector_constants import (
    SKILL_GROUP_RELATIVE_POINTS,
    SKILL_GROUP_SWITCH_SETTLE_SECONDS,
)


def stopping() -> bool:
    """A stop (or the player taking over) is unwinding the run right now."""
    from ok.task.exceptions import FinishedException, TaskDisabledException

    error = sys.exc_info()[1]
    return isinstance(error, (TaskDisabledException, FinishedException))


class SkillGroupKeeper:
    def __init__(self, task, vision, label: str) -> None:
        self.task = task
        self.vision = vision
        self.label = label
        self.switched = False
        self.before: int | None = None

    def read(self) -> int | None:
        capture = getattr(self.vision, "capture", None)
        if not callable(capture):
            return None
        return selected_skill_group(capture())

    def before_switch(self) -> None:
        """Call just before the tool clicks a group button."""
        if not self.switched:
            self.before = self.read()
            self.switched = True

    def restore(self, *, stopped: bool = False, final: bool = False) -> None:
        """Back to the player's group.  Off the field (no skill bar) it waits
        for a later call; ``final`` gives up there with a log line."""

        if not self.switched:
            return
        before = self.before
        if stopped:
            self._forget()
            if before is not None:
                self.task.log_warning(
                    f"{self.label}：停止时技能组可能还在工具切过去的那一组，原本是第{before}组，请切回去。"
                )
            return
        if before is None:
            self._forget()
            self.task.log_warning(
                f"{self.label}：切换技能组前没认出原本是第几组，没有切回，请检查技能栏。"
            )
            return
        now = self.read()
        if now is None:
            if final:
                self._forget()
                self.task.log_warning(
                    f"{self.label}：结束时不在地图上，技能组没有切回，原本是第{before}组，请检查技能栏。"
                )
            return
        self._forget()
        if now == before:
            return
        self.task.operate_click(  # 不用确认：下面读技能组确认
            *SKILL_GROUP_RELATIVE_POINTS[before], after_sleep=0.0
        )
        self.task.sleep(SKILL_GROUP_SWITCH_SETTLE_SECONDS)
        after = self.read()
        if after == before:
            self.task.log_info(f"{self.label}：技能组从第{now}组切回原本的第{before}组。")
        else:
            self.task.log_warning(
                f"{self.label}：想把技能组切回原本的第{before}组，但现在认到的是"
                f"{f'第{after}组' if after else '认不出'}，请检查技能栏。"
            )

    def _forget(self) -> None:
        self.switched = False
        self.before = None
