from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import replace

from ok.task.exceptions import FinishedException, TaskDisabledException

from src.tasks.map_trade import account_check
from src.tasks.map_trade.action_icons import ActionIconDetector
from src.tasks.map_trade.card_status import (
    CollectionCardSelectionOutcome,
    CollectionCardSelectionResult,
)
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    BATTLE_ACTIONS,
    SKILL_FAILURE_EVIDENCE_LIMIT,
    SKILL_FAILURE_TEXT_LIMIT,
    UNSUPPORTED_COLLECTION_CARD_NUMBERS,
    SUPPRESS_ACTION,
    SearchCountdownSession,
    SkillExecutionResult,
)
from src.tasks.map_trade.collector_skills import SkillExecutionMixin
from src.tasks.map_trade.models import (
    COLLECTABLE_CARDS,
    LAST_MAP_THEN_TOWN_CARD_IDS,
    CollectionActionState,
    CollectionMapRole,
    CollectionResult,
)
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.progress import ProgressStore
from src.tasks.map_trade.skill_group_keeper import SkillGroupKeeper, stopping
from src.tasks.map_trade.skill_layout import SkillLayoutWrong
from src.tasks.map_trade.vision import Vision
from src.utils.plain_text import DIAGNOSTIC_PREFIX
from src.utils.press_confirm import SLOW_PC_GRACE_SECONDS, wait_for

# "卡带单步重试次数"未配置时的默认值。
CARD_RETRY_DEFAULT = 2
# A map whose press was cut by a field battle is done again after running
# away, this many times at most, 压制 first to clear the monsters.
BATTLE_REDOS_MAX = 2
AFTER_ESCAPE_ACTIONS = (SUPPRESS_ACTION,) + tuple(
    action for action in BATTLE_ACTIONS if action is not SUPPRESS_ACTION
)


def chapter_filter(text) -> set[int | str] | None:
    """"8-13" / "6" / "1,3,5" -> chapter numbers, "R1" / "R1-R7" -> character
    cards, "E2" / "E1-E7" -> event cards ("R1" / "E2" etc., see
    CardSpec.filter_key); empty or 全部 -> None (all)."""
    raw = str(text or "").replace("，", ",").replace("、", ",")
    raw = raw.replace("～", "-").replace("~", "-").strip()
    if not raw or raw in {"全部", "all"}:
        return None
    wanted: set[int | str] = set()
    for part in raw.split(","):
        part = part.strip().upper()
        prefix = part[0] if part[:1] in ("R", "E") else ""
        body = part.replace(prefix, "") if prefix else part
        if "-" in body:
            low, high = (value.strip() for value in body.split("-", 1))
            if low.isdigit() and high.isdigit():
                numbers = range(int(low), int(high) + 1)
                wanted.update(f"{prefix}{n}" if prefix else n for n in numbers)
        elif body.isdigit():
            wanted.add(f"{prefix}{body}" if prefix else int(body))
    return wanted or None


class Collector(SkillExecutionMixin):
    def __init__(
        self,
        task,
        vision: Vision,
        navigator: Navigator,
        progress: ProgressStore,
    ) -> None:
        self.task = task
        self.vision = vision
        self.navigator = navigator
        self.progress = progress
        self.action_icons = ActionIconDetector(vision)
        # Keep only a small in-memory replay tail.  It is emitted when a
        # recognition failure reaches the caller; normal successful runs do
        # not write images or grow an on-disk directory indefinitely.
        self._skill_failure_evidence: deque[dict[str, object]] = deque(
            maxlen=SKILL_FAILURE_EVIDENCE_LIMIT
        )
        self._last_skill_observations: dict[str, dict[str, object]] = {}
        self._last_skill_geometry: dict[str, object] = {}
        self._group_one_recovery_attempted = False
        # The last card entered this run: the group kept for the next card is
        # put back there when the run ends off the field.
        self._last_field_card_id = None
        self._last_count_window_stable = False
        # The player's skill group, put back after the group search switched it.
        self.skill_group_keeper = SkillGroupKeeper(task, vision, "地图采集")

    def run(self) -> CollectionResult:
        # A Collector instance can be reused by the task scheduler.  Recovery
        # is bounded once per formal run, while direct helper calls retain the
        # latch until the next run invocation.
        self._group_one_recovery_attempted = False
        self._skipped_cards: list = []
        # card_id -> where and why a skill could not be confirmed (Leo
        # 2026-10-12: skip the card, but the report must say where).
        self._skill_skips: dict[str, str] = {}
        self._unconfirmed_cards: set[str] = set()
        # card_id -> why a card was skipped (player report 2026-10-17: the
        # summary said only 「这次跳过」 and the stage left over from before).
        self._skip_reasons: dict[str, str] = {}
        # The skill bar is read once a run (a player may have moved skills).
        self._skill_layout_checked = False
        try:
            return self._with_skipped_cards(self._run_collection())
        except SkillLayoutWrong as exc:
            self.task.log_warning(f"地图采集：{exc}")
            return CollectionResult(False, message=str(exc))
        except RuntimeError as exc:
            self.task.log_error("地图采集流程异常", exc)
            return CollectionResult(
                False,
                message=f"地图采集流程异常：{exc}",
            )
        finally:
            stopped = stopping()
            if not stopped:
                self._restore_on_last_field()
            self._restore_skill_group(stopped=stopped, final=True)

    def _run_collection(self) -> CollectionResult:
        state = self.progress.load()
        # Only the game's count says the day is used up (a player 2026-10-20:
        # 18/21 absorbs, the tool said used up and 开始跑图 did nothing).
        self.progress.forget_unproven_depletion()
        if self.progress.game_used_up("吸收"):
            return CollectionResult(True, depleted=True, message="今日采集技能额度已用尽")
        # GitHub issue #4: records that call cards finished while the game
        # shows them untouched belong to another account; stop, press nothing.
        if account_check.records_from_other_account(
            self.navigator, state, chapter_filter(self.task.config.get("跑图章节", ""))
        ):
            account_check.raise_flag(state.weekly_key)
            self.task.log_warning(f"地图采集：{account_check.MESSAGE}")
            return CollectionResult(False, message=account_check.MESSAGE)
        if state.weekly_collection_complete:
            return CollectionResult(
                True,
                message="本周已支持剧情卡带均已采集并完成视觉复核",
            )

        completed_this_run = 0
        cards_this_run = 0
        self._unfinished_cards: list[str] = []
        # 0 = no limit beyond the daily skill counts (at most 7 cards a day).
        card_limit = max(0, int(self.task.config.get("本次最多卡带数", 0)))
        card_retries = max(
            1, int(self.task.config.get("卡带单步重试次数", CARD_RETRY_DEFAULT))
        )
        allowed = chapter_filter(self.task.config.get("跑图章节", ""))
        self._badges_unfinished: set[str] = set()
        for card in self._cards_with_one_retry():
            if allowed is not None and card.filter_key not in allowed:
                continue
            if card.number in UNSUPPORTED_COLLECTION_CARD_NUMBERS:
                self._status("跳过", f"{card.card_id}：{card.label}等待专用流程")
                self.task.log_warning(
                    f"地图采集：{card.label}需要专用流程，本轮跳过且不写任何采集进度。"
                )
                continue

            state = self.progress.state
            completed = state.completed_targets(card.card_id)
            if len(completed) >= len(card.targets):
                # Three maps done this week = the card is done; its badges are
                # not read (Leo 2026-10-21 「假設我第五章 安全區 戰鬥1 戰鬥2 都
                # 進行過了 那麼這張就不再跑」, 「第六章確認跑過一遍就算完成」:
                # a player's 跑图 kept walking cards it had finished).
                if not state.card_verified(card.card_id):
                    self.progress.mark_card_verified(card.card_id)
                continue

            if card_limit and cards_this_run >= card_limit:
                return CollectionResult(
                    True,
                    completed_submaps=completed_this_run,
                    message=f"已完成本次设定的{card_limit}张卡带",
                )

            if not self._can_finish_card_today(card, completed):
                self.progress.mark_depleted_today()
                return CollectionResult(
                    True,
                    depleted=True,
                    completed_submaps=completed_this_run,
                    message="今日剩余吸取/召集/压制次数不足以安全完成下一张卡带",
                )

            # What _skip_card needs to tell whether a later card follows.
            self._follow_args = (cards_this_run, card_limit, allowed)
            selected = None
            for _attempt in range(card_retries):
                selected = self.navigator.select_collection_card(
                    card.card_id,
                    enter_visually_complete=False,
                )
                if selected.success:
                    break
            if selected is None or not selected.success:
                stopped = self._skip_card(
                    card,
                    f"进不去（{selected.message if selected else '-'}），"
                    "可能还没有这张卡带或章节还没开",
                    completed_this_run,
                )
                if stopped is not None:
                    return stopped
                continue
            if selected.outcome == CollectionCardSelectionOutcome.ENTERED:
                self._last_field_card_id = card.card_id
            if selected.outcome == CollectionCardSelectionOutcome.VISUALLY_COMPLETE:
                self._status(
                    "卡带完成度",
                    f"{card.card_id}进入前确认吸取与压制均已完成，记为本周完成",
                )
                self.progress.mark_card_complete_from_badge(card.card_id)
                continue

            # Route (user 2026-09-28): on the last map (e.g. chapter 6's 第5层)
            # go backwards (第5层 -> walk 第6层 -> 第1层); anywhere else start
            # from the town (第1层 -> 第6层 -> walk 第5层).  If a move fails,
            # the safe restart: hunting ground -> the town -> start over.
            here = self.navigator.current_collection_target(card)
            keys = [target.key for target in card.targets]
            # The whole route every time, whatever this PC recorded: a map
            # done already shows grey icons and is passed through (Leo
            # 2026-10-20 「以遊戲為準 不要讓工具紀錄的狀況影響跑圖」; ch14 went
            # town -> 中央回廊 by the teleport map because 左侧回廊 was
            # recorded, and 中央回廊 has no circle).
            order = list(card.targets)
            if here == keys[-1]:
                if card.card_id in LAST_MAP_THEN_TOWN_CARD_IDS:
                    # Last map first, then the town and the rest forward.
                    order = order[-1:] + order[:-1]
                else:
                    order.reverse()
            self._status(
                "采集进度",
                f"{card.card_id} 当前={here or '未知'}；顺序="
                + "→".join(target.title for target in order),
            )
            current = next((target for target in card.targets if target.key == here), None)
            if here not in (keys[0], keys[-1]):
                # Leo 2026-09-29: only two routes exist (town -> ... -> last,
                # or last -> ... -> town).  Anywhere else: hunting ground ->
                # the town, then the forward route.
                self._status("采集进度", f"{card.card_id} 不在起点或终点，经狩猎场或艾琳回主城")
                reset = self.navigator.prepare_collection_main_area(
                    card.card_id, via_hunting_ground=True
                )
                if not reset.success:
                    stopped = self._skip_card(
                        card, f"回主城失败（{reset.message}）", completed_this_run
                    )
                    if stopped is not None:
                        return stopped
                    continue
                current = card.targets[0]
            observed_depleted = False
            restarted = False
            search_confirmed = False
            before_search: list[str] = []
            # Maps finished in this pass: a restart walks through them again
            # without pressing anything there.
            done_here: set[str] = set()
            battled_here: dict[str, int] = {}
            index = 0
            while index < len(order):
                target = order[index]
                role = CollectionMapRole(target.key)
                arrived = self._go_to_collection_target(card, current, target)
                if arrived is not None and not arrived.success:
                    if restarted:
                        stopped = self._skip_card(
                            card,
                            f"前往{target.title}失败（{arrived.message}）",
                            completed_this_run,
                        )
                        if stopped is not None:
                            return stopped
                        break
                    restarted = True
                    self._status(
                        "采集进度",
                        f"前往{target.title}失败（{arrived.message}），经狩猎场或艾琳回主城重来",
                    )
                    reset = self.navigator.prepare_collection_main_area(
                        card.card_id, via_hunting_ground=True
                    )
                    if not reset.success:
                        stopped = self._skip_card(
                            card, f"回主城失败（{reset.message}）", completed_this_run
                        )
                        if stopped is not None:
                            return stopped
                        break
                    current = card.targets[0]
                    order = list(card.targets)
                    index = 0
                    continue
                current = target
                if target.key in done_here:
                    index += 1
                    continue
                used_up = self._absorb_used_up(card_id=card.card_id, map_role=role)
                if used_up is not None:
                    return self._skill_failure(card.card_id, role.label, used_up, completed_this_run)
                searched = self._ensure_search(map_role=role)
                if isinstance(searched, SearchCountdownSession):
                    search_confirmed = True
                elif not search_confirmed and not isinstance(searched, SkillExecutionResult):
                    # Collected before this card's 探查 was seen to start:
                    # its hidden items may not have been shown.
                    before_search.append(target.key)
                if isinstance(searched, SkillExecutionResult):
                    if not searched.depleted:
                        # A monster touched the character while 探查 was
                        # pressed (YES-BD2 #61): run away and do the map
                        # again, as after the other presses.
                        left = self._leave_battle(card, role)
                        if left == "left" and battled_here.get(target.key, 0) < BATTLE_REDOS_MAX:
                            battled_here[target.key] = battled_here.get(target.key, 0) + 1
                            continue
                        if left not in ("left", "none"):
                            stopped = self._skip_card(
                                card, f"{role.label}探查时撞到怪进了战斗，{left}", completed_this_run
                            )
                            if stopped is not None:
                                return stopped
                            break
                    stopped = self._skip_after_skill_failure(
                        card, f"{role.label}探查", searched, completed_this_run
                    )
                    if stopped is not None:
                        return stopped
                    break
                self._status("采集进度", f"{card.card_id} {role.label}：{target.title}")
                actions = (
                    (ABSORB_ACTION,) if role is CollectionMapRole.MAIN_AREA else BATTLE_ACTIONS
                )
                if target.key in battled_here and role is not CollectionMapRole.MAIN_AREA:
                    # Leo 2026-10-22 「逃跑完 就優先按壓制 再按其他的」「先把怪清掉」.
                    actions = AFTER_ESCAPE_ACTIONS
                result = self._use_actions(actions, card_id=card.card_id, map_role=role)
                if not result.completed:
                    # A monster touched the character (live 2K 2026-10-22,
                    # 第14章 战斗区域2): run away and do this map again (Leo
                    # 「逃跑完一樣繼續該圖的跑圖流程」), twice at most.
                    left = self._leave_battle(card, role)
                    if left == "left" and battled_here.get(target.key, 0) < BATTLE_REDOS_MAX:
                        battled_here[target.key] = battled_here.get(target.key, 0) + 1
                        continue
                    if left not in ("left", "none"):
                        stopped = self._skip_card(card, f"{role.label}撞到怪进了战斗，{left}", completed_this_run)
                        if stopped is not None:
                            return stopped
                        break
                if not result.completed:
                    if result.depleted:
                        return self._skill_failure(
                            card.card_id, role.label, result, completed_this_run
                        )
                    # One map's press that cannot be confirmed no longer
                    # drops the rest of the card: it is reported and the
                    # route goes on to the next map (Leo 2026-10-20 「沒記錄到
                    # 那也是要跑下一章吧」).  The card's badges decide at its end.
                    self._note_map_problem(card, role.label, result)
                    index += 1
                    continue
                done_here.add(target.key)
                if target.key in completed:
                    # Recorded before, passed through again on the route.
                    index += 1
                    continue
                committed = self.progress.mark_target(card.card_id, target.key)
                if not committed:
                    return CollectionResult(
                        True,
                        depleted=True,
                        completed_submaps=completed_this_run,
                        message=(
                            f"{card.card_id}{role.label}提交失败：今日技能额度已用尽，剩余地图留待次日"
                        ),
                    )
                completed.add(target.key)
                completed_this_run += 1
                observed_depleted = observed_depleted or result.depleted
                if observed_depleted and any(key not in completed for key in keys):
                    self.progress.mark_depleted_today()
                    return CollectionResult(
                        True,
                        depleted=True,
                        completed_submaps=completed_this_run,
                        message=(
                            f"{card.card_id}{role.label}已完成，"
                            "但实机技能次数已到上限，剩余地图留待次日"
                        ),
                    )
                index += 1
            if card in self._skipped_cards:
                continue

            # Still on the card's last map: the skill bar is on screen.  The
            # player's group goes back after the last card only (Leo
            # 2026-10-13 「跑圖有時候跑完還會切我的工具列」: it flipped back
            # and forth on every card).
            if observed_depleted or not self._another_card_follows(
                card, cards_this_run, card_limit, allowed
            ):
                self._restore_skill_group()
            # Straight to the card's own tab (Leo 2026-10-01: character cards went to
            # the story tab first and back).
            reopened = self.navigator.open_story_quick_switcher_from_sandbox(
                category=card.category
            )
            if not reopened.success:
                return CollectionResult(
                    False,
                    completed_submaps=completed_this_run,
                    message=f"{card.card_id}完成后无法打开快速切换页：{reopened.message}",
                )
            maps_done = len(completed) >= len(card.targets)
            verified = self._card_done_check(card, completed)
            if card.card_id in self._skill_skips:
                if verified.success or maps_done:
                    # The card is done: the unconfirmed press took.
                    self._skill_skips.pop(card.card_id)
                    self._unconfirmed_cards.discard(card.card_id)
                elif card not in self._skipped_cards:
                    self._skipped_cards.append(card)
            if not maps_done and self._badges_cut_off(verified):
                cards_this_run += 1
                continue
            cards_this_run += 1
            if maps_done:
                # Every map done = the card is done, whatever its badges read
                # (Leo 2026-10-21, see the check before the card).
                if not verified.success:
                    self.task.log_warning(
                        f"地图采集：{card.label}三张地图都跑过，记为本周完成"
                        f"（卡带图标读成未完成：{verified.message or '-'}）。"
                    )
                self.progress.mark_card_verified(card.card_id)
            elif not verified.success:
                # Leo 2026-10-05: one card left unfinished stopped the whole
                # run.  The card is collected again on the next run; go on.
                # Leo 2026-10-06: maps that were done stay recorded; only the
                # ones collected before this card's 探查 started are redone.
                redo = [key for key in before_search if key in completed]
                self.task.log_warning(
                    f"地图采集：{card.card_id}三张地图都做了，但卡带图标仍未完成"
                    f"（{verified.message or '-'}），"
                    + (
                        f"探查前就吸收的{'、'.join(redo)}之后重做，先跑下一张。"
                        if redo
                        else "其余地图保留记录，先跑下一张。"
                    )
                )
                if redo:
                    self.progress.reset_card(card.card_id, redo)
                else:
                    self.progress.keep_unverified_card(card.card_id)
                if card.card_id not in self._unfinished_cards:
                    self._unfinished_cards.append(card.card_id)
                self._badges_unfinished.add(card.card_id)
            elif len(completed) < len(card.targets):
                # The game's badges show it done, a map's press only went
                # unconfirmed here: the game decides.
                self.progress.mark_card_complete_from_badge(card.card_id)
            else:
                self.progress.mark_card_verified(card.card_id)

            if observed_depleted and not self.progress.state.depleted_today:
                self.progress.mark_depleted_today()

            state = self.progress.state
            effective = self.progress.effective_daily_counts()
            pending = self.progress.pending_count()
            self._status(
                "每日技能进度",
                (
                    f"吸取 {effective['吸收']}/{self.progress.limit_of('吸收')}"
                    f"（本地{state.daily_absorbs}）；"
                    f"召集 {effective['召集']}/{self.progress.limit_of('召集')}"
                    f"（本地{state.daily_summons}）；"
                    f"压制 {effective['压制']}/{self.progress.limit_of('压制')}"
                    f"（本地{state.daily_suppressions}）"
                    + (f"；待对账{pending}条" if pending else "")
                ),
            )
            if state.depleted_today:
                return CollectionResult(
                    True,
                    depleted=True,
                    completed_submaps=completed_this_run,
                    message=(
                        "当前卡带已完成并通过复核；实机技能次数显示已到上限"
                        if observed_depleted
                        else self._used_up_today()
                    )
                    + (
                        f"；另有{self.progress.pending_count()}条动作次数待后续明亮帧对账"
                        if self.progress.pending_count()
                        else ""
                    ),
                )

        pending = self.progress.pending_count()
        skipped = "、".join(str(n) for n in sorted(UNSUPPORTED_COLLECTION_CARD_NUMBERS))
        return CollectionResult(
            True,
            completed_submaps=completed_this_run,
            message=(
                "本周已支持的可采集卡带已经处理完毕"
                + (
                    f"；{'、'.join(self._unfinished_cards)}图标仍未完成，之后重新采集"
                    if self._unfinished_cards
                    else ""
                )
                + (f"；第{skipped}章等待专用流程" if skipped else "")
                + (f"；末图有{pending}条动作次数待后续明亮帧对账" if pending else "")
            ),
        )

    def _used_up_today(self) -> str:
        """Which skills the game showed used up today, in player words (it
        said 「已完成今日7张卡带，达到每日21次吸取上限」 whatever the limit or
        the cards done were)."""
        used = [name for name in ("吸收", "召集", "压制") if self.progress.game_used_up(name)]
        if not used:
            return "今天的技能次数已用完，剩下的地图明天再跑"
        return f"今天的{'、'.join(used)}次数游戏已显示用完，剩下的地图明天再跑"

    def _card_done_check(self, card, completed) -> CollectionCardSelectionResult:
        """The game's badges for the card (第6章 by its own badge rule)."""
        return self.navigator.inspect_collection_card_completion(card.card_id)

    def _badges_cut_off(self, verified) -> bool:
        """The card's badge row is cut off at the quick bar's edge.

        Live 2K 2026-09-29: 第11章 sat at the bar's right edge and the wheel
        did not move it; its three maps were proven one by one (count +1 and
        greyed icon), and the collection page showed it complete.  The visual
        double-check is skipped with a warning instead of failing the run;
        it is retried on the next run.
        """
        completion = getattr(verified, "completion", None)
        if verified.success or completion is None or completion.complete_region:
            return False
        self.task.log_warning(
            "地图采集：卡带在快速栏边缘，完成度图标被切到，无法视觉复核；"
            "三张地图已逐一确认，继续下一张（下次运行再复核）。"
        )
        return True

    def _another_card_follows(self, card, cards_this_run, card_limit, allowed) -> bool:
        """A later card will be entered this run, so the collection skill
        group can stay selected for it.  Leans to False: then the group goes
        back now, as before."""
        if card_limit and cards_this_run + 1 >= card_limit:
            return False
        if self.progress.state.depleted_today:
            return False
        cards = list(COLLECTABLE_CARDS)
        if card not in cards:
            return False
        for other in cards[cards.index(card) + 1 :]:
            if allowed is not None and other.filter_key not in allowed:
                continue
            if other.number in UNSUPPORTED_COLLECTION_CARD_NUMBERS:
                continue
            completed = self.progress.state.completed_targets(other.card_id)
            if len(completed) >= len(other.targets):
                continue
            return bool(self._can_finish_card_today(other, completed))
        return False

    def _restore_on_last_field(self) -> None:
        """The group was kept for a next card that was then not entered
        (skipped, already complete, failed to open): enter the last card
        again and put the player's group back there (Leo's rule: the tool
        never leaves the skill group changed)."""
        keeper = getattr(self, "skill_group_keeper", None)
        card_id = getattr(self, "_last_field_card_id", None)
        if keeper is None or not keeper.switched or card_id is None:
            return
        try:
            if keeper.read() is not None:
                return  # still on a field: the normal restore does it
            self.task.log_info(
                f"地图采集：结束时不在地图上，回到{card_id}把技能组切回原本那组。"
            )
            entered = self.navigator.select_collection_card(
                card_id, enter_visually_complete=True
            )
            if entered.outcome == CollectionCardSelectionOutcome.ENTERED and wait_for(
                keeper.read, SLOW_PC_GRACE_SECONDS, sleep=self.task.sleep, poll=0.5
            ):
                keeper.restore()
                if not keeper.switched:
                    self.navigator.return_home()
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.task.log_warning(f"地图采集：回地图切回技能组失败：{exc}")

    def _restore_skill_group(self, **kwargs) -> None:
        keeper = getattr(self, "skill_group_keeper", None)
        if keeper is not None:
            keeper.restore(**kwargs)

    def _cards_with_one_retry(self):
        """Every card in order; a card left unfinished by this run (a map
        not confirmed, a failed move, badges still open) is run once more
        straight away, judged again by the game's screen (Leo 2026-10-20
        「一個卡帶就三張地圖而以 不要讓工具判斷錯誤導致沒有完成」).  A card
        that cannot be entered at all is not retried."""
        retried: set[str] = set()
        for card in COLLECTABLE_CARDS:
            yield card
            if card.card_id in retried or not self._card_left_unfinished(card):
                continue
            retried.add(card.card_id)
            self._status("采集进度", f"{card.card_id}没有完成，照游戏画面再跑一次")
            self.task.log_warning(f"地图采集：{card.label}没有完成，再跑一次。")
            self._forget_card_problems(card)
            yield card

    def _card_left_unfinished(self, card) -> bool:
        if card.card_id in getattr(self, "_badges_unfinished", set()):
            return True
        if card not in self._skipped_cards:
            return False
        reason = self._skip_reasons.get(card.card_id, "")
        return not reason.startswith("进不去")

    def _forget_card_problems(self, card) -> None:
        """The retry's own outcome is what the report tells."""
        from src.tasks import problem_report

        problem_report.forget_skip()
        self._skipped_cards = [item for item in self._skipped_cards if item.card_id != card.card_id]
        self._skill_skips.pop(card.card_id, None)
        self._skip_reasons.pop(card.card_id, None)
        self._unconfirmed_cards.discard(card.card_id)
        self._badges_unfinished.discard(card.card_id)
        if card.card_id in self._unfinished_cards:
            self._unfinished_cards.remove(card.card_id)

    def _go_to_collection_target(self, card, current, target):
        """None when already there, else the navigation result."""
        if current is not None and current.key == target.key:
            return None
        if current is None:
            arrived = self.navigator.prepare_collection_main_area(card.card_id)
            if not arrived.success or target.key == card.targets[0].key:
                return arrived
            current = card.targets[0]
        return self.navigator.advance_collection_map(card.card_id, current, target)

    def _can_finish_card_today(self, card, completed: set[str]) -> bool:
        remaining = [target for target in card.targets if target.key not in completed]
        return self.progress.can_plan_collection(remaining)

    def _skip_card(self, card, reason: str, completed_this_run: int) -> CollectionResult | None:
        """Decision 6 of the 2026-10-10 plan (its default, not yet answered
        by Leo): a card that cannot be entered or travelled no longer stops
        every later card.  It is skipped from the home screen, nothing is
        recorded for it and it stays in 跑图章节.
        None = go on; a result = stop, home was not reached."""
        self._skipped_cards.append(card)
        self._skip_reasons.setdefault(card.card_id, reason)
        self.task.log_warning(f"地图采集：{card.label}{reason}，先跳过，继续下一张。")
        self._note_skip_screen()
        # A skipped card keeps the collection group too when a later card
        # follows (Leo 2026-10-15 「一張卡帶跑完都會把技能欄切成錯的 下張圖又
        # 切回來」: 2K, Q_cp7 skipped → group 3, Q_ep1 → group 2 again).  If
        # none is entered after all, the run's end puts it back.
        follow = getattr(self, "_follow_args", None)
        if follow is None or not self._another_card_follows(card, *follow):
            self._restore_skill_group()
        returned = self.navigator.return_home()
        if returned.success:
            return None
        if self._recover_home_after_skip(card, returned.message):
            return None
        return CollectionResult(
            False,
            completed_submaps=completed_this_run,
            message=f"{card.label}跳过后回不到主页（{returned.message}），停止跑图",
        )

    def _note_skip_screen(self) -> None:
        """The 问题摘要 shows where the first skipped card stopped, not the
        run's last screen (player 2026-10-23: 第11章 under 第14章's frame)."""
        capture = getattr(self.task, "capture_frame", None)
        if capture is None:
            return
        try:
            from src.tasks import problem_report

            problem_report.note_skip(self.task, capture())
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:  # a lost picture must never stop the run
            self.task.log_info(f"地图采集：跳过时的画面没留下（{exc}）。")

    def _recover_home_after_skip(self, card, why: str) -> bool:
        """The general way home (back arrow, H, and Esc one step at a time)
        when the map pages' own way found no safe path (YES-BD2 #24: a map
        page left open stopped the whole run; Leo 2026-10-13 「能不能直接esc
        然后换下一张卡带」).  True = home, the next card goes on."""
        if not hasattr(self.task, "capture_frame"):
            return False
        from src.tasks.recovery import recover_to_home

        self.task.log_warning(
            f"地图采集：{card.label}跳过后没认出回主页的路（{why}），改用通用退出再回主页。"
        )
        try:
            return bool(recover_to_home(self.task))
        except (TaskDisabledException, FinishedException):
            raise
        except Exception as exc:
            self.task.log_warning(f"地图采集：通用退出失败：{exc}")
            return False

    def _skip_after_skill_failure(
        self,
        card,
        stage: str,
        result: SkillExecutionResult,
        completed_this_run: int,
    ) -> CollectionResult | None:
        """Leo 2026-10-12: a skill that cannot be confirmed on one map skips
        that card and the run goes on; the report names the card, the map and
        why.  Used-up skills still end the day's run.  None = go on."""
        if result.depleted:
            return self._skill_failure(card.card_id, stage, result, completed_this_run)
        self._record_skill_failure(card.card_id, stage, result)
        problem = f"{stage}技能操作失败" + (f"：{result.message}" if result.message else "")
        self._skill_skips.setdefault(card.card_id, problem)
        if self._press_probably_taken(result):
            self._unconfirmed_cards.add(card.card_id)
        return self._skip_card(card, problem, completed_this_run)

    def _leave_battle(self, card, role) -> str:
        """A field battle on screen after a press: see BaseBD2Task.leave_field_battle."""
        leave = getattr(self.task, "leave_field_battle", None)
        if not callable(leave):
            return "none"
        left = leave(f"地图采集：{card.label}{role.label}")
        if left == "left":
            self._status("采集进度", f"{card.card_id} {role.label}：离开战斗，重做这张图")
        return left

    def _note_map_problem(self, card, stage: str, result: SkillExecutionResult) -> None:
        """A map whose press could not be confirmed: kept for the report,
        the card's route goes on."""
        self._record_skill_failure(card.card_id, stage, result)
        problem = f"{stage}技能操作失败" + (f"：{result.message}" if result.message else "")
        if card.card_id in self._skill_skips:
            self._skill_skips[card.card_id] += f"；{problem}"
        else:
            self._skill_skips[card.card_id] = problem
        if self._press_probably_taken(result):
            self._unconfirmed_cards.add(card.card_id)
        self.task.log_warning(f"地图采集：{card.label}{problem}，继续下一张图。")

    @staticmethod
    def _press_probably_taken(result: SkillExecutionResult) -> bool:
        """The icon went grey after the press, only its count or toast could
        not be read: most likely done, just not proven (live 4K 2026-10-14,
        压制 11/75 read as 11775).  Leo: 「確定沒做」 and 「沒法確認」 are told
        apart, and the second does not fail the whole run."""
        return "icon=available->used" in str(result.message or "")

    def _with_skipped_cards(self, result: CollectionResult) -> CollectionResult:
        """A skipped card is not done, so the run is never reported as complete."""
        if not self._skipped_cards:
            return result
        cards = list({card.card_id: card for card in self._skipped_cards}.values())
        unconfirmed = getattr(self, "_unconfirmed_cards", set())
        notes = []
        for card in cards:
            if card.card_id not in self._skill_skips:
                continue
            problem = self._skill_skips[card.card_id]
            if card.card_id in unconfirmed:
                problem = problem.replace("技能操作失败", "技能可能已按上但没能确认")
            notes.append(f"{card.label}{problem}，其余地图照跑，没完成的下次运行再补")
        missing = [card for card in cards if card.card_id not in self._skill_skips]
        if missing:
            names = _card_names(missing)
            reasons = getattr(self, "_skip_reasons", {})
            # Cards that stopped for the same reason share one entry, so a
            # long run of skips keeps every reason inside the report's line
            # (player 2026-10-19: nine chapters skipped, the reasons of
            # 第5–11章 were cut off after 第3章's).
            grouped: dict[str, list] = {}
            for card in missing:
                if reasons.get(card.card_id):
                    grouped.setdefault(reasons[card.card_id], []).append(card)
            why = "；".join(
                f"{group[0].label}{reason}"
                if len(group) == 1
                else f"{_card_names(group)}都{reason}"
                for reason, group in grouped.items()
            )
            notes.append(
                f"{names}这次跳过，没有完成"
                + (f"（原因：{why}）" if why else "")
            )
        note = "；".join(notes)
        self.task.log_warning(f"地图采集：{note}。")
        # The summary's 「停在」 is 当前阶段: without this it kept the step of
        # the card after the skip (Leo 4K 2026-10-17 「寻找快速切换按钮」).
        info_set = getattr(self.task, "info_set", None)
        if callable(info_set):
            skipped = _card_names(cards)
            info_set("当前阶段", f"地图采集：{skipped}跳过，没有完成")
        # Only presses that surely did not happen fail the run; one that
        # most likely took (icon greyed) is reported, not failed.
        failed = any(card.card_id not in unconfirmed for card in cards)
        return replace(
            result,
            success=result.success and not failed,
            message=f"{note}；{result.message}" if result.message else note,
        )

    def _skill_failure(
        self,
        card_id: str,
        stage: str,
        result: SkillExecutionResult,
        completed_this_run: int,
    ) -> CollectionResult:
        self._record_skill_failure(card_id, stage, result)
        if result.depleted:
            self.progress.mark_depleted_today()
            return CollectionResult(
                True,
                depleted=True,
                completed_submaps=completed_this_run,
                message=result.message or f"{card_id}{stage}技能次数已用尽",
            )
        return CollectionResult(
            False,
            completed_submaps=completed_this_run,
            message=(
                f"{card_id}{stage}技能操作失败" + (f"：{result.message}" if result.message else "")
            ),
        )

    def _record_skill_failure(
        self,
        card_id: str,
        stage: str,
        result: SkillExecutionResult,
    ) -> None:
        """Retain bounded, replayable evidence for a final skill miss."""

        message = str(result.message or "")[:SKILL_FAILURE_TEXT_LIMIT]
        evidence = {
            "card": str(card_id),
            "phase": str(stage),
            "completed": bool(result.completed),
            "depleted": bool(result.depleted),
            "message": message,
            "geometry": deepcopy(self._last_skill_geometry),
            "observations": deepcopy(self._last_skill_observations),
        }
        self._skill_failure_evidence.append(evidence)
        try:
            self.task.log_info(
                f"{DIAGNOSTIC_PREFIX}地图采集：技能识别失败证据"
                f"（最近{len(self._skill_failure_evidence)}条） {evidence}"
            )
        except AttributeError:
            pass

    @property
    def skill_failure_evidence(self) -> tuple[dict[str, object], ...]:
        """Return a copy of the bounded failure replay tail for diagnostics."""

        return tuple(deepcopy(item) for item in self._skill_failure_evidence)

    def _status(self, key: str, value) -> None:
        try:
            self.task.info_set(key, value)
        except AttributeError:
            pass


def _card_names(cards) -> str:
    """「第3章、第5章至第11章」: chapters in a row are named as a range."""
    names: list[str] = []
    run: list = []

    def flush() -> None:
        if len(run) > 2:
            names.append(f"{run[0].label}至{run[-1].label}")
        else:
            names.extend(card.label for card in run)
        run.clear()

    for card in cards:
        if (
            run
            and card.category == run[-1].category
            and card.number == run[-1].number + 1
        ):
            run.append(card)
            continue
        flush()
        run.append(card)
    flush()
    return "、".join(names)
