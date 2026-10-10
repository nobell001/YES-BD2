"""魔兽追踪者: saves on the left, the picked save's turns and settings on the right.

One page for both halves of the feature (Leo 2026-10-06, 魔獸戰 back in the
new window): 开始打 replays the picked save (FiendHuntTask), 录制 records
into it (FiendHuntRecordTask, F8 by default).  A save is a folder under
configs/fiend_hunt with record.json and one screenshot per turn, or only
the player's own planning screenshots.

The record key always saves the turn the game shows (TURN, bottom right):
a new one is added, one recorded before is overwritten (Leo 2026-10-06).
The page stays on what it shows meanwhile.  录制 and 开始打 sit big in the
save's card, not in the page header (Leo 2026-10-06: 放显眼的地方).
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ok import Logger
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.shell import actions, data, motion, theme
from src.ui.shell.page import Page, pill, set_pill
from src.ui.shell.widgets import (
    Button,
    Card,
    IconTile,
    Inset,
    Picture,
    Segmented,
    Separator,
    Text,
    Toggle,
    clear_layout,
    fmt_duration,
    grid_container,
    hbox,
    t,
    tf,
    vbox,
)

logger = Logger.get_logger(__name__)

REPLAY_TASK = "FiendHuntTask"
RECORD_TASK = "FiendHuntRecordTask"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")
THUMB = QSize(208, 117)
THUMBS_KEPT = 96  # shrunk screenshots kept (about 0.4 MB each)
# Leo 2026-10-06: two ways to play, for saves and screenshot folders alike.
# Leo 2026-10-06 (16:52Z): 不调整 first, marked as the steadier pick.
CARD_LABELS = {"summons": "不调整（推荐，较稳定）", "all": "调整服装技能"}
CARD_NOTES = {
    "all": "每个人的技能和爆发都照存档选。开打前：队伍组得跟录的时候一样，服装技能要齐，SP 要够",
    "summons": (
        "先在游戏的「服装顺序设置」排好每个角色的服装顺序！"
        "工具只排出手顺序和站位，召唤物的技能照存档选"
    ),
}
# Leo 2026-10-06: a recorded fight shown as a souseha-style turn chart.
VIEW_LABELS = {"chart": "排轴", "shots": "截图"}


def _fiend():
    """The task module, imported late: the page must open even if it can't load."""
    from src.tasks import FiendHuntTask

    return FiendHuntTask


def _stamp(folder: Path) -> tuple[int, int]:
    """record.json's change time and size: the chart is rebuilt when they change."""
    try:
        info = (folder / "record.json").stat()
    except OSError:
        return (0, 0)
    return (info.st_mtime_ns, info.st_size)


def saves_root() -> Path:
    return _fiend().saves_root()


class SaveInfo:
    def __init__(self, folder: Path):
        from src.tasks.fiend_hunt.saves import RECORD_FILE, saved_turns

        self.folder = folder
        self.name = folder.name
        self.turns = saved_turns(folder) if (folder / RECORD_FILE).is_file() else []
        self.shots = []
        if not self.turns:
            self.shots = sorted(
                path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
            )
        self.mtime = folder.stat().st_mtime
        self.stamp = _stamp(folder)

    @property
    def kind(self) -> str:
        return "record" if self.turns else ("shots" if self.shots else "empty")

    def summary(self) -> str:
        if self.turns:
            return tf("{n} 回合", n=len(self.turns))
        if self.shots:
            return tf("截图 {n} 张", n=len(self.shots))
        return t("还没录")

    def key(self) -> tuple:
        # record.json's stamp too: a turn recorded again keeps its number,
        # team and file name, and the page must still show the new one.
        return (
            self.name,
            self.stamp,
            tuple((turn.turn, turn.team, str(turn.screenshot)) for turn in self.turns),
            tuple(str(path) for path in self.shots),
        )


# folder -> (its stamp, SaveInfo): the page looks every 1.5 s, and reading
# every save's record.json each time grew with the saves (0.4 ms a save).
_infos: dict[Path, tuple[tuple, SaveInfo]] = {}


def list_saves(root: Path) -> list[SaveInfo]:
    """Every folder under ``root``, newest first."""
    if not root.is_dir():
        return []
    saves = []
    seen = set()
    for folder in root.iterdir():
        if folder.is_dir():
            try:
                # A file added or removed changes the folder's time; a record
                # rewritten in place changes its own.
                stamp = (folder.stat().st_mtime_ns, _stamp(folder))
                kept = _infos.get(folder)
                if kept is None or kept[0] != stamp:
                    kept = (stamp, SaveInfo(folder))
                    _infos[folder] = kept
                saves.append(kept[1])
                seen.add(folder)
            except OSError:
                continue
    for gone in [folder for folder in _infos if folder.parent == root and folder not in seen]:
        del _infos[gone]
    saves.sort(key=lambda save: save.mtime, reverse=True)
    return saves


class SaveRow(QWidget):
    """One save in the left list: icon, name, how many turns."""

    def __init__(self, save: SaveInfo, on_click, parent=None):
        super().__init__(parent)
        self.folder = save.folder
        self._selected = False
        self._hover = motion.HoverFade(self, self.update)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        layout = hbox(self, (8, 6, 10, 6), 10)
        icon = {"record": "circle-dot", "shots": "image"}.get(save.kind, "folder-open")
        layout.addWidget(IconTile(icon, 26, 15, kind="fight"))
        layout.addWidget(Text(save.name, "h3", elide=True), 1)
        layout.addWidget(Text(save.summary(), "muted"))
        self.setFixedHeight(40)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click(self.folder)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        hover = self._hover.value
        if not (self._selected or hover > 0):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            theme.color("row_on") if self._selected else theme.color("ink", 0.04 * hover)
        )
        painter.drawRoundedRect(QRectF(self.rect()), theme.corner(5), theme.corner(5))
        if self._selected:
            painter.setBrush(theme.color("row_on_bar"))
            painter.drawRoundedRect(QRectF(0, 8, 3, self.height() - 16), 1.5, 1.5)


def _file_key(path: Path) -> str | None:
    """The file and its stamp: a screenshot recorded again gets a new key."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_mtime_ns}|{stat.st_size}|{path}"


class _Thumbs(QObject):
    """Turn screenshots shrunk to their tile, read off the page's thread and kept.

    A 4K screenshot takes about 0.2 s to read and holds 33 MB as a full
    picture: opening a save, and every record key press, froze the page
    while each turn was read again, and the tiles held them all (a test
    save of 11 4K turns, 2026-10-06: 6.6 s and 371 MB; Leo's fights have
    about 18).  Kept by file and stamp, so only new screenshots are read.
    """

    loaded = Signal(str, QImage)

    def __init__(self) -> None:
        super().__init__()
        self._kept: OrderedDict[str, QPixmap] = OrderedDict()
        self._waiting: dict[str, list[Picture]] = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="魔兽截图缩图")
        self.loaded.connect(self._done)

    def show(self, path: Path, picture: Picture) -> None:
        key = _file_key(path)
        if key is None:
            return
        kept = self._kept.get(key)
        if kept is not None:
            self._kept.move_to_end(key)
            picture.set_pixmap(kept)
            return
        waiting = self._waiting.setdefault(key, [])
        waiting.append(picture)
        if len(waiting) == 1:
            self._pool.submit(self._read, key, str(path))

    def _read(self, key: str, path: str) -> None:
        image = QImage()
        try:
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid():
                box = QSize(THUMB.width() * 2, THUMB.height() * 2)  # sharp on 200 % screens
                reader.setScaledSize(size.scaled(box, Qt.KeepAspectRatio))
            image = reader.read()
        except Exception as exc:  # a picture that can't be read stays blank
            logger.error(f"缩图读不了 {path}", exc)
        self.loaded.emit(key, image)

    def _done(self, key: str, image: QImage) -> None:
        import shiboken6

        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        if not pixmap.isNull():
            self._kept[key] = pixmap
            while len(self._kept) > THUMBS_KEPT:
                self._kept.popitem(last=False)
        for picture in self._waiting.pop(key, []):
            if shiboken6.isValid(picture):
                picture.set_pixmap(pixmap)


_thumbs: _Thumbs | None = None


def thumbs() -> _Thumbs:
    global _thumbs
    if _thumbs is None:
        _thumbs = _Thumbs()
    return _thumbs


class TurnTile(QWidget):
    """A saved turn: its screenshot, T number and team; a click opens the picture.

    The screenshot is shown once the tile is (``load``): the 排轴 view
    doesn't need them.
    """

    def __init__(self, number: int | None, team: int | None, shot: Path | None, page, parent=None):
        super().__init__(parent)
        self.number = number
        self.shot = shot
        self._page = page
        self._loaded = False
        column = vbox(self, (6, 6, 6, 4), 4)
        self.picture = Picture(None, fixed=THUMB, radius=4)
        self.picture.setCursor(Qt.PointingHandCursor)
        self.picture.clicked.connect(self.open_image)
        column.addWidget(self.picture)
        row = hbox(None, (2, 0, 0, 0), 2)
        if number is None:
            label = shot.name if shot else ""
        elif team:
            label = tf("第 {n} 回合 · TEAM{team}", n=number, team=team)
        else:
            label = tf("第 {n} 回合", n=number)
        row.addWidget(Text(label, "muted", elide=True), 1)
        zoom = Button("", "icon", "maximize-2", size="sm", on_click=self.open_image)
        zoom.setToolTip(t("打开原图"))
        zoom.setEnabled(shot is not None)
        zoom.setFixedSize(26, 26)
        row.addWidget(zoom)
        if number is not None:
            bin_button = Button("", "icon", "trash-2", size="sm", on_click=self._delete)
            bin_button.setToolTip(tf("删除第 {n} 回合", n=number))
            bin_button.setFixedSize(26, 26)
            row.addWidget(bin_button)
        column.addLayout(row)
        self.setFixedWidth(THUMB.width() + 12)

    def load(self) -> None:
        if not self._loaded and self.shot is not None:
            self._loaded = True
            thumbs().show(self.shot, self.picture)

    def _delete(self) -> None:
        self._page.delete_turn(self.number)

    def open_image(self) -> None:
        if self.shot is not None and self.shot.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.shot.resolve())))


class FiendPage(Page):
    interval = 1500

    def __init__(self, parent=None):
        super().__init__("shellFiend", "魔兽追踪者", "", parent)
        self.set_sub("在魔兽战的排位画面（BATTLE 显示 TURN）按开始")
        # Leo 2026-10-06: 录制 and 开始 big in the save's card, not top right.
        self.actions_box = QWidget()
        actions_column = vbox(self.actions_box, (0, 2, 0, 0), 8)
        buttons_row = hbox(None, (0, 0, 0, 0), 12)
        self.record_button = Button("开始录制", "secondary", "circle-dot", "lg")
        self.record_button.clicked.connect(lambda *_: self.record_or_stop())
        self.start_button = Button("开始打", "primary", "play", "lg")
        self.start_button.clicked.connect(lambda *_: self.start_replay())
        for button in (self.record_button, self.start_button):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            buttons_row.addWidget(button, 1)
        actions_column.addLayout(buttons_row)
        self.run_note = Text("", "muted", wrap=True)
        actions_column.addWidget(self.run_note)
        self._folder: Path | None = None
        self._rows: dict[str, SaveRow] = {}
        self._list_key: tuple = ()
        self._detail_key: tuple | None = None
        self._tiles: dict[int, TurnTile] = {}
        self._view = "chart"

        columns = hbox(None, (0, 0, 0, 0), 16)
        left = vbox(None, (0, 0, 0, 0), 0)
        self.list_card = Card()
        self.list_card.setFixedWidth(300)
        self.list_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        list_column = vbox(self.list_card, (10, 12, 10, 12), 2)
        head = Text("存档", "eyebrow")
        head.setContentsMargins(8, 0, 8, 6)
        list_column.addWidget(head)
        self.list_layout = vbox(None, (0, 0, 0, 0), 2)
        list_column.addLayout(self.list_layout)
        list_column.addSpacing(8)
        list_column.addWidget(Separator())
        list_column.addSpacing(6)
        buttons = hbox(None, (4, 0, 4, 0), 6)
        buttons.addWidget(Button("新增", "ghost", "plus", size="sm", on_click=self.new_save))
        buttons.addStretch(1)
        folder_button = Button("", "icon", "folder-open", size="sm", on_click=self.open_root)
        folder_button.setToolTip(t("打开存档文件夹"))
        buttons.addWidget(folder_button)
        list_column.addLayout(buttons)
        left.addWidget(self.list_card)
        left.addStretch(1)
        columns.addLayout(left)

        right = vbox(None, (0, 0, 0, 0), 0)
        self.detail = Card()
        self.detail_layout = vbox(self.detail, (22, 20, 22, 20), 14)
        right.addWidget(self.detail)
        right.addStretch(1)
        columns.addLayout(right, 1)
        self.body.addLayout(columns)

        # Leo 2026-10-06: the turns (排轴) take the page's full width under
        # both columns, so the page stays short and the left isn't empty.
        self.turns_card = Card()
        self.turns_layout = vbox(self.turns_card, (22, 18, 22, 20), 12)
        self.turns_card.hide()
        self.body.addWidget(self.turns_card)

        # Leo 2026-10-06: 使用说明 under the turns; open on the first visit.
        self.guide = GuideCard()
        self.body.addWidget(self.guide)
        self.body.addStretch(1)

    # ---------------------------------------------------------------- tasks

    def replay_task(self):
        return data.task_by_class_name(REPLAY_TASK)

    def record_task(self):
        return data.task_by_class_name(RECORD_TASK)

    def _set(self, task, key: str, value) -> None:
        if task is not None:
            task.config[key] = value

    def start_replay(self) -> None:
        task = self.replay_task()
        if self._folder is None or task is None:
            return
        self._set(task, "模式", _fiend().MODE_REPLAY)
        self._set(task, "存档", str(self._folder))
        actions.start(task, self.window())
        self.refresh()

    def record_or_stop(self) -> None:
        task = self.record_task()
        if task is None:
            return
        if task.enabled:
            actions.stop(task)
            self.refresh()
            return
        if task is data.current_task():
            return  # still stopping: 「正在停止…」
        if self._folder is None:
            self.new_save()
            if self._folder is None:
                return
        self._set(task, "存档", str(self._folder))
        actions.start(task, self.window())
        self.refresh()

    # ---------------------------------------------------------------- saves

    def select(self, folder) -> None:
        self._folder = Path(folder) if folder else None
        for task in (self.replay_task(), self.record_task()):
            self._set(task, "存档", str(self._folder) if self._folder else "")
        self.refresh()

    def new_save(self) -> None:
        from src.tasks.fiend_hunt.saves import valid_save_name

        dialog = _TextDialog("新增存档", "例如：10月魔兽", self.window())
        while dialog.exec():
            name = dialog.text()
            if not valid_save_name(name):
                dialog.set_error('名字不能空白，也不能有 \\ / : * ? " < > |')
                continue
            folder = saves_root() / name
            if folder.exists():
                dialog.set_error("已经有这个存档了")
                continue
            folder.mkdir(parents=True)
            self.select(folder)
            return

    def open_root(self) -> None:
        root = saves_root()
        root.mkdir(parents=True, exist_ok=True)
        actions.open_folder(str(root))

    def delete_turn(self, turn: int) -> None:
        from qfluentwidgets import MessageBox

        from src.tasks.fiend_hunt.saves import delete_turn

        folder = self._folder
        if folder is None:
            return
        box = MessageBox(
            tf("删除第 {n} 回合？", n=turn),
            tf(
                "存档「{save}」的第 {n} 回合和它的截图会被删除，不能复原。",
                save=folder.name,
                n=turn,
            ),
            self.window(),
        )
        if box.exec():
            delete_turn(folder, turn)
            self._detail_key = None
            self.refresh()

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        saves = list_saves(saves_root())
        if self._folder is None:
            chosen = str((self.replay_task() or _NoTask).config.get("存档", "") or "")
            if chosen and Path(chosen).is_dir():
                self._folder = Path(chosen)
            elif saves:
                self._folder = saves[0].folder
        # The rows show how many turns: a recording changes them, not only a new name.
        names = tuple((save.name, save.summary()) for save in saves)
        if names != self._list_key:
            self._build_list(saves)
            self._list_key = names
        for key, row in self._rows.items():
            row.set_selected(self._folder is not None and key == self._folder.name)
        save = next((s for s in saves if self._folder and s.folder == self._folder), None)
        if save is None and saves and self._folder is not None and not self._folder.is_dir():
            self._folder = saves[0].folder
            save = saves[0]
        if save is None:
            if self._detail_key != ():
                self._build_empty()
                self._detail_key = ()
        elif save.key() != self._detail_key:
            self._build_detail(save)
            self._detail_key = save.key()
        self._refresh_state(save)
        self.guide.set_open_by_default(not any(s.kind != "empty" for s in saves))

    def _build_list(self, saves: list[SaveInfo]) -> None:
        clear_layout(self.list_layout)
        self._rows = {}
        if not saves:
            empty = Text("还没有存档：按「新增」建一个，再按「录制」", "muted", wrap=True)
            empty.setContentsMargins(8, 4, 8, 4)
            self.list_layout.addWidget(empty)
        for save in saves:
            row = SaveRow(save, self.select)
            self.list_layout.addWidget(row)
            self._rows[save.name] = row

    def _take_actions(self) -> None:
        """Lift the 录制/开始打 buttons out before the card is rebuilt."""
        self.detail_layout.removeWidget(self.actions_box)

    def _build_empty(self) -> None:
        self._take_actions()
        clear_layout(self.detail_layout)
        clear_layout(self.turns_layout)
        self.turns_card.hide()
        self._tiles = {}
        self.detail_layout.addWidget(Text("先建一个存档", "h2"))
        self.detail_layout.addWidget(
            Text("推荐先自己用 F8 录一场，之后回放最快最稳。下面有使用说明。", "sub", wrap=True)
        )
        self.detail_layout.addWidget(self.actions_box)

    def _build_detail(self, save: SaveInfo) -> None:
        # Leo 2026-10-06: a rebuild (a turn saved by F8, an edit) keeps what
        # was on show: the same turn, the same open unit, the same scroll.
        chart = getattr(self, "_chart_box", None)
        same = getattr(self, "_built_folder", None) == save.folder
        self._keep = (
            (chart.shown, chart.opened, chart.folded)
            if same and chart is not None
            else (None, None, None)
        )
        scroll = self.verticalScrollBar().value() if same else 0
        self._built_folder = save.folder
        self._chart_box = None
        self._take_actions()
        clear_layout(self.detail_layout)
        clear_layout(self.turns_layout)
        self._tiles = {}
        head = hbox(None, (0, 0, 0, 0), 12)
        titles = vbox(None, (0, 0, 0, 0), 3)
        titles.addWidget(Text(save.name, "h2"))
        kind = {
            "record": "自己录的存档：照每回合的站位、顺序和技能回放",
            "shots": "只有截图：照截图排位，打完一场自动存成动作档",
            "empty": "还没有回合：在排位画面按「录制」开始录",
        }[save.kind]
        titles.addWidget(Text(kind, "sub", wrap=True))
        head.addLayout(titles, 1)
        self.state_pill = pill()
        head.addWidget(self.state_pill, 0, Qt.AlignTop)
        self.detail_layout.addLayout(head)
        self.detail_layout.addWidget(self.actions_box)

        stats = Inset()
        stats_row = hbox(stats, (16, 12, 16, 12), 24)
        self.stat_turns = self._stat(stats_row, "回合")
        self.stat_last = self._stat(stats_row, "上次用时")
        self.key_box = self._key_picker(stats_row)
        self.detail_layout.addWidget(stats)

        self.detail_layout.addWidget(self._settings(save))

        if save.turns or save.shots:
            line = hbox(None, (0, 4, 0, 0), 8)
            line.addWidget(Text("回合", "h3"))
            line.addStretch(1)
            views = None
            if save.turns:
                views = Segmented(list(VIEW_LABELS), self._view, labels=VIEW_LABELS)
                line.addWidget(views)
            self.turns_layout.addLayout(line)
            tiles = []
            if save.turns:
                for turn in save.turns:
                    tile = TurnTile(turn.turn, turn.team, turn.screenshot, self)
                    self._tiles[turn.turn] = tile
                    tiles.append(tile)
            else:
                tiles = [TurnTile(None, None, shot, self) for shot in save.shots]
            container, grid = grid_container(THUMB.width() + 12, spacing=8)
            for tile in tiles:
                grid.addWidget(tile)
            self.turns_layout.addWidget(container)
            self._shots_box = container
            self._chart_box = None
            if views is not None:
                self._chart_box = self._chart(save)
                self.turns_layout.addWidget(self._chart_box)
                views.changed.connect(self._set_view)
            self._set_view(self._view)
            self.turns_card.show()
        else:
            self.turns_card.hide()
        if scroll:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def _chart(self, save: SaveInfo) -> QWidget:
        from src.tasks.fiend_hunt.chart import build_chart
        from src.tasks.fiend_hunt.saves import load_save
        from src.tasks.fiend_hunt.screen import load_frame
        from src.ui.shell.fiend_chart import ChartView

        record = load_save(save.folder)
        # Reading every turn's screenshot takes a second or more on 4K: the
        # chart's turns are kept while record.json is the same file.
        key = (save.folder, _stamp(save.folder))
        cached = getattr(self, "_chart_cache", None)
        if cached is not None and cached[0] == key:
            turns = cached[1]
        else:
            # Turns unchanged since the last build are kept, so a record key
            # press reads no screenshot but the new turn's.
            if getattr(self, "_kept_turns", (None, None))[0] != save.folder:
                self._kept_turns = (save.folder, {})
            kept = self._kept_turns[1]
            turns = build_chart(record, save.folder, load_frame, kept) if record is not None else []
            self._chart_cache = (key, turns)
        # Leo 2026-10-06: the chart can be adjusted here; 不调整 (只看召唤物)
        # shows only the order and the cells, and the summons' skills.
        shown, opened, folded = getattr(self, "_keep", (None, None, None))
        return ChartView(
            turns,
            self._show_card(),
            record=record,
            save=lambda state, changed: self._save_edit(save.folder, state, changed),
            on_team=lambda team: self.edit_team(save.folder, team),
            shown=shown,
            opened=opened,
            folded=folded,
        )

    def edit_team(self, folder: Path, team: int) -> None:
        """编辑队伍 (Leo 2026-10-06): add or remove characters, team by team."""
        from src.tasks.fiend_hunt.chart import team_members
        from src.tasks.fiend_hunt.record import TurnStateError
        from src.tasks.fiend_hunt.saves import set_team
        from src.ui.shell.fiend_team import edit_teams

        chart = self._chart_box
        if chart is None:
            return
        teams = team_members(list(chart._turns.values()))
        changed = edit_teams(teams, chart.faces, team, self.window())
        if not changed:
            return
        for number, members in sorted(changed.items()):
            try:
                set_team(folder, number, members)
            except (OSError, TurnStateError) as error:
                from qfluentwidgets import InfoBar, InfoBarPosition

                InfoBar.warning(
                    t("没存上"),
                    str(error),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=6000,
                )
                break
        self._detail_key = None
        QTimer.singleShot(0, self.refresh)

    def _save_edit(self, folder: Path, state, changed):
        from src.tasks.fiend_hunt.record import TurnStateError
        from src.tasks.fiend_hunt.saves import edit_turn

        try:
            record = edit_turn(folder, state, changed)
        except (OSError, TurnStateError) as error:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.warning(
                t("没存上"),
                str(error),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            return None
        # The tiles and the list key on the save; the chart already shows the change
        # (its turns were changed in place, so they stay the cached ones).
        self._detail_key = SaveInfo(folder).key()
        cached = getattr(self, "_chart_cache", None)
        if cached is not None and cached[0][0] == folder:
            self._chart_cache = ((folder, _stamp(folder)), cached[1])
        return record

    def _show_card(self):
        """Whose skills the chart shows: everyone's, or the summons' only."""
        fiend = _fiend()
        task = self.replay_task() or _NoTask
        if task.config.get("技能判断", fiend.CARDS_SUMMONS) == fiend.CARDS_ALL:
            return lambda _name: True
        from src.tasks.fiend_hunt.fight import summons_only
        from src.tasks.fiend_hunt.souseha import load_game_names

        return summons_only(load_game_names().characters.values())

    def _show_card_note(self, current: str) -> None:
        self.card_note.set_text(CARD_NOTES[current])
        # Leo 2026-10-06: under 不调整 the player is reminded to set the costume order first.
        colour = theme.color("primary") if current == "summons" else theme.color("ink3")
        self.card_note.setStyleSheet(f"color: {colour.name()};")

    def _cards_changed(self, value: str) -> None:
        """服装技能 switched: the note and the chart change in place (Leo
        2026-10-06: a full rebuild froze the page for seconds)."""
        fiend = _fiend()
        task = self.replay_task()
        self._set(task, "技能判断", value)
        stored = (task or _NoTask).config.get("技能判断", fiend.CARDS_SUMMONS)
        logger.info(f"魔兽追踪者 服装技能 → {value}（已存：{stored == value}）")
        current = "all" if stored == fiend.CARDS_ALL else "summons"
        if stored != value:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.warning(
                t("没切换成"),
                t("设置没存上，请再点一次"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            self.cards_switch.set_value(current)
            return
        self._show_card_note(current)
        QTimer.singleShot(0, self._swap_chart)  # not inside the clicked control's own signal

    def _swap_chart(self) -> None:
        old = self._chart_box
        if old is None or self._folder is None:
            return
        save = SaveInfo(self._folder)
        self._keep = (old.shown, old.opened, old.folded)
        fresh = self._chart(save)
        fresh.setVisible(old.isVisible())
        self.turns_layout.replaceWidget(old, fresh)
        old.setParent(None)
        old.deleteLater()
        self._chart_box = fresh

    def _set_view(self, view: str) -> None:
        self._view = view
        chart = getattr(self, "_chart_box", None)
        shots = getattr(self, "_shots_box", None)
        if chart is not None:
            chart.setVisible(view == "chart")
        if shots is not None:
            shots.setVisible(chart is None or view != "chart")
            if not shots.isHidden():
                for tile in shots.findChildren(TurnTile):
                    tile.load()

    def _key_picker(self, row):
        """录制按键, F6-F12 (Leo 2026-10-06/09), chosen here or in 设置."""
        from qfluentwidgets import ComboBox

        fiend = _fiend()
        column = vbox(None, (0, 0, 0, 0), 4)
        column.addWidget(Text("录制按键", "muted"))
        box = ComboBox()
        box.addItems(list(fiend.KEY_CHOICES))
        key = str((self.record_task() or _NoTask).config.get("录制按键", fiend.DEFAULT_KEY))
        box.setCurrentText(key if key in fiend.KEY_CHOICES else fiend.DEFAULT_KEY)
        box.setFixedWidth(96)
        box.currentTextChanged.connect(self._key_changed)
        column.addWidget(box)
        row.addLayout(column, 1)
        return box

    def _key_changed(self, key: str) -> None:
        from src.ui.shell import hotkeys

        task = self.record_task()
        if task is None:
            self._set(task, "录制按键", key)
        else:
            # Swaps with the pause/stop key if one of them had it.
            hotkeys.set_key(hotkeys.RECORD, key, task)
        QTimer.singleShot(0, self.refresh)  # the note under the buttons names the key

    @staticmethod
    def _stat(row, label: str) -> Text:
        column = vbox(None, (0, 0, 0, 0), 4)
        column.addWidget(Text(label, "muted"))
        value = Text("-", "h3")
        column.addWidget(value)
        row.addLayout(column, 1)
        return value

    def _settings(self, save: SaveInfo) -> QWidget:
        fiend = _fiend()
        task = self.replay_task() or _NoTask
        box = Inset()
        column = vbox(box, (16, 10, 16, 10), 10)

        row = hbox(None, (0, 0, 0, 0), 12)
        row.addWidget(Text("服装技能", "h3"))
        row.addStretch(1)
        values = {"summons": fiend.CARDS_SUMMONS, "all": fiend.CARDS_ALL}
        current = (
            "all"
            if task.config.get("技能判断", fiend.CARDS_SUMMONS) == fiend.CARDS_ALL
            else "summons"
        )
        cards = Segmented(list(CARD_LABELS), current, labels=CARD_LABELS, accent=True)
        cards.changed.connect(lambda key: self._cards_changed(values[key]))
        self.cards_switch = cards
        row.addWidget(cards)
        column.addLayout(row)
        self.card_note = Text("", "body", wrap=True)
        self._show_card_note(current)
        column.addWidget(self.card_note)

        row = hbox(None, (0, 0, 0, 0), 12)
        row.addWidget(Text("打到第几回合就停", "h3"))
        row.addStretch(1)
        from qfluentwidgets import SpinBox

        stop = SpinBox()
        stop.setRange(0, 99)
        stop.setSingleStep(2)
        stop.setValue(int(task.config.get("打到第几回合", 0) or 0))
        stop.setSpecialValueText(t("打完"))
        stop.valueChanged.connect(
            lambda value: self._set(self.replay_task(), "打到第几回合", value)
        )
        row.addWidget(stop)
        column.addLayout(row)

        # Leo 2026-10-06: off by default, few bosses move anyone.
        row = hbox(None, (0, 0, 0, 0), 12)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text("魔兽会推动角色位置", "h3"))
        texts.addWidget(Text("勾了每回合逐个确认站位，较慢", "muted"))
        row.addLayout(texts, 1)
        pushes = Toggle(bool(task.config.get(fiend.PUSH_OPTION, False)))
        pushes.toggled.connect(
            lambda on: self._set(self.replay_task(), fiend.PUSH_OPTION, bool(on))
        )
        self.push_switch = pushes
        row.addWidget(pushes)
        column.addLayout(row)

        if save.kind != "shots":
            return box  # the keep option only matters to a folder of screenshots
        row = hbox(None, (0, 0, 0, 0), 12)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text("只有截图时，打完存一份动作档", "h3"))
        texts.addWidget(Text("下次照它回放，更快更稳", "muted"))
        row.addLayout(texts, 1)
        keep = Toggle(bool(task.config.get(fiend.KEEP_OPTION, True)))
        keep.toggled.connect(lambda on: self._set(self.replay_task(), fiend.KEEP_OPTION, bool(on)))
        row.addWidget(keep)
        column.addLayout(row)
        return box

    def _refresh_state(self, save: SaveInfo | None) -> None:
        replay, record = self.replay_task(), self.record_task()
        recording = bool(getattr(record, "enabled", False))
        replaying = bool(getattr(replay, "enabled", False))
        # Leo 2026-10-10: 停止录制 shows at once; the recording ends its step.
        stopping = record is not None and not recording and record is data.current_task()
        if stopping:
            self.record_button.set_label("正在停止…")
            self.record_button.set_icon_name("loader-circle")
        else:
            self.record_button.set_label("停止录制" if recording else "开始录制")
            self.record_button.set_icon_name("square" if recording else "circle-dot")
        self.record_button.set_kind("danger" if recording or stopping else "secondary")
        self.record_button.setEnabled(not stopping and (recording or actions.can_start()))
        self.start_button.setEnabled(
            save is not None and save.kind != "empty" and actions.can_start()
        )
        key = str((record or _NoTask).config.get("录制按键", "F8") or "F8")
        info = getattr(record if recording else replay, "info", None) or {}
        if recording:
            note = str(info.get("当前回合", "") or info.get("状态", "") or "")
            note = note or tf("录制中：每回合排好后按 {key}，工具照右下角的回合数存", key=key)
        elif replaying:
            note = str(info.get("状态", "") or "")
        else:
            note = tf(
                "录制：每回合排好后按 {key}，照右下角的回合数自动新增（录过的回合会覆盖）",
                key=key,
            )
        self.run_note.set_text(note)
        if save is None:
            return
        self.stat_turns.set_text(str(len(save.turns) or len(save.shots) or "-"))
        last = data.last_run(getattr(replay, "name", "")) or {}
        self.stat_last.set_text(fmt_duration(last["duration"]) if last.get("duration") else "-")
        self.key_box.setEnabled(not recording)  # read when recording starts
        if self.key_box.currentText() != key:
            self.key_box.blockSignals(True)
            self.key_box.setCurrentText(key)
            self.key_box.blockSignals(False)
        if recording:
            set_pill(self.state_pill, "录制中", "run")
        elif replaying:
            set_pill(self.state_pill, "回放中", "run")
        else:
            set_pill(self.state_pill, "")


class _NoTask:
    config: dict = {}
    name = ""


class GuideCard(Card):
    """使用说明: five steps, an icon and a line each, and one game picture of
    where the record key is pressed (Leo 2026-10-06: the old three-picture
    how-to had too much text).  Open the first time the page is shown and
    while there's no save; folded otherwise."""

    SEEN_KEY = "fiend"

    STEPS = (
        ("plus", "新增存档", "取个名字，例如 10月魔兽"),
        ("circle-dot", "按「开始录制」", "在游戏的魔兽战排位画面，先按工具上的「开始录制」"),
        ("gamepad-2", "每回合按 F8", "每回合排好后按录制按键（默认 F8），不用按 BATTLE"),
        ("play", "开始打", "打的时候不要动鼠标和键盘"),
        ("rotate-ccw", "被中断了？", "在任一回合的排位画面再点「开始打」，接着打，不用从头"),
    )
    PICTURE = "fiend_f8.jpg"

    def __init__(self, parent=None):
        super().__init__(parent)
        column = vbox(self, (22, 14, 22, 14), 12)
        head = hbox(None, (0, 0, 0, 0), 10)
        head.addWidget(IconTile("book-open", 26, 15))
        head.addWidget(Text("使用说明", "h3"), 1)
        self.toggle_button = Button(
            "展开", "ghost", "chevron-down", size="sm", on_click=self.toggle
        )
        head.addWidget(self.toggle_button)
        column.addLayout(head)
        self.content = QWidget()
        body = hbox(self.content, (0, 0, 0, 0), 20)
        steps = vbox(None, (0, 0, 0, 0), 14)
        for number, (icon, title, text) in enumerate(self.STEPS, 1):
            row = hbox(None, (0, 0, 0, 0), 12)
            row.addWidget(IconTile(icon, 34, 18), 0, Qt.AlignTop)
            texts = vbox(None, (0, 0, 0, 0), 2)
            texts.addWidget(Text(f"{number}. {t(title)}", "h3"))
            texts.addWidget(Text(text, "guide", wrap=True))
            row.addLayout(texts, 1)
            steps.addLayout(row)
        steps.addStretch(1)
        body.addLayout(steps, 1)
        folder = Path(__file__).resolve().parents[1] / "guide"
        picture = vbox(None, (0, 0, 0, 0), 6)
        picture.addWidget(Picture(str(folder / self.PICTURE), fixed=QSize(432, 243), radius=6))
        picture.addWidget(Text("排好这回合后，在这个画面按 F8", "muted"), 0, Qt.AlignHCenter)
        body.addLayout(picture)
        column.addWidget(self.content)
        self.content.hide()
        self._touched = False

    def showEvent(self, event):
        super().showEvent(event)
        from src.ui.shell import guide_page

        if not guide_page.seen(self.SEEN_KEY):
            guide_page.mark_seen(self.SEEN_KEY)
            self._touched = True  # stays open until the player folds it
            self._show(True)

    def toggle(self) -> None:
        self._touched = True
        self._show(not self.content.isVisible())

    def _show(self, shown: bool) -> None:
        self.content.setVisible(shown)
        self.toggle_button.setText(t("收起" if shown else "展开"))

    def set_open_by_default(self, shown: bool) -> None:
        if not self._touched and self.content.isVisible() != shown:
            self._show(shown)


class _TextDialog:
    """A one-line question (new save name, chart link)."""

    def __init__(self, title: str, placeholder: str, parent):
        from qfluentwidgets import CaptionLabel, LineEdit, MessageBoxBase, SubtitleLabel

        self.box = MessageBoxBase(parent)
        self.box.viewLayout.addWidget(SubtitleLabel(t(title), self.box))
        self.edit = LineEdit(self.box)
        self.edit.setPlaceholderText(t(placeholder))
        self.edit.setClearButtonEnabled(True)
        self.box.viewLayout.addWidget(self.edit)
        self.error = CaptionLabel("", self.box)
        self.box.viewLayout.addWidget(self.error)
        self.box.yesButton.setText(t("确定"))
        self.box.cancelButton.setText(t("取消"))
        self.box.widget.setMinimumWidth(380)

    def exec(self) -> bool:
        return bool(self.box.exec())

    def text(self) -> str:
        return self.edit.text().strip()

    def set_error(self, text: str) -> None:
        self.error.setText(t(text))
