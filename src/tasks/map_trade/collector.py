from __future__ import annotations

from collections import deque
from copy import deepcopy

from src.tasks.map_trade import account_check
from src.tasks.map_trade.action_icons import ActionIconDetector
from src.tasks.map_trade.card_status import CollectionCardSelectionOutcome
from src.tasks.map_trade.collector_constants import (
    ABSORB_ACTION,
    BATTLE_ACTIONS,
    SKILL_FAILURE_EVIDENCE_LIMIT,
    SKILL_FAILURE_TEXT_LIMIT,
    UNSUPPORTED_COLLECTION_CARD_NUMBERS,
    SearchCountdownSession,
    SkillExecutionResult,
)
from src.tasks.map_trade.collector_skills import SkillExecutionMixin
from src.tasks.map_trade.models import (
    COLLECTABLE_CARDS,
    LAST_MAP_THEN_TOWN_CARD_IDS,
    CollectionMapRole,
    CollectionResult,
)
from src.tasks.map_trade.navigator import Navigator
from src.tasks.map_trade.progress import ProgressStore
from src.tasks.map_trade.vision import Vision

# "卡带单步重试次数"未配置时的默认值。
CARD_RETRY_DEFAULT = 2


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
        self._last_count_window_stable = False

    def run(self) -> CollectionResult:
        # A Collector instance can be reused by the task scheduler.  Recovery
        # is bounded once per formal run, while direct helper calls retain the
        # latch until the next run invocation.
        self._group_one_recovery_attempted = False
        try:
            return self._run_collection()
        except RuntimeError as exc:
            self.task.log_error("地图采集流程异常", exc)
            return CollectionResult(
                False,
                message=f"地图采集流程异常：{exc}",
            )

    def _run_collection(self) -> CollectionResult:
        state = self.progress.load()
        if state.depleted_today or state.daily_submaps >= self.progress.limit_of("吸收"):
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
        for card in COLLECTABLE_CARDS:
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
                if state.card_verified(card.card_id):
                    continue
                verified = self.navigator.inspect_collection_card_completion(card.card_id)
                if self._badges_cut_off(verified):
                    continue
                if verified.success:
                    self.progress.mark_card_verified(card.card_id)
                    continue
                # Something is still left, but which map is not known: the
                # maps stay recorded (Leo 2026-10-06) and the run goes on.
                self.task.log_warning(
                    f"地图采集：{card.card_id}三张地图已有进度，但卡带图标仍未完成"
                    f"（{verified.message or '-'}），先跑下一张。"
                )
                self.progress.keep_unverified_card(card.card_id)
                self._unfinished_cards.append(card.card_id)
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

            selected = None
            for _attempt in range(card_retries):
                selected = self.navigator.select_collection_card(
                    card.card_id,
                    enter_visually_complete=False,
                )
                if selected.success:
                    break
            if selected is None or not selected.success:
                return CollectionResult(
                    False,
                    completed_submaps=completed_this_run,
                    message=f"未能进入卡带 {card.card_id}",
                )
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
            order = [target for target in card.targets if target.key not in completed]
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
                    return CollectionResult(
                        False,
                        completed_submaps=completed_this_run,
                        message=f"{card.card_id}回主城失败：{reset.message}",
                    )
                current = card.targets[0]
            observed_depleted = False
            restarted = False
            search_confirmed = False
            before_search: list[str] = []
            index = 0
            while index < len(order):
                target = order[index]
                role = CollectionMapRole(target.key)
                arrived = self._go_to_collection_target(card, current, target)
                if arrived is not None and not arrived.success:
                    if restarted:
                        return CollectionResult(
                            False,
                            completed_submaps=completed_this_run,
                            message=f"{card.card_id}前往{target.title}失败：{arrived.message}",
                        )
                    restarted = True
                    self._status(
                        "采集进度",
                        f"前往{target.title}失败（{arrived.message}），经狩猎场或艾琳回主城重来",
                    )
                    reset = self.navigator.prepare_collection_main_area(
                        card.card_id, via_hunting_ground=True
                    )
                    if not reset.success:
                        return CollectionResult(
                            False,
                            completed_submaps=completed_this_run,
                            message=f"{card.card_id}回主城失败：{reset.message}",
                        )
                    current = card.targets[0]
                    order = [item for item in card.targets if item.key not in completed]
                    index = 0
                    continue
                current = target
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
                    return self._skill_failure(
                        card.card_id, f"{role.label}探查", searched, completed_this_run
                    )
                self._status("采集进度", f"{card.card_id} {role.label}：{target.title}")
                actions = (
                    (ABSORB_ACTION,) if role is CollectionMapRole.MAIN_AREA else BATTLE_ACTIONS
                )
                result = self._use_actions(actions, card_id=card.card_id, map_role=role)
                if not result.completed:
                    return self._skill_failure(card.card_id, role.label, result, completed_this_run)
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
            verified = self.navigator.inspect_collection_card_completion(card.card_id)
            if self._badges_cut_off(verified):
                cards_this_run += 1
                continue
            cards_this_run += 1
            if not verified.success:
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
                self._unfinished_cards.append(card.card_id)
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
                        else "已完成今日7张卡带，达到每日21次吸取上限"
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
            self.task.log_warning(
                f"地图采集：技能识别失败证据（最近{len(self._skill_failure_evidence)}条）"
                f" {evidence}"
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
