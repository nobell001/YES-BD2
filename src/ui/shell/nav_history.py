"""上一页 / 下一页, like a browser (Leo 2026-10-10).

The mouse's side buttons, Alt+← / Alt+→ and the keyboard's own Back /
Forward keys go back and forward through the pages opened in this window.
Only while the tool's window is in front: these are not global hotkeys, so
the game never sees them.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut

MAX_STEPS = 50


class History:
    """Pages visited, with a cursor: back and forward like a browser."""

    def __init__(self):
        self.back: list[str] = []
        self.forward: list[str] = []
        self.current: str | None = None
        # Pages a back/forward step is switching to; the switch animation
        # can report them late, after the next step already moved on.
        self._pending: list[str] = []

    def arrived(self, key: str) -> None:
        """A page was shown: a new step, unless a back/forward step opened it."""
        if key in self._pending:
            del self._pending[: self._pending.index(key) + 1]
            return
        self._pending.clear()
        self.visit(key)

    def visit(self, key: str) -> None:
        if key == self.current:
            return
        if self.current is not None:
            self.back.append(self.current)
            del self.back[:-MAX_STEPS]
        self.forward.clear()
        self.current = key

    def go_back(self) -> str | None:
        if not self.back:
            return None
        self.forward.append(self.current)
        self.current = self.back.pop()
        self._pending.append(self.current)
        return self.current

    def go_forward(self) -> str | None:
        if not self.forward:
            return None
        self.back.append(self.current)
        self.current = self.forward.pop()
        self._pending.append(self.current)
        return self.current


class BackForward(QObject):
    """Wires the inputs on ``window`` to ``back`` / ``forward``.

    Mouse presses a widget does not use travel up to the window, so one
    filter on the window sees the side buttons anywhere in it without an
    application-wide filter (those slowed every repaint, see install.py).
    """

    def __init__(self, window, back: Callable[[], None], forward: Callable[[], None]):
        super().__init__(window)
        self._back = back
        self._forward = forward
        window.installEventFilter(self)
        self.shortcuts = []
        for keys, action in (
            (QKeySequence(Qt.ALT | Qt.Key_Left), back),
            (QKeySequence(Qt.ALT | Qt.Key_Right), forward),
            (QKeySequence(Qt.Key_Back), back),
            (QKeySequence(Qt.Key_Forward), forward),
        ):
            shortcut = QShortcut(keys, window)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            button = event.button()
            if button == Qt.BackButton:
                self._back()
                return True
            if button == Qt.ForwardButton:
                self._forward()
                return True
        return False
