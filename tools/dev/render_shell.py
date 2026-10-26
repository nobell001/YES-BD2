"""Open the whole tool offscreen (no game) and save every page and dialog as
PNGs, in light and dark (layout check across languages and Windows scaling).

    QT_SCALE_FACTOR=1.25 python tools/dev/render_shell.py <out dir> <language> [WxH]

<language> is zh_CN, zh_TW, en_US, ja_JP or ko_KR.  QT_SCALE_FACTOR stands in
for Windows' 125 % / 150 % / 200 %.  Writes configs/ui_config.json (ignored by
git) with the language before the app starts; run it from the repo root.
Files: <out dir>/<theme>-<page>.png, then the dialogs as <theme>-dlg-<name>.png.
Each dialog is also driven the way a player would (add a row, show a message)
and drawn again as <theme>-dlg-<name>-<step>.png.  fit.jsonl lists what
tests/ui_fit_audit.problems() finds after each one, with only events
processed: nothing here places or resizes a window by hand.
"""

import json
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WINDIR", "/nonexistent-windir")  # ok-script looks for Windows fonts
root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "tests"))
os.chdir(root)

out = os.path.abspath(sys.argv[1])
language = sys.argv[2] if len(sys.argv) > 2 else "zh_CN"
size = sys.argv[3] if len(sys.argv) > 3 else "1200x800"
width, height = (int(part) for part in size.split("x"))
os.makedirs(out, exist_ok=True)
os.makedirs("configs", exist_ok=True)
ui_config = os.path.join("configs", "ui_config.json")
try:
    with open(ui_config, encoding="utf-8") as file:
        saved = json.load(file)
except (OSError, ValueError):
    saved = {}
saved.setdefault("MainWindow", {})["Language"] = language
with open(ui_config, "w", encoding="utf-8") as file:
    json.dump(saved, file)

import ok  # noqa: E402
import ok.core.screenshot  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from src.config import config  # noqa: E402

config["check_mutex"] = False
# The screenshot overlay needs Windows fonts; nothing here takes screenshots.
ok.core.screenshot.Screenshot = lambda *_args, **_kwargs: None
# Offscreen windows have no native handle until shown.
type(ok.og).set_dpi_scaling = lambda self, window: None


def settle(rounds: int = 8) -> None:
    for _ in range(rounds):
        QApplication.processEvents()


def wait(ms: int) -> None:
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def save(widget: QWidget, name: str) -> None:
    widget.grab().save(os.path.join(out, name + ".png"))
    print("saved", name, flush=True)


def _visible(widget: QWidget, root: QWidget) -> bool:
    return widget.isVisibleTo(root)


def audit(root: QWidget, name: str) -> None:
    """Note text that does not fit and widgets that stick out of their parent
    (one JSON line per problem in <out dir>/audit.jsonl)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QLabel, QStackedWidget

    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not _visible(widget, root):
            continue
        where = widget.mapTo(root, widget.rect().topLeft())
        item = {"class": type(widget).__name__, "x": where.x(), "y": where.y(),
                "w": widget.width(), "h": widget.height()}
        if isinstance(widget, QLabel) and widget.text() and widget.textFormat() != Qt.RichText:
            metrics = QFontMetrics(widget.font())
            text = widget.text()
            room = widget.contentsRect()
            full = getattr(widget, "full_text", lambda: text)()
            if widget.wordWrap():
                need = widget.heightForWidth(widget.width())
                if need > widget.height() + 1:
                    found.append({**item, "kind": "text-cut-bottom", "text": full, "need": need})
            else:
                widest = max(metrics.horizontalAdvance(line) for line in text.split("\n"))
                lines = len(text.split("\n"))
                if widest > room.width() + 1:
                    found.append({**item, "kind": "text-cut-side", "text": full, "need": widest})
                elif full != text:
                    found.append({**item, "kind": "text-elided", "text": full})
                if metrics.height() * lines > room.height() + 2:
                    found.append({**item, "kind": "text-cut-bottom", "text": full,
                                  "need": metrics.height() * lines})
        elif isinstance(widget, QAbstractButton) and widget.text():
            hint = widget.sizeHint()
            if hint.width() > widget.width() + 1:
                found.append({**item, "kind": "button-text-cut", "text": widget.text(), "need": hint.width()})
        parent = widget.parentWidget()
        if (parent is not None and widget is not root and not widget.isWindow()
                and not isinstance(parent, (QStackedWidget,))
                and parent.objectName() != "qt_scrollarea_viewport"
                and not isinstance(parent.parentWidget(), QAbstractScrollArea)):
            box = widget.geometry()
            area = parent.rect()
            if box.width() > 0 and box.height() > 0 and not area.contains(box):
                out_by = max(area.left() - box.left(), box.right() - area.right(),
                             area.top() - box.top(), box.bottom() - area.bottom())
                if out_by > 1:
                    text = getattr(widget, "text", lambda: "")()
                    found.append({**item, "kind": "sticks-out", "by": out_by,
                                  "parent": type(parent).__name__, "text": text if isinstance(text, str) else ""})
    with open(os.path.join(out, "audit.jsonl"), "a", encoding="utf-8") as file:
        for problem in found:
            file.write(json.dumps({"screen": name, **problem}, ensure_ascii=False) + "\n")


def fit(root: QWidget, name: str) -> None:
    """tests/ui_fit_audit.problems() for what the player sees right now."""
    from ui_fit_audit import problems

    found = problems(root)
    with open(os.path.join(out, "fit.jsonl"), "a", encoding="utf-8") as file:
        for problem in found:
            file.write(json.dumps({"screen": name, "problem": problem}, ensure_ascii=False) + "\n")
    print("fit", name, len(found), flush=True)


_label = ["dialog"]
# What the player does inside a dialog once it is open: (step, do it) pairs
# per dialog name, set by dialogs() below.
_steps: dict[str, list] = {}


def _composite(window, dialog) -> "QPixmap":
    """The window with a separate dialog window painted where it floats."""
    from PySide6.QtGui import QPainter

    picture = window.grab()
    if dialog is not None and dialog.isWindow() and dialog is not window:
        painter = QPainter(picture)
        offset = dialog.mapToGlobal(dialog.rect().topLeft()) - window.mapToGlobal(window.rect().topLeft())
        painter.drawPixmap(offset, dialog.grab())
        painter.end()
    return picture


def _fake_exec(dialog, *_args):
    """Every dialog: show it, save how it looks, then answer 取消."""
    dialog.show()
    wait(500)
    settle()
    window = dialog.parentWidget().window() if dialog.parentWidget() else dialog
    _composite(window, dialog).save(os.path.join(out, _label[0] + ".png"))
    audit(dialog, _label[0])
    fit(dialog, _label[0])
    print("saved", _label[0], flush=True)
    for step, do in _steps.get(_label[0].split("-dlg-", 1)[-1], []):
        try:
            do(dialog)
        except Exception:
            traceback.print_exc()
            continue
        wait(300)
        settle()
        name = f"{_label[0]}-{step}"
        _composite(window, dialog).save(os.path.join(out, name + ".png"))
        fit(dialog, name)
    dialog.hide()
    return 0


QDialog.exec = _fake_exec


def dialogs(shell):
    """(name, open it) pairs; each either exec()s a dialog or returns an overlay."""
    from qfluentwidgets import MessageBox

    from src.ui.shell import accounts_ui, actions, clone_flow, data, new_setting_notice
    from src.ui.shell import run_confirm, skill_interval_dialog, wait_settings_dialog

    window = shell.window
    batch = data.task_by_name(data.DAILY_BATCH)

    def tours():
        found = []
        for show in new_setting_notice.NOTICES:
            name = show.__name__.replace("show_", "").replace("_notice", "")
            steps = getattr(new_setting_notice, name + "_steps", None)
            if steps is not None:
                found.append((name, steps))
        return found

    def tour(steps):
        def open_it():
            marks = new_setting_notice.CoachMarks(window, steps(shell), lambda: None)
            marks.start()
            return marks

        return open_it

    from src.ui.shell import run_notify_dialog, schedule_ui
    from src.ui.shell.widgets import shell_buttons
    from src.utils import accounts

    def five_accounts():
        # The menu's 新增账号 adds one and opens this list: the most rows.
        while len(accounts.accounts()) < accounts.MAX_ACCOUNTS:
            accounts.add(data.tr("很长很长的账号名字二十个字"))
        return accounts_ui.ManageDialog(window).exec()

    def last_row(dialog):
        return dialog.rows.itemAt(dialog.rows.count() - 1).widget()

    def set_message(dialog, text):
        # What 保存 does when Windows refuses the task, minus Windows.
        dialog.message.set_text(text)
        dialog.message.show()

    def message():
        box = MessageBox(data.tr("游戏还没开"), data.tr("要帮你打开游戏并开始跑吗？"), window)
        shell_buttons(box)
        return box.exec()

    def fiend_error(box):
        from qfluentwidgets import CaptionLabel

        box.findChildren(CaptionLabel)[0].setText(data.tr('名字不能空白，也不能有 \\ / : * ? " < > |'))

    _steps.clear()
    _steps.update({
        "accounts-5": [
            ("picture-error", lambda d: d.say("看不懂这张图片，换一张 PNG 或 JPG 试试")),
            ("delete-ask", lambda d: last_row(d)._delete()),
            ("deleted", lambda d: last_row(d)._delete()),
            ("error-gone", lambda d: d.say("")),
        ],
        "schedule": [
            *[(f"add-{n}", lambda d: d._add_time()) for n in range(1, 7)],
            ("add-reset", lambda d: d._add_reset()),
            ("save-error", lambda d: set_message(d, "Windows 不让建立定时：请重新打开 YES-BD2 再试，还是不行就重开电脑")),
            ("delete", lambda d: d._delete(d._rows[-1])),
            ("off", lambda d: d.master.setChecked(False)),
        ],
        "run-notify": [
            ("bad-key", lambda d: d.edit.setText("abc")),
            ("good-key", lambda d: d.edit.setText("SCT1234567890abcdef")),
            ("sending", lambda d: d._say(run_notify_dialog.SENDING)),
            ("test-failed", lambda d: d._show_test("发不出去：连不上 Server酱，看看网络，或者过几分钟再试")),
        ],
        "run-confirm": [
            ("other-mode", lambda d: d._set_mode([m for m in (run_confirm.MODE_LEFT, run_confirm.MODE_TICKED) if m != d.mode][0])),
            ("none", lambda d: d._select_all(False)),
            ("all", lambda d: d._select_all(True)),
        ],
        "skill-interval": [
            ("max", lambda d: d.slider.setValue(d.slider.maximum())),
            ("min", lambda d: d.slider.setValue(d.slider.minimum())),
        ],
        "wait-settings": [
            ("max", lambda d: [spin.setValue(spin.maximum()) for spin in d.spins.values()]),
            ("reset", lambda d: d._reset()),
        ],
        "fiend-new-save": [("error", fiend_error)],
    })

    items = [
        ("game-not-open", lambda: actions._ask_to_open_game(window)),
        ("run-confirm", lambda: run_confirm.ask(window, batch)),
        ("run-confirm-clone", lambda: run_confirm.ask(window, batch, clone=True)),
        ("skill-interval", lambda: skill_interval_dialog.ask(window, 1.0, (0.3, 5.0), 1.0)),
        ("wait-settings", lambda: wait_settings_dialog.ask(window)),
        ("accounts", lambda: accounts_ui.ManageDialog(window).exec()),
        ("accounts-5", five_accounts),
        ("schedule", lambda: schedule_ui.ScheduleDialog(window).exec()),
        ("run-notify", lambda: run_notify_dialog.ask(window)),
        ("account-mismatch", lambda: accounts_ui.MismatchDialog(window).exec()),
        ("clone-ask", lambda: clone_flow.ask_and_start(window, batch)),
        ("language-relaunch", lambda: shell.pages["settings"]._offer_relaunch()),
        ("clone-undo", lambda: shell.pages["settings"]._clone_undo()),
        ("fiend-new-save", lambda: shell.pages["fiend"].new_save()),
        ("bargain", lambda: shell.pages["trade"]._bargain_dialog(data.task_by_class_name("BargainLoopTask"))[0].exec()),
        ("message", message),
    ]
    items += [(f"tour-{name}", tour(steps)) for name, steps in tours()]
    return items


def shoot(window):
    from src.ui.shell import theme

    try:
        shell = window._bd2_shell
        window.resize(width, height)
        audit(shell.sidebar, "sidebar")
        for mode in ("light", "dark"):
            theme.set_theme_mode(mode)
            settle()
            for key, page in shell.pages.items():
                shell.navigate(key)
                wait(600)
                settle()
                save(window, f"{mode}-{key}")
                audit(page, f"{mode}-{key}")
                fit(window, f"{mode}-{key}")
                view = getattr(page, "view", None)
                if view is not None and view.height() > page.viewport().height() + 4:
                    save(view, f"{mode}-{key}-full")
            shell.navigate("home")
            wait(400)
            for name, open_it in dialogs(shell):
                _label[0] = f"{mode}-dlg-{name}"
                try:
                    overlay = open_it()
                except Exception:
                    traceback.print_exc()
                    continue
                if isinstance(overlay, QWidget) and hasattr(overlay, "go"):
                    for step in range(len(getattr(overlay, "_steps", [])) or 1):
                        wait(500)
                        settle()
                        save(window, f"{_label[0]}-{step + 1}")
                        audit(overlay, f"{_label[0]}-{step + 1}")
                        fit(overlay, f"{_label[0]}-{step + 1}")
                        overlay.go(1)
                    overlay.hide()
                    overlay.deleteLater()
                settle()
    except Exception:
        traceback.print_exc()
    finally:
        os._exit(0)


original = ok.App.do_show_main


def do_show_main(self):
    original(self)
    QTimer.singleShot(3000, lambda: shoot(self.main_window))


ok.App.do_show_main = do_show_main
import threading  # noqa: E402

threading.Timer(150, lambda: os._exit(3)).start()
ok.OK(config).start()
