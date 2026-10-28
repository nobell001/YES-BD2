"""魔兽追踪者自动站位 (replay) and 魔兽录制 (record), started on the
fight's planning screen (TURN shown on the BATTLE button).

回放: each turn the tool reads who stands where and the 1-N order, fixes
them to match the saved turn, checks again and presses BATTLE.  On any
mismatch it stops before BATTLE and leaves the planning screen to the
player (认不准就不按).

录制 lives on the 魔兽追踪者 page (Leo 2026-10-06; its own page since 10-01): the player picks or
makes a save there and starts FiendHuntRecordTask (not listed among the
tasks).  Each turn the player arranges by hand and presses the record key
(F8 unless set otherwise, F6-F12) instead of BATTLE; the tool reads the
screen, saves the turn with a screenshot and presses BATTLE itself.  It
only reads the key, it never sends it.  Recording into an existing save
edits it; the page lists its turns, deletes one or picks one to redo.

A save is chosen as a folder (button opening configs/fiend_hunt), not by
typing its name; the old 存档名称 setting is still read as a fallback.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ok import Config
from ok.util.file import get_relative_path
from qfluentwidgets import FluentIcon

from src.tasks.BaseBD2Task import BaseBD2Task
from src.tasks.fiend_hunt import vision
from src.tasks.fiend_hunt.fight import (
    ScreenReadError,
    minutes_and_seconds,
    replay_fight,
    summons_only,
)
from src.tasks.fiend_hunt.keep import KeptFight
from src.tasks.fiend_hunt.preflight import check_folder
from src.tasks.fiend_hunt.record import FightRecord, TurnStateError, load_record
from src.tasks.fiend_hunt.recording import RECORD_FILE, record_fight
from src.tasks.fiend_hunt.saves import (
    saved_turns,
    valid_save_name,
)
from src.tasks.fiend_hunt.screen import (
    GameFightScreen,
    bursts_from_screenshots,
    load_frame,
    record_names,
)
from src.tasks.fiend_hunt.shots import ScreenshotTurns, find_screenshots
from src.tasks.fiend_hunt.souseha import load_game_names

MODE_REPLAY = "回放存档"
MODE_RECORD = "录制（按录制键保存本回合）"  # moved to the 魔兽追踪者 page; old configs only
# Leo 2026-10-06: 导入攻略图 removed; an old config set to it replays.
MODES = (MODE_REPLAY,)
# Leo 2026-10-01: a fight played from screenshots alone, kept as a save.
KEEP_OPTION = "只有截图时，完成战斗新增动作档至资料夹"
# Leo 2026-10-06: most bosses never move anyone (one did in a year), so the
# per-unit cell checks before BATTLE are skipped unless this is ticked.
PUSH_OPTION = "魔兽会推动角色位置"
# Whose attack or skill a replay checks (Leo, 2026-09-30).
CARDS_SUMMONS = "只有召唤物判断技能（较快较稳定，需先设好服装施放顺序）"
CARDS_ALL = "全部判断技能、顺序、站位（较慢，建议先设好服装施放顺序）"
CARD_CHOICES = (CARDS_SUMMONS, CARDS_ALL)
# The record key: an F-key, as the takeover guard lets those through to the
# game without stopping the task (any other key counts as the player taking over).
# Leo 2026-10-06: F6-F10 (the game takes none of them); 2026-10-09 F6-F12, set
# in 设置 with the pause and stop keys (src/ui/shell/hotkeys.py); else F8.
KEY_CHOICES = tuple(f"F{number}" for number in range(6, 13))
NO_KEY = "无"  # Leo 2026-10-20: the record key can be off (src/ui/shell/hotkeys.NONE)
DEFAULT_KEY = "F8"
SAVE_KEY_NAME = DEFAULT_KEY
DAMAGE_FILE = "伤害记录.csv"
VK_F8 = 0x77
# Each unit's card column as recorded (to learn which costume each skill card is).
CARDS_FOLDER = "卡片"
CHARACTERS_FILE = Path(__file__).resolve().parent / "fiend_hunt" / "data" / "characters.json"


def saves_root() -> Path:
    return Path(get_relative_path(Config.config_folder, "fiend_hunt"))


def record_folder(name: str) -> Path:
    return saves_root() / name


def chosen_save(config) -> Path | None:
    """The save folder a task's config points at: 存档 (a folder), else the old 存档名称."""
    value = str(config.get("存档", "") or "").strip()
    folder = Path(value) if value else None
    if folder is not None and folder.is_dir():  # a save of screenshots alone has no record.json
        return folder
    name = str(config.get("存档名称", "") or "").strip()
    if valid_save_name(name) and (record_folder(name) / RECORD_FILE).is_file():
        return record_folder(name)
    return folder


def valid_record_name(name: str) -> bool:
    return valid_save_name(name)


def key_code(name: str) -> int:
    """Virtual-key code of F6-F12 (F8 for anything else)."""
    if name not in KEY_CHOICES:
        name = DEFAULT_KEY
    return 0x70 + int(name[1:]) - 1


def known_character_names(path: Path | None = None) -> set[str]:
    """In-game (简中) names of characters and summons, if the list is there
    (by default the newer copy an update brought, if any)."""
    if path is None:
        from src.tasks.fiend_hunt.character_files import characters_file

        path = characters_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = set()
    for entry in data.get("characters", []) + data.get("summons", []):
        name = entry.get("name_zh_cn") if isinstance(entry, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


class HotKey:
    """SaveKey: presses of one key seen by polling (the game never gets a key from us)."""

    def __init__(self, code: int = VK_F8) -> None:
        import win32api

        self._code = code
        self._get = win32api.GetAsyncKeyState
        self._down = bool(self._get(code) & 0x8000)
        self._get(code)  # drop a press made before recording started

    def pressed(self) -> bool:
        state = self._get(self._code)
        down = bool(state & 0x8000)
        new_press = (down and not self._down) or bool(state & 0x1)
        self._down = down
        return new_press


F8Key = HotKey  # the record key used to be F8 only


class FiendHuntTask(BaseBD2Task):
    status_keys = [
        "状态",
        "模式",
        "存档",
        "当前回合",
        "已打回合",
        "用时",
        "停下原因",
        "Log",
        "Warning",
        "Error",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "魔兽追踪者自动站位"
        self.description = (
            "推荐先在「魔兽追踪者」页用 F8 自己录一场，回放最快最稳；"
            "只有截图也能打（存档文件夹里放每回合的截图）。"
            "在魔兽追踪者的排位画面（BATTLE 按钮显示 TURN）开始。"
            "回放：每回合按存档调整站位和行动顺序，核对无误才按 BATTLE，对不上就停下交给你。"
        )
        self.icon = FluentIcon.PEOPLE
        self.group_name = "魔兽追踪者"
        self.group_icon = FluentIcon.PEOPLE
        self.visible = True
        self.player_plays_along = False
        self.default_config.update(
            {
                "模式": MODE_REPLAY,
                "存档": "",
                "存档名称": "",
                "技能判断": CARDS_SUMMONS,
                "打到第几回合": 0,
                KEEP_OPTION: True,
                PUSH_OPTION: False,
            }
        )
        self.config_description.update(
            {
                "模式": "回放存档。录制在「魔兽追踪者」页。",
                "存档": (
                    "按「浏览」选存档文件夹（默认在 configs\\fiend_hunt），"
                    "里面有 record.json 和每回合截图。"
                    "也可以只放每回合排好后的游戏截图（俯视视角、没选人），"
                    "工具照截图排位，卡照「技能判断」核对。"
                ),
                "技能判断": (
                    "回放时核对谁选的攻击或技能。"
                    "只看召唤物：角色的技能交给游戏里的「服装使用顺序设置」（要先设好），"
                    "工具只排顺序和站位，召唤物不能在那里设定，一定要核对。"
                    "全部判断：每个人的卡都照存档（或截图）选，不一样会改回来，改不成就停。"
                ),
                "打到第几回合": "回放打完这一回合就停在下一回合的排位画面；0 = 打到战斗结束。",
                PUSH_OPTION: (
                    "勾选：魔兽或技能会把角色推走、换位，每回合按 BATTLE 前逐个确认站位（较慢）。"
                    "不勾：站位没变的回合不再逐个确认（较快）。"
                ),
                KEEP_OPTION: (
                    "推荐，不需额外设定。这是新增动作档：只有截图的存档完整打完一场后，"
                    "自动在同一个文件夹存一份动作档（record.json），下次照它回放。"
                    "不建议关闭，可增加稳定性和游戏速度。"
                ),
            }
        )
        self.config_type.update(
            {
                "模式": {
                    "type": "drop_down",
                    "options": list(MODES),
                    "sub_configs": {
                        MODE_REPLAY: ["存档", "技能判断", "打到第几回合", PUSH_OPTION, KEEP_OPTION],
                    },
                },
                "存档": {
                    "type": "file_selector",
                    "selector_type": "folder",
                    "dialog_title": "选择存档文件夹",
                },
                "存档名称": {"hidden": True},  # the old typed name, read as a fallback
                "技能判断": {"type": "drop_down", "options": list(CARD_CHOICES)},
                "打到第几回合": {"min": 0, "max": 99, "step": 2},
            }
        )

    def run(self):
        self.info_set("模式", MODE_REPLAY)  # the only mode left (导入攻略图 removed)
        folder = chosen_save(self.config)
        self.info_set("存档", folder.name if folder else "-")
        if folder is None or not folder.is_dir():
            return self._stop("先按「存档」那一行的「浏览」选一个存档文件夹")
        if (folder / RECORD_FILE).is_file():
            return self._replay(folder)
        return self._replay_screenshots(folder)

    def _replay(self, folder: Path) -> bool:
        path = folder / RECORD_FILE
        if not path.exists():
            return self._stop(f"找不到存档 {path}")
        try:
            record = bursts_from_screenshots(load_record(path), folder)
        except (OSError, TurnStateError) as error:
            return self._stop(f"存档读不了：{error}")
        last = int(self.config.get("打到第几回合", 0) or 0)
        screen = GameFightScreen(
            self, record_names(record), record=record, folder=folder, log=self._turn_log
        )
        self.info_set("状态", "回放中")
        # Leo 2026-10-06: two ways to play a save.  全部判断 (调整服装技能)
        # plays it as charted: every card checked, auto skills off.  只看召唤物
        # (不调整) leaves the characters' skills to the costume order set in
        # the game (auto skills on) and checks the summons' cards only.
        # A record kept from screenshots (KEEP_OPTION) is checked against
        # them before each BATTLE, cells and the summon's badge included, so
        # a turn it got wrong can never be replayed blindly (Leo 2026-10-01).
        learned = None
        if record.source == "screenshots" and record.screenshots:
            learned = ScreenshotTurns(
                screen,
                folder,
                record.screenshots,
                None,
                load_frame,
                self._turn_log,
                summons_only(load_game_names().characters.values()),
            ).check
        check = self._card_check()
        if check is not None:
            self._turn_log("只看召唤物：角色的技能照游戏里的服装使用顺序，只核对召唤物的卡")
        if not self._auto_skills(screen, on=check is not None):
            return False
        try:
            outcome = replay_fight(
                screen,
                record,
                last_turn=last or None,
                check_card=check,
                check=learned,
                pushes=self._pushes(),
                log=self._turn_log,
            )
        except ScreenReadError as error:
            return self._stop(str(error))
        mode = "照排轴，" + ("全部判断" if check is None else "只看召唤物")
        return self._finish(screen, folder, outcome, last, mode)

    def _pushes(self) -> bool:
        pushes = bool(self.config.get(PUSH_OPTION, False))
        if not pushes:
            self._turn_log("魔兽不推人：站位没变的回合不再逐个确认")
        return pushes

    def _replay_screenshots(self, folder: Path) -> bool:
        """Fight from a folder holding only the player's screenshot of each turn
        (Leo's first idea, 2026-09-30): see fiend_hunt/shots.py."""
        last = int(self.config.get("打到第几回合", 0) or 0)
        record = FightRecord({}, title=folder.name, source="screenshots")
        # Names come from the game as in recording (the screenshots show none).
        screen = GameFightScreen(
            self,
            known_character_names(),
            learn_names=True,
            read_cards=False,
            record=record,
            folder=folder,
            log=self._turn_log,
        )
        notes: list[str] = []
        files = find_screenshots(
            folder, lambda frame: vision.read_turn(frame, screen.ocr), load_frame, notes.append
        )
        if not files:
            for note in notes:
                self._turn_log(note)
            return self._stop(
                f"{folder.name} 里没有 record.json，也没有能用的排位截图"
                "（要俯视视角、没选人、右下角有 TURN 的游戏全画面）"
            )
        # Leo 2026-10-01: what's missing or unusable is said before the fight.
        try:
            live_turn = screen.read_turn()
        except ScreenReadError:
            live_turn = None
        checked = check_folder(files, [n for n in notes if n.endswith("跳过")], live_turn)
        for line in [n for n in notes if not n.endswith("跳过")] + checked.summary():
            self._turn_log(line)
        if checked.problem is not None:
            return self._stop(f"{checked.problem}（还没开打）")
        check = self._card_check()
        whose = "每个人的卡" if check is None else "召唤物的卡（角色的卡交给服装顺序）"
        self._turn_log(f"只靠截图打：{whose}照截图核对")
        self.info_set("状态", "回放中（只靠截图）")
        solver = ScreenshotTurns(
            screen,
            folder,
            files,
            screen.team_of,
            load_frame,
            self._turn_log,
            summons_only(load_game_names().characters.values()),
            check_card=check,
        )
        kept = KeptFight(screen, folder, solver, folder.name, self._turn_log)
        # As in a record replay: 全部判断 sets every card (auto skills off);
        # 只认召唤物 lets the costume order pick the characters' (on), which
        # spares setting every card each turn (4K PC 2026-10-01: 8 min to 4).
        if not self._auto_skills(screen, on=check is not None):
            return False
        try:
            outcome = replay_fight(
                screen,
                record,
                last_turn=last or None,
                check_card=check,
                solve=kept.solve,
                check=kept.check,
                pushes=self._pushes(),
                log=self._turn_log,
            )
        except ScreenReadError as error:
            return self._stop(str(error))
        # Only a fight played to its end screen is kept (Leo 2026-10-01).
        # Only a fight played from its first screenshot to the end screen: one
        # started mid-fight would keep a record missing its first turns.
        whole = set(files) <= set(outcome.turns_played) or (
            min(outcome.turns_played, default=99) <= min(files)
        )
        if outcome.finished and whole and self.config.get(KEEP_OPTION, True):
            if kept.keep(outcome.turns_played) is not None:
                self._turn_log(
                    f"已存成存档（{folder.name}\\record.json），下次选这个文件夹就直接用存档回放"
                )
        mode = "只靠截图，" + ("全部判断" if check is None else "只看召唤物")
        return self._finish(screen, folder, outcome, last, mode)

    def _auto_skills(self, screen: GameFightScreen, *, on: bool) -> bool:
        """The diamond top right (auto skills), set by mode (Leo 2026-10-01):
        checking every card turns it off, so everyone starts on attack and no
        skill or burst the save doesn't have holds SP; 只看召唤物 needs it on,
        as the costume order then plays the characters' skills unchecked."""
        try:
            done = screen.set_auto_skill(on)
        except ScreenReadError:
            done = False
        # A tap whose effect didn't show leaves the icon's state unknown (a
        # real fight's scenery can hide it), so both modes stop before turn 1.
        if not on and done:
            self._turn_log("已关掉自动技能（右上角菱形），没在存档里的技能不会占 SP")
        elif not on:
            self._stop("关不掉自动技能（右上角菱形），或认不出它的状态：请手动关掉再开始")
        elif done:
            self._turn_log("自动技能（右上角菱形）是开着的，角色照服装顺序放技能")
        else:
            self._stop(
                "打不开自动技能（右上角菱形），或认不出它的状态：只看召唤物时角色要靠它放技能"
            )
        return done

    def _finish(self, screen: GameFightScreen, folder: Path, outcome, last: int, mode: str) -> bool:
        self.info_set("已打回合", len(outcome.turns_played))
        self.info_set("用时", minutes_and_seconds(outcome.seconds))
        if outcome.finished:
            message = (
                f"战斗结束，按存档打了 {len(outcome.turns_played)} 个回合，"
                f"共 {minutes_and_seconds(outcome.seconds)}"
            )
            message += self._damage(screen, folder, outcome, mode)
            self.info_set("状态", message)
            self.log_info(f"魔兽追踪者：{message}", notify=True)
            return True
        if last and outcome.stopped_at is not None and outcome.stopped_at > last:
            message = f"已打到第 {last} 回合，停在第 {outcome.stopped_at} 回合的排位画面"
            self.info_set("状态", message)
            self.log_info(f"魔兽追踪者：{message}", notify=True)
            return True
        where = f"第 {outcome.stopped_at} 回合" if outcome.stopped_at else "开始时"
        return self._stop(f"{where}停下：{outcome.reason}")

    def _damage(self, screen: GameFightScreen, folder: Path, outcome, mode: str) -> str:
        """Total damage from the HP under BATTLE END, kept in the save's 伤害记录.csv
        (Leo 2026-10-01: exact, not estimated)."""
        try:
            hp = screen.boss_hp()
        except ScreenReadError:
            hp = None
        if hp is None:
            return "；总伤害没读准（结算画面的魔兽血量），请看画面"
        left, full = hp
        damage = full - left
        self.info_set("总伤害", f"{damage:,}")
        line = ",".join(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                mode,
                str(len(outcome.turns_played)),
                minutes_and_seconds(outcome.seconds),
                str(damage),
                str(left),
                str(full),
            ]
        )
        path = folder / DAMAGE_FILE
        try:
            new = not path.exists()
            with path.open("a", encoding="utf-8-sig" if new else "utf-8") as file:
                if new:
                    file.write("时间,技能判断,回合数,用时,总伤害,魔兽剩余血量,魔兽总血量\n")
                file.write(line + "\n")
        except OSError as error:
            self.log_info(f"魔兽追踪者：伤害记录写不进 {path}：{error}")
        return f"；总伤害 {damage:,}（魔兽剩 {left:,} / {full:,}）"

    def _card_check(self):
        """Whose saved card a replay checks: everyone's, or only the summons'."""
        if self.config.get("技能判断", CARDS_SUMMONS) == CARDS_ALL:
            return None
        return summons_only(load_game_names().characters.values())

    def _turn_log(self, message: str) -> None:
        self.info_set("当前回合", message)
        self.log_info(f"魔兽追踪者：{message}")

    def _stop(self, reason: str) -> bool:
        self.info_set("停下原因", reason)
        self.info_set("状态", "已停下，排位画面交给你")
        self.log_warning(f"魔兽追踪者自动站位：{reason}", notify=True)
        return False


class FiendHuntRecordTask(FiendHuntTask):
    """魔兽录制, started from the 魔兽追踪者 page (not listed among the tasks)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "魔兽录制"
        self.description = (
            "在「魔兽追踪者」页选存档后按「录制」。每回合自己排好后按录制键（默认 F8），"
            "工具存下这一回合并替你按 BATTLE。"
        )
        self.group_name = None
        self.visible = False  # run from its page, not from a task list
        for key in (
            "模式",
            "存档名称",
            "技能判断",
            "打到第几回合",
            KEEP_OPTION,
            PUSH_OPTION,
        ):
            self.default_config.pop(key, None)
            self.config_description.pop(key, None)
            self.config_type.pop(key, None)
        self.default_config.update({"存档": "", "录制按键": DEFAULT_KEY})
        self.config_description.update(
            {
                "存档": "录到哪个存档文件夹（在「魔兽追踪者」页选或新增）。",
                "录制按键": (
                    "排好一回合后按这个键保存并开打（代替按 BATTLE）。"
                    "可选 F6~F12（不能跟暂停、停止键相同）："
                    "别的键按在游戏上会被当成你接手，工具会停下。"
                ),
            }
        )
        self.config_type.update(
            {"录制按键": {"type": "drop_down", "options": [NO_KEY, *KEY_CHOICES]}}
        )

    def run(self):
        value = str(self.config.get("存档", "") or "").strip()
        folder = Path(value) if value else None
        self.info_set("模式", "录制")
        if folder is None or not valid_save_name(folder.name):
            return self._stop("先在「魔兽追踪者」页选一个存档，或新增一个")
        self.info_set("存档", folder.name)
        return self._record(folder, folder.name)

    def _record(self, folder: Path, name: str) -> bool:
        key = str(self.config.get("录制按键", DEFAULT_KEY))
        if key == NO_KEY:
            return self._stop("录制按键是「无」：先在设置或「魔兽追踪者」页选一个键才能录制")
        key = key if key in KEY_CHOICES else DEFAULT_KEY
        had = len(saved_turns(folder))
        # The character list helps snap names but may lack new costumes and
        # characters; names it lacks are taken once two reads agree.  Each
        # unit's card (攻击/技能n) is read too, about 1-2 s more per key: the
        # screenshot alone can't tell two skills with near-identical icons
        # (克蕾西亚's two costumes, 尤里光盾 T21, 4K PC 2026-10-01), so 全部判断
        # stopped there every time on a save without them.
        screen = GameFightScreen(
            self, known_character_names(), learn_names=True, read_cards=True, log=self._turn_log
        )
        screen.cards_folder = folder / CARDS_FOLDER
        # Leo 2026-10-06: name, then skill name against the character list, so
        # each skill is saved with its costume (the card's row can differ by PC).
        screen.learn_costumes = True
        editing = f"（存档已有 {had} 个回合，重录的回合会覆盖）" if had else ""
        self.info_set("状态", f"录制中：每回合排好后按 {key}（不要按 BATTLE）{editing}")
        # The player plays along while recording: their clicks mustn't stop the task.
        self.player_plays_along = True
        try:
            outcome = record_fight(
                screen,
                HotKey(key_code(key)),
                folder,
                title=name,
                sleep=self.sleep,
                log=self._turn_log,
            )
        except ScreenReadError as error:
            return self._stop(str(error))
        finally:
            self.player_plays_along = False
        saved = sorted(outcome.record.turns)
        unsaved = f"；没存的回合 {list(outcome.unsaved_turns)}" if outcome.unsaved_turns else ""
        message = f"录制{'完成' if outcome.finished else '中断'}：存了 {len(saved)} 个回合{unsaved}"
        if outcome.reason:
            message += f"（{outcome.reason}）"
        self.info_set("状态", message)
        self.info_set("已打回合", len(saved))
        self.log_info(f"魔兽追踪者：{message}", notify=True)
        return outcome.finished
