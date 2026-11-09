"""render_shell.py with the real Windows font engine (DirectWrite), never
showing a window: same arguments, run on Windows.

    set QT_SCALE_FACTOR=1.25
    python tools/dev/render_shell_hidden.py <out dir> <language> [WxH]

The offscreen platform used by render_shell.py has no Windows fonts, so text
widths differ from a player's screen by a few px and 1 px cuts can't be
judged (2026-11-09).  Here every top-level window gets WA_DontShowOnScreen
before it is shown: it is laid out and painted like a real one, but nothing
appears on the desktop.
"""

import os
import runpy
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_show = QWidget.show
_set_visible = QWidget.setVisible


def _hide_window(widget: QWidget) -> None:
    if not widget.isWindow():
        return
    # Second layer: even if a window reaches the desktop (2026-11-09: the
    # main window still appeared once), it is fully see-through, takes no
    # clicks and never takes focus.  grab() paints it all the same.
    widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
    if widget.windowOpacity() != 0.0:
        widget.setWindowOpacity(0.0)
    if not widget.testAttribute(Qt.WA_DontShowOnScreen):
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)


def _wrap(original):
    def shown(self, *args):
        _hide_window(self)
        return original(self, *args)

    return shown


def set_visible(self, visible):
    if visible:
        _hide_window(self)
    return _set_visible(self, visible)


QWidget.show = _wrap(_show)
QWidget.setVisible = set_visible
for _name in ("showNormal", "showMaximized", "showMinimized", "showFullScreen", "raise_"):
    setattr(QWidget, _name, _wrap(getattr(QWidget, _name)))


def _hidden(original):
    def call(self, *args, **kwargs):
        _hide_window(self)
        return original(self, *args, **kwargs)

    return call


# ok's MainWindow opens with showNormal() (2026-11-09 a first try flashed it).
for _name in ("showNormal", "showMaximized", "showFullScreen", "showMinimized"):
    setattr(QWidget, _name, _hidden(getattr(QWidget, _name)))


class _Hider(QObject):
    """Backup for windows shown from C++ (menus, tooltips, exec())."""

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Polish, QEvent.Show, QEvent.WinIdChange) and isinstance(
            watched, QWidget
        ):
            _hide_window(watched)
        return False


_original_init = QApplication.__init__


def _init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self._hider = _Hider()
    self.installEventFilter(self._hider)
    # Third layer: every 50 ms, any top-level window that is up is made
    # see-through at once.
    from PySide6.QtCore import QTimer

    self._sweep = QTimer()
    self._sweep.timeout.connect(lambda: [_hide_window(w) for w in self.topLevelWidgets()])
    self._sweep.start(50)


QApplication.__init__ = _init

here = os.path.dirname(os.path.abspath(__file__))
sys.argv = [os.path.join(here, "render_shell.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
