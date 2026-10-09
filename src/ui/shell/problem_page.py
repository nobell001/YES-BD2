"""回报问题: copy or save a run's 问题摘要 to send the author (Leo 2026-10-09).

Two places, both easy to find (Leo: 「那個地方也要方便找」): a red card on
the 跑完的结算 page whenever a run did not fully finish, and this page in the
sidebar, where any run of the last days can be picked, a fine one too
(「没失败但觉得不对劲」).  Each offers 复制图片 (the main one), 保存图片 (to
the desktop) and 复制文字 (four short lines).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.tasks import problem_report
from src.ui.shell import data, problem_image, theme
from src.ui.shell.page import Page
from src.ui.shell.widgets import (
    SHADOW_MARGINS,
    Button,
    Card,
    IconLabel,
    StateIcon,
    Text,
    clear_layout,
    hbox,
    t,
    tf,
    vbox,
)

FEEDBACK_MS = 2500
PAGE_SUB = "选一次运行，复制图片或文字，到留言区或聊天框按 Ctrl+V 贴上。没失败但觉得不对劲也可以。"


def run_title(record: dict) -> str:
    """'今天 14:32 · 一键完成日常'."""
    finished = record.get("finished")
    when = f"{t(data.day_text(finished))} {data.clock_text(finished)}".strip()
    return f"{when} · {t(record.get('label') or '')}"


def run_line(record: dict) -> str:
    """'手动停止 · 停在「每周跑图」' under a run's title."""
    ended = problem_image.ended_text(record)
    problem = record.get("problem") or {}
    if problem.get("task"):
        return tf("{ended} · 停在「{task}」", ended=ended, task=t(problem["task"]))
    return ended


def state_of(record: dict) -> str:
    ended = record.get("ended")
    if ended == problem_report.DONE:
        return "done"
    if ended in (problem_report.STOPPED, problem_report.SETUP):
        return "skip"
    return "fail"


class Preview(QWidget):
    """The top of the picture at the card's width; a click shows all of it."""

    clicked = Signal()

    def __init__(self, height: int, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self._scaled: QImage | None = None
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._scaled = None
        self.update()

    def _fitted(self, width: float) -> QImage:
        """The picture shrunk smoothly to ``width`` once (painting it scaled
        down three times over left the small text ragged)."""
        ratio = self.devicePixelRatioF()
        side = max(1, round(width * ratio))
        if self._scaled is None or self._scaled.width() != side:
            self._scaled = self._image.scaledToWidth(side, Qt.SmoothTransformation)
            self._scaled.setDevicePixelRatio(ratio)
        return self._scaled

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, theme.color("inset"))
        if not self._image.isNull():
            painter.save()
            painter.setClipPath(path)
            painter.drawImage(rect.topLeft(), self._fitted(rect.width()))
            painter.restore()
        painter.setPen(QPen(theme.color("line2"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ReportActions(QWidget):
    """Preview, 复制图片, 保存图片, 复制文字 and a line saying what happened."""

    def __init__(self, preview_height: int, parent=None):
        super().__init__(parent)
        self._record: dict | None = None
        self._image: QImage | None = None
        layout = vbox(self, (0, 0, 0, 0), 10)
        self.preview = Preview(preview_height)
        self.preview.clicked.connect(self._show_picture)
        layout.addWidget(self.preview)
        self.copy_image = Button("复制图片", "primary", "image", "lg", on_click=self._copy_image)
        layout.addWidget(self.copy_image)
        row = hbox(None, (0, 0, 0, 0), 10)
        self.save_image = Button("保存图片", "secondary", "download", on_click=self._save_image)
        self.copy_text = Button("复制文字", "secondary", "file-text", on_click=self._copy_text)
        row.addWidget(self.save_image, 1)
        row.addWidget(self.copy_text, 1)
        layout.addLayout(row)
        self.note = Text("", "muted", wrap=True)
        self.note.setAlignment(Qt.AlignHCenter)
        layout.addWidget(self.note)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reset_note)
        self._reset_note()

    def set_record(self, record: dict | None) -> None:
        same = (record or {}).get("path") == (self._record or {}).get("path")
        self._record = record
        if not same:
            self._image = None
            self.preview.set_image(self.image() if record else QImage())
            self._reset_note()
        for button in (self.copy_image, self.save_image, self.copy_text):
            button.setEnabled(record is not None)

    def image(self) -> QImage:
        if self._image is None and self._record is not None:
            self._image = problem_image.render(self._record)
        return self._image or QImage()

    def _reset_note(self) -> None:
        self.copy_image.set_label("复制图片")
        self.copy_image.set_icon_name("image")
        self.note.set_text("复制后到留言区或聊天框按 Ctrl+V 贴上。不含账号和电脑用户名")

    def _done(self, text: str) -> None:
        self.note.set_text(text)
        self._timer.start(FEEDBACK_MS)

    def _copy_image(self) -> None:
        if self._record is None:
            return
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setImage(self.image())
        self.copy_image.set_label("图片已复制")
        self.copy_image.set_icon_name("check")
        self._done("图片已复制，到留言区或聊天框按 Ctrl+V 贴上")

    def _copy_text(self) -> None:
        if self._record is None:
            return
        problem_image.copy_text(self._record)
        self._done("文字已复制，到留言区或聊天框按 Ctrl+V 贴上")

    def _save_image(self) -> None:
        if self._record is None:
            return
        folder = problem_image.desktop()
        path = folder / problem_image.file_name(self._record)
        try:
            saved = self.image().save(str(path), "PNG")
        except Exception:
            saved = False
        if saved:
            self._done(tf("已保存到桌面：{name}", name=path.name))
        else:
            self._done("没能保存到桌面")

    def _show_picture(self) -> None:
        if self._record is None:
            return
        from PySide6.QtGui import QPixmap

        from src.ui.shell.home import PictureDialog

        PictureDialog("", self, pixmap=QPixmap.fromImage(self.image())).exec()


class ProblemCard(Card):
    """The red card on the 跑完的结算 page of a run that did not fully finish."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = vbox(self, (18, 16, 18, 16), 10)
        head = hbox(None, (0, 0, 0, 0), 8)
        head.addWidget(IconLabel("message-circle-warning", 20, "bad"), 0, Qt.AlignVCenter)
        head.addWidget(Text("卡住了？告诉作者", "h2"), 1)
        layout.addLayout(head)
        layout.addWidget(
            Text(
                "工具会把这次的情况和卡住时的游戏画面整理好，复制后贴到留言区，作者就知道卡在哪。",
                "sub",
                wrap=True,
            )
        )
        self.actions = ReportActions(220)
        layout.addWidget(self.actions)

    def set_record(self, record: dict | None) -> None:
        self.actions.set_record(record)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        left, top, right, bottom = SHADOW_MARGINS
        body = QRectF(self.rect()).adjusted(left + 1, top + 1, -right - 1, -bottom - 1)
        painter.setPen(QPen(theme.color("bad"), 2))
        painter.setBrush(Qt.NoBrush)
        corner = float(theme.radius())
        painter.drawRoundedRect(body, corner, corner)


class RunRow(QWidget):
    """One run in the 回报问题 list; the chosen one is outlined."""

    chosen = Signal(str)

    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.path = record.get("path") or ""
        self._selected = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        layout = hbox(self, (12, 10, 12, 10), 10)
        layout.addWidget(StateIcon(state_of(record), 16), 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text(run_title(record), "h3", elide=True))
        line = Text(run_line(record), "bad" if state_of(record) != "done" else "muted", elide=True)
        texts.addWidget(line)
        layout.addLayout(texts, 1)

    def set_selected(self, on: bool) -> None:
        self._selected = on
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
        if not (self._selected or self._hover):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._selected:
            painter.setPen(QPen(theme.color("accent"), 2))
            painter.setBrush(theme.color("accent_soft"))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("ink", 0.04))
        painter.drawRoundedRect(rect, 12, 12)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.path)
        super().mouseReleaseEvent(event)


class ProblemPage(Page):
    interval = 4000

    def __init__(self):
        super().__init__("shellProblem", "回报问题", PAGE_SUB)
        self._records: list[dict] = []
        self._shown_key = None
        self._chosen = ""
        self._rows: list[RunRow] = []

        self.empty = Card()
        empty_layout = vbox(self.empty, (20, 18, 20, 18), 4)
        empty_layout.addWidget(Text("还没有运行记录", "h3"))
        empty_layout.addWidget(
            Text("跑过一键日常、周常或单独执行后，这里就能复制那一次的情况。", "muted")
        )
        self.body.addWidget(self.empty)

        self.columns = QWidget()
        columns = hbox(self.columns, (0, 0, 0, 0), 16)
        self.list_card = Card()
        list_layout = vbox(self.list_card, (12, 12, 12, 12), 4)
        list_layout.addWidget(Text("最近 7 天", "h3"))
        self.list_layout = vbox(None, (0, 0, 0, 0), 2)
        list_layout.addLayout(self.list_layout)
        list_layout.addStretch(1)
        columns.addWidget(self.list_card, 2)
        self.preview_card = Card()
        preview_layout = vbox(self.preview_card, (16, 16, 16, 16), 0)
        self.actions = ReportActions(420)
        preview_layout.addWidget(self.actions)
        preview_layout.addStretch(1)
        columns.addWidget(self.preview_card, 3)
        self.body.addWidget(self.columns)
        self.body.addStretch(1)

    def refresh(self) -> None:
        records = problem_report.records()
        key = tuple(record.get("path") for record in records)
        if key == self._shown_key:
            return
        self._shown_key = key
        self._records = records
        self.empty.setVisible(not records)
        self.columns.setVisible(bool(records))
        clear_layout(self.list_layout)
        self._rows = []
        for record in records:
            row = RunRow(record)
            row.chosen.connect(self._choose)
            self.list_layout.addWidget(row)
            self._rows.append(row)
        paths = [record.get("path") for record in records]
        self._choose(self._chosen if self._chosen in paths else (paths[0] if paths else ""))

    def _choose(self, path: str) -> None:
        self._chosen = path
        for row in self._rows:
            row.set_selected(row.path == path)
        record = next((r for r in self._records if r.get("path") == path), None)
        self.actions.set_record(record)
