"""编辑队伍: add and remove a save's characters, team by team (Leo 2026-10-06,
after souseha's team editor, not a copy of it).

TEAM1/2/3 along the top; under them the team's members, then a search box,
star and element filters and every character of the built-in list.  A click
on a character adds it to the team (a click on a member, or its ×, takes it
out); one in another team can't be added (Leo 2026-10-06).  Nothing is
saved until 确定; the page then gives each changed team its new members
(saves.set_team).

The character tiles are built once; filters hide them and a click only
redraws the tiles it changes (Leo 2026-10-06: the editor lagged).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QWidget

from src.tasks.fiend_hunt import costumes
from src.ui.shell import icons, theme
from src.ui.shell.fiend_chart import _face, costume_pixmap
from src.ui.shell.widgets import (
    Button,
    Segmented,
    Text,
    clear_layout,
    grid_container,
    hbox,
    shell_buttons,
    t,
    tf,
    vbox,
)

TEAMS = 3
MAX_CHARACTERS = 5  # a BD2 team; summons don't count
ELEMENTS = (
    ("fire", "flame", "#E0653A"),
    ("water", "droplet", "#3D8FE0"),
    ("wind", "wind", "#3BAF6A"),
    ("light", "sun", "#D9A520"),
    ("dark", "moon", "#9A5BD6"),
)
STARS = {"all": "全部", "5": "5★", "4": "4★", "3": "3★"}


def _picture(name: str, faces: dict[str, QPixmap]) -> QPixmap:
    """The list's portrait (sharp), else the face cut from the save's screenshots."""
    character = _character(name)
    if character is not None and character.costume:
        pixmap = costume_pixmap(character.costume)
        if not pixmap.isNull():
            return pixmap
    return faces.get(name, QPixmap())


def _back(element: str) -> QColor:
    """A soft wash of the character's element behind its see-through portrait."""
    colour = dict((key, colour) for key, _icon, colour in ELEMENTS).get(element)
    if colour is None:
        return theme.color("ink", 0.08)
    back = QColor(colour)
    back.setAlphaF(0.28)
    return back


def _character(name: str):
    return _by_name().get(name)


@lru_cache(maxsize=1)
def _by_name() -> dict:
    return {character.name: character for character in costumes.book().characters}


class MemberSlot(QAbstractButton):
    """One place in the team: a portrait with its name and a ×, or empty."""

    SIZE = 88

    def __init__(self, name: str | None, pixmap: QPixmap, on_remove: Callable[[str], None]):
        super().__init__()
        self.name = name
        self._pixmap = pixmap
        self._hover = False
        self.setFixedSize(self.SIZE, self.SIZE + 22)
        if name:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(tf("把 {name} 移出队伍", name=t(name)))
            self.clicked.connect(lambda: on_remove(name))

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.SIZE - 2, self.SIZE - 2)
        if not self.name:
            painter.setPen(QPen(theme.color("ink", 0.18), 1.2, Qt.DashLine))
            painter.setBrush(theme.color("ink", 0.03))
            painter.drawRoundedRect(rect, 10, 10)
            plus = icons.pixmap("plus", theme.color("ink3"), 20)
            ratio = plus.devicePixelRatio() or 1
            painter.drawPixmap(
                round(rect.center().x() - plus.width() / ratio / 2),
                round(rect.center().y() - plus.height() / ratio / 2),
                plus,
            )
            return
        character = _character(self.name)
        _face(painter, rect, self._pixmap, 10, False, _back(character.element if character else ""))
        painter.setPen(QPen(theme.color("primary"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)
        # the ×, top right
        cross = QRectF(self.SIZE - 24, 4, 20, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("bad") if self._hover else QColor(0, 0, 0, 120))
        painter.drawEllipse(cross)
        mark = icons.pixmap("x", QColor("white"), 14, 2.4)
        ratio = mark.devicePixelRatio() or 1
        painter.drawPixmap(
            round(cross.center().x() - mark.width() / ratio / 2),
            round(cross.center().y() - mark.height() / ratio / 2),
            mark,
        )
        font = QFont(painter.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(theme.color("ink"))
        painter.drawText(
            QRectF(-6, self.SIZE + 2, self.SIZE + 12, 18),
            Qt.AlignCenter,
            painter.fontMetrics().elidedText(t(self.name), Qt.ElideRight, self.SIZE + 12),
        )


class CharacterTile(QAbstractButton):
    """A character to add: portrait, name and an element dot; in-team ones ticked."""

    SIZE = 76

    def __init__(self, character, pixmap: QPixmap, chosen: bool, on_click: Callable[[str], None]):
        super().__init__()
        self.character = character
        self._pixmap = pixmap
        self.chosen = chosen
        self.taken: int | None = None  # the other team it is in
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.SIZE, self.SIZE + 20)
        self.setToolTip(t(character.name))
        self.clicked.connect(lambda: on_click(character.name))

    def set_state(self, chosen: bool, taken: int | None) -> None:
        if (chosen, taken) != (self.chosen, self.taken):
            self.chosen, self.taken = chosen, taken
            self.setToolTip(
                tf("{name}（已在 TEAM{n}）", name=t(self.character.name), n=taken)
                if taken
                else t(self.character.name)
            )
            self.setCursor(Qt.ForbiddenCursor if taken else Qt.PointingHandCursor)
            self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(2, 2, self.SIZE - 4, self.SIZE - 4)
        dim = self.chosen or self.taken is not None
        _face(painter, rect, self._pixmap, 8, dim, _back(self.character.element))
        if self.taken is not None:
            painter.save()
            font = QFont(painter.font())
            font.setPixelSize(12)
            theme.strong(font, digits=True)
            painter.setFont(font)
            painter.setPen(QColor("white"))
            painter.drawText(rect, Qt.AlignCenter, f"TEAM{self.taken}")
            painter.restore()
        elif self.chosen or self._hover:
            painter.setPen(QPen(theme.color("primary"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 8, 8)
        if self.chosen:
            tick = icons.pixmap("check", QColor("white"), 26, 2.6)
            ratio = tick.devicePixelRatio() or 1
            painter.drawPixmap(
                round(rect.center().x() - tick.width() / ratio / 2),
                round(rect.center().y() - tick.height() / ratio / 2),
                tick,
            )
        colour = dict((key, colour) for key, _icon, colour in ELEMENTS).get(self.character.element)
        if colour:
            painter.setPen(QPen(theme.color("card"), 1.5))
            painter.setBrush(QColor(colour))
            painter.drawEllipse(QRectF(rect.left() + 4, rect.top() + 4, 10, 10))
        font = QFont(painter.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(theme.color("ink2") if dim else theme.color("ink"))
        painter.drawText(
            QRectF(-4, self.SIZE, self.SIZE + 8, 18),
            Qt.AlignCenter,
            painter.fontMetrics().elidedText(t(self.character.name), Qt.ElideRight, self.SIZE + 8),
        )


class ElementChip(QAbstractButton):
    """An element filter: its icon in its colour, on a soft disc when on."""

    def __init__(self, key: str, icon_name: str, colour: str, on_toggle: Callable[[], None]):
        super().__init__()
        self.key = key
        self._icon = icon_name
        self._colour = QColor(colour)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 34)
        self.setToolTip(
            t({"fire": "火", "water": "水", "wind": "风", "light": "光", "dark": "暗"}[key])
        )
        self.toggled.connect(lambda _on: on_toggle())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, 32, 32)
        if self.isChecked():
            soft = QColor(self._colour)
            soft.setAlphaF(0.2)
            painter.setPen(QPen(self._colour, 1.4))
            painter.setBrush(soft)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("ink", 0.05))
        painter.drawEllipse(rect)
        mark = icons.pixmap(self._icon, self._colour, 18)
        ratio = mark.devicePixelRatio() or 1
        painter.drawPixmap(
            round(17 - mark.width() / ratio / 2), round(17 - mark.height() / ratio / 2), mark
        )


class TeamEditor(QWidget):
    """The dialog's body; ``members`` holds each team's list as edited."""

    def __init__(
        self, teams: dict[int, list[str]], faces: dict[str, QPixmap], team: int, parent=None
    ):
        super().__init__(parent)
        self.saved = {number: list(names) for number, names in teams.items()}
        self.members = {number: list(names) for number, names in teams.items()}
        self.faces = faces
        self.team = team if team in teams else min(teams)
        self.setMinimumWidth(820)
        column = vbox(self, (0, 0, 0, 0), 14)

        top = hbox(None, (0, 0, 0, 0), 12)
        top.addWidget(Text("编辑队伍", "h2"))
        top.addStretch(1)
        options = [str(number) for number in range(1, max(TEAMS, max(teams)) + 1)]
        self.tabs = Segmented(options, str(self.team), labels={o: f"TEAM{o}" for o in options})
        for option, button in self.tabs._buttons.items():
            if int(option) not in teams:
                button.setEnabled(False)
                button.setToolTip(tf("还没有录到 TEAM{n} 的回合", n=option))
        self.tabs.changed.connect(lambda value: self._show_team(int(value)))
        top.addWidget(self.tabs)
        column.addLayout(top)

        self.slots_box = QWidget()
        self.slots_box.setObjectName("teamSlots")
        soft = theme.color("ink", 0.04)
        self.slots_box.setStyleSheet(
            "QWidget#teamSlots { background: rgba(%d, %d, %d, %d); border-radius: 12px; }"
            % (soft.red(), soft.green(), soft.blue(), soft.alpha())
        )
        slots_column = vbox(self.slots_box, (16, 12, 16, 12), 8)
        line = hbox(None, (0, 0, 0, 0), 8)
        self.count = Text("", "muted")
        line.addWidget(self.count, 1)
        line.addWidget(Button("还原", "ghost", "rotate-ccw", size="sm", on_click=self._reset))
        slots_column.addLayout(line)
        self.slots = hbox(None, (0, 0, 0, 0), 12)
        slots_column.addLayout(self.slots)
        column.addWidget(self.slots_box)

        filters = hbox(None, (0, 0, 0, 0), 10)
        from qfluentwidgets import SearchLineEdit

        self.search = SearchLineEdit()
        self.search.setPlaceholderText(t("搜索角色名（中文或英文）"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(lambda _text: self._filter())
        filters.addWidget(self.search)
        filters.addStretch(1)
        self.stars = Segmented(list(STARS), "all", labels=STARS)
        self.stars.changed.connect(lambda _value: self._filter())
        filters.addWidget(self.stars)
        self.elements = [
            ElementChip(key, icon, colour, self._filter) for key, icon, colour in ELEMENTS
        ]
        for chip in self.elements:
            filters.addWidget(chip)
        column.addLayout(filters)

        from qfluentwidgets import ScrollArea

        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(ScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.scroll.setMinimumHeight(330)
        self.grid_holder = QWidget()
        self.grid_holder.setStyleSheet("background: transparent;")
        self.grid_column = vbox(self.grid_holder, (0, 0, 8, 0), 0)
        self.tiles: list[CharacterTile] = []
        self.groups: dict[int, QWidget] = {}
        self._build_grid()
        self.scroll.setWidget(self.grid_holder)
        column.addWidget(self.scroll, 1)
        self._show_team(self.team)

    # ---------------------------------------------------------------- state

    def changed_teams(self) -> dict[int, list[str]]:
        return {
            number: names
            for number, names in self.members.items()
            if names != self.saved.get(number)
        }

    def _characters_in(self, names: list[str]) -> int:
        return sum(1 for name in names if _character(name) is not None)

    def taken(self) -> dict[str, int]:
        """The characters in the other teams, by team (Leo 2026-10-06: one
        character can't be in two teams)."""
        return {
            name: number
            for number, names in self.members.items()
            if number != self.team
            for name in names
            if _character(name) is not None
        }

    def _show_team(self, team: int) -> None:
        self.team = team
        self._fill_slots()
        self._mark_tiles()

    def _reset(self) -> None:
        self.members[self.team] = list(self.saved[self.team])
        self._show_team(self.team)

    def remove(self, name: str) -> None:
        names = self.members[self.team]
        if name in names and len(names) > 1:
            names.remove(name)
            self._show_team(self.team)

    def toggle(self, name: str) -> None:
        names = self.members[self.team]
        if name in names:
            self.remove(name)
            return
        elsewhere = self.taken().get(name)
        if elsewhere is not None:
            self.count.set_text(
                tf("{name} 已在 TEAM{n}：先从那一队移出", name=t(name), n=elsewhere)
            )
            return
        if self._characters_in(names) >= MAX_CHARACTERS:
            self.count.set_text(tf("一队最多 {n} 个角色：先移出一个", n=MAX_CHARACTERS))
            return
        names.append(name)
        self._show_team(self.team)

    # ---------------------------------------------------------------- drawing

    def _fill_slots(self) -> None:
        clear_layout(self.slots)
        names = self.members[self.team]
        for name in names:
            self.slots.addWidget(MemberSlot(name, _picture(name, self.faces), self.remove))
        for _ in range(max(0, MAX_CHARACTERS - self._characters_in(names))):
            self.slots.addWidget(MemberSlot(None, QPixmap(), self.remove))
        self.slots.addStretch(1)
        self.count.set_text(
            tf(
                "TEAM{team} · {n}/{max} 个角色 · 点头像移出，点下面的角色加入",
                team=self.team,
                n=self._characters_in(names),
                max=MAX_CHARACTERS,
            )
        )

    def _matches(self, character) -> bool:
        text = self.search.text().strip().lower()
        star = self.stars.value() or "all"
        elements = {chip.key for chip in self.elements if chip.isChecked()}
        if star != "all" and character.star != int(star):
            return False
        if elements and character.element not in elements:
            return False
        return not text or any(
            text in (value or "").lower() for value in (character.name, *character.names.values())
        )

    def _shown(self) -> list:
        return [tile.character for tile in self.tiles if self._matches(tile.character)]

    def _build_grid(self) -> None:
        """Every character of the list, once, by star."""
        characters = costumes.book().characters
        for star in sorted({c.star for c in characters}, reverse=True):
            group = QWidget()
            group_column = vbox(group, (0, 0, 0, 0), 0)
            head = hbox(None, (2, 8, 0, 6), 8)
            head.addWidget(Text(f"{star}★", "h3"))
            head.addStretch(1)
            group_column.addLayout(head)
            container, grid = grid_container(CharacterTile.SIZE, spacing=10)
            for character in (c for c in characters if c.star == star):
                tile = CharacterTile(
                    character, costume_pixmap(character.costume), False, self.toggle
                )
                grid.addWidget(tile)
                self.tiles.append(tile)
            group_column.addWidget(container)
            self.grid_column.addWidget(group)
            self.groups[star] = group
        self.none = Text("没有符合的角色", "muted")
        self.none.hide()
        self.grid_column.addWidget(self.none)
        self.grid_column.addStretch(1)

    def _filter(self) -> None:
        shown = {star: False for star in self.groups}
        wanted = {}
        for tile in self.tiles:
            wanted[tile] = self._matches(tile.character)
            shown[tile.character.star] |= wanted[tile]
        # Tiles change inside hidden groups: one layout pass per group, not per tile.
        for group in self.groups.values():
            group.hide()
        for tile, match in wanted.items():
            if tile.isHidden() == match:
                tile.setHidden(not match)
        for star, group in self.groups.items():
            group.setHidden(not shown[star])
        self.none.setHidden(any(shown.values()))

    def _mark_tiles(self) -> None:
        names = set(self.members[self.team])
        taken = self.taken()
        for tile in self.tiles:
            name = tile.character.name
            tile.set_state(name in names, taken.get(name))


def edit_teams(
    teams: dict[int, list[str]], faces: dict[str, QPixmap], team: int, parent
) -> dict[int, list[str]] | None:
    """Show the editor; the teams whose members changed, or None if cancelled."""
    from qfluentwidgets import MessageBoxBase

    box = MessageBoxBase(parent)
    editor = TeamEditor(teams, faces, team, box)
    box.viewLayout.addWidget(editor)
    box.yesButton.setText(t("确定"))
    box.cancelButton.setText(t("取消"))
    shell_buttons(box)
    if not box.exec():
        return None
    return editor.changed_teams()
