"""The status bar on top of the game while a run is on (YES-BD2 #60).

Leo 2026-10-28 「做一個執行中可以置頂在遊戲視窗的狀態欄 可以看現在進行中的狀態」
and 「不要干擾到辨識和判定」.  The bar is drawn after mockup v2
(ui-mockups/ontop-status-1027/ingame-mockup.png): dark glass at the top
middle of the game, under the currency row; the task and its step, the
latest log line, the time so far, 第 N / M 项, a thin progress line.

What keeps it out of the run's way:
- Screenshots: the window is excluded from every capture
  (WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+).  WGC and BitBlt_RenderFull
  capture only the game window anyway; a screen BitBlt would see the bar,
  so where Windows refuses the exclusion the bar is never shown.
- Clicks: the mouse goes through it (WS_EX_TRANSPARENT) and it never takes
  the focus (WS_EX_NOACTIVATE), so the game stays the foreground window.
  Only its 暂停/停止 buttons take a click, and only while the player's own
  mouse is on one (StatusBar).
  The 「游戏被遮住」 and takeover checks look through it
  (``src.utils.game_status_bar.window_at``).
- It shows only while the game itself is in front, and hides 10 s after the
  run ends.

Off unless the player turns it on in 设置 (it is read each half second, so
turning it off mid-run hides it at once).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from ok import Logger
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from src.tasks import run_report
from src.tasks.BaseBD2Task import task_info_snapshot
from src.ui.shell import data, hotkeys, icons, theme
from src.ui.shell.safe import guarded
from src.ui.shell.widgets import fmt_clock, t, tf
from src.utils import game_status_bar

logger = Logger.get_logger(__name__)

CHECK_MS = 500
LINGER_SECONDS = 10.0  # the end line stays this long, then the bar hides
TOP_RATIO = 0.075  # bar top, as a share of the game height: under the currency row
WIDTH_RATIO = 0.36
SHADOW = 14  # room around the card for its shadow

RUN, PAUSE, STOP, DONE, FAIL = "run", "pause", "stop", "done", "fail"
DOT = {
    RUN: "#9D92E8",
    PAUSE: "#E5B454",
    STOP: "#E5B454",
    DONE: "#7CC4A0",
    FAIL: "#E07A8F",
}


@dataclass
class Status:
    tone: str
    title: str
    detail: str = ""
    clock: str = ""
    count: str = ""
    progress: float | None = None
    icon: str = "loader-circle"
    # The buttons while the run is on: (action, word, key) as hotkeys has
    # them, e.g. ("pause", "暂停", "F9"); the key reads 「无」 when it is off.
    # The word names the button; the bar shows only its icon and key.
    buttons: tuple[tuple[str, str, str], ...] = ()
    # While paused on a task that lets the player pick its stage (塔洛斯教材):
    # (stage shown, how many, that one cleared).  None everywhere else.
    picker: tuple[int, int, bool] | None = None


# ---------------------------------------------------------------- what to say


def stage_text(task) -> str:
    """The step a task says it is on (当前阶段 / 状态), without its own name."""
    if task is None:
        return ""
    info = task_info_snapshot(task)
    for key in ("当前阶段", "状态"):
        text = str(info.get(key) or "").strip()
        if text and text != "-":
            name = str(getattr(task, "name", ""))
            return text[len(name) :].lstrip("：: ") if name and text.startswith(name) else text
    return ""


def log_text(task) -> str:
    if task is None:
        return ""
    text = str(task_info_snapshot(task).get("Log") or "").strip()
    return "" if text == "-" else text


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def _counts(rows: list[dict]) -> tuple[int, int, int]:
    states = [row.get("state") for row in rows]
    return states.count(run_report.DONE), states.count(run_report.SKIP), states.count(run_report.FAIL)


def running_status(
    report: dict | None, task, child, paused: bool, stopping: bool, now: float
) -> Status:
    """The bar while a run is on.  ``report`` is the 一键完成日常 report (None
    for one task run alone), ``child`` the task doing the current item."""
    if report is not None:
        rows = report.get("rows") or []
        key = report.get("current")
        index = next((i for i, row in enumerate(rows) if row.get("key") == key), None)
        row = rows[index] if index is not None else None
        name = str(row.get("name") or "") if row else ""
        icon = data.CHILD_META.get(key or "", ("", "loader-circle", ""))[1]
        started = report.get("started")
        done, skipped, failed = _counts(rows)
        count = (
            tf("第 {n} / {total} 项", n=index + 1, total=len(rows))
            if index is not None and rows
            else ""
        )
        progress = (done + skipped + failed) / len(rows) if rows else None
    else:
        child = task
        name = data.tr(str(getattr(task, "name", "")))
        icon = data.task_look(task)[0] if task is not None else "loader-circle"
        started = getattr(task, "start_time", 0) or None
        count, progress = "", None
    clock = fmt_clock(now - started) if started else ""
    if stopping:
        return Status(STOP, _join(t("正在停止"), name), t("正在收尾，请稍等"), clock, count, progress, icon)
    if paused:
        return Status(
            PAUSE, _join(t("已暂停"), name, stage_text(child)), log_text(child), clock, count, progress, icon, buttons(True)
        )
    return Status(
        RUN,
        _join(name or t("正在准备"), stage_text(child)),
        log_text(child),
        clock,
        count,
        progress,
        icon,
        buttons(False),
    )


PREV, NEXT = "stage_prev", "stage_next"


def with_picker(status: Status, picker) -> Status:
    """Paused on a task with a ``stage_picker`` (Leo 2026-10-28 「暫停後可以在
    上面切換關卡」): the bar shows 「◀ 第 N 关 ▶」, the stage picked or the one
    being played, with ✓ when it is cleared.  The picker has ``count``,
    ``current``, ``cleared`` (set of numbers), ``chosen`` (None: not
    changed) and ``pick(n)``; the task reads ``chosen`` when it goes on."""
    if picker is None or status.tone != PAUSE:
        return status
    count = int(getattr(picker, "count", 0) or 0)
    if count < 2:
        return status
    current = int(getattr(picker, "current", 1) or 1)
    chosen = getattr(picker, "chosen", None)
    shown = int(chosen) if chosen else current
    detail = status.detail
    if shown != current:
        # Says what 继续 will do now.
        detail = tf("按继续改打第 {n} 关", n=shown)
    cleared = shown in set(getattr(picker, "cleared", ()) or ())
    return replace(status, detail=detail, picker=(shown, count, cleared))


def step_stage(picker, action: str) -> None:
    """◀ / ▶ on the bar: the stage before or after, round 1..count."""
    count = int(getattr(picker, "count", 0) or 0)
    if count < 2:
        return
    current = int(getattr(picker, "current", 1) or 1)
    shown = int(getattr(picker, "chosen", None) or current)
    shown = shown % count + 1 if action == NEXT else (shown - 2) % count + 1
    picker.pick(shown)


def buttons(paused: bool, current: dict[str, str] | None = None) -> tuple[tuple[str, str, str], ...]:
    """暂停/继续 and 停止, each with the key set in 设置 (Leo 2026-10-28: 「無」
    for a key turned off there)."""
    current = current or hotkeys.keys()
    return (
        (hotkeys.PAUSE, t("继续" if paused else "暂停"), t(current[hotkeys.PAUSE])),
        (hotkeys.STOP, t("停止"), t(current[hotkeys.STOP])),
    )


def finished_status(report: dict | None, name: str, started: float | None, now: float) -> Status:
    """The end line: how it went, and the first reason when an item failed."""
    if report is None:
        clock = fmt_clock(now - started) if started else ""
        return Status(DONE, _join(t("跑完"), name), "", clock, "", 1.0, "check")
    rows = report.get("rows") or []
    done, skipped, failed = _counts(rows)
    ended = report.get("ended")
    title = t("已停止") if ended == run_report.ENDED_STOPPED else t("跑完")
    parts = [tf("完成 {n}", n=done)]
    if skipped:
        parts.append(tf("跳过 {n}", n=skipped))
    if failed:
        parts.append(tf("失败 {n}", n=failed))
    first_fail = next((row for row in rows if row.get("state") == run_report.FAIL), None)
    detail = ""
    if first_fail is not None:
        note = str(first_fail.get("note") or "").strip()
        detail = _join(str(first_fail.get("name") or ""), note) if note else str(first_fail.get("name") or "")
    elif ended != run_report.ENDED_DONE:
        detail = t("回到工具看结算")
    started = report.get("started")
    finished = report.get("finished") or now
    return Status(
        FAIL if failed or ended not in (run_report.ENDED_DONE, None) else DONE,
        title + "：" + " · ".join(parts),
        detail,
        fmt_clock(finished - started) if started else "",
        tf("{done} / {total} 项", done=done, total=len(rows)) if rows else "",
        1.0,
        "circle-alert" if failed else "check",
    )


# ---------------------------------------------------------------- the window


class _PressRelay(QObject):
    """A press the mouse hook made for the bar (another thread) → the Qt thread."""

    pressed = Signal(str)


class StatusBar(QWidget):
    """The bar's own window: click-through, never focused, kept out of screenshots.

    Its buttons take a click only while the player's own mouse is on one
    (Leo 2026-10-28 「要有滑鼠可以點的樣子」) and the tool is not pressing the
    real mouse (``game_status_bar.hold_clicks``).  The tool's own clicks are
    posted to the game window and never pass through here.  No resting
    first: a player's quick press on ▶ came before the cursor had rested
    and went through to the game (Leo's 4K 2026-10-28 16:02).
    """

    PAD = 14
    WATCH_MS = 15  # how often the cursor is looked at

    def __init__(self, on_press: Callable[[str], None] | None = None):
        super().__init__(None)
        self._on_press = on_press
        self._button_rects: list[tuple[str, QRectF]] = []
        self._hover: str | None = None
        self._live = False
        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(guarded("game status bar hover", self._watch_mouse))
        # A press the takeover hook kept off the game while the tool moved the
        # mouse, or that beat the button waking up (src/utils/mouse_guard).
        self._relay = _PressRelay(self)
        self._relay.pressed.connect(guarded("game status bar press", self._relayed_press))
        game_status_bar.set_press_handler(self._relay.pressed.emit)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.status: Status | None = None
        self.px = 15
        self.native_ok: bool | None = None  # None: not tried yet

    # The window has to exist before Windows can be told about it; it is
    # made (not shown) here, so a refusal hides nothing that was on screen.
    def prepare(self) -> bool:
        if self.native_ok is None:
            self.native_ok = make_invisible_to_run(int(self.winId()))
            if self.native_ok:
                game_status_bar.register(int(self.winId()))
        return bool(self.native_ok)

    def set_status(self, status: Status) -> None:
        if status != self.status:
            self.status = status
            self.update()

    # ------------------------------------------------------------ buttons

    def showEvent(self, event):
        super().showEvent(event)
        self._hover_timer.start(self.WATCH_MS)

    def hideEvent(self, event):
        self._hover_timer.stop()
        self._set_live(False, None)
        game_status_bar.set_buttons(int(self.winId()), [])
        super().hideEvent(event)

    def _native_button_rects(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        import win32gui

        left, top, right, _bottom = win32gui.GetWindowRect(int(self.winId()))
        ratio = (right - left) / self.width() if self.width() else 1.0
        return [
            (
                action,
                (
                    round(left + rect.left() * ratio),
                    round(top + rect.top() * ratio),
                    round(left + rect.right() * ratio),
                    round(top + rect.bottom() * ratio),
                ),
            )
            for action, rect in self._button_rects
        ]

    def _watch_mouse(self) -> None:
        import win32api

        rects = self._native_button_rects() if self._button_rects else []
        game_status_bar.set_buttons(
            int(self.winId()), [rect for _action, rect in rects], [action for action, _rect in rects]
        )
        if not rects:
            self._set_live(False, None)
            return
        point = tuple(win32api.GetCursorPos())
        under = next(
            (
                action
                for action, rect in rects
                if rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]
            ),
            None,
        )
        self._set_live(under is not None, under)

    def _set_live(self, live: bool, hover: str | None) -> None:
        if live:
            rects = [rect for _action, rect in self._native_button_rects()]
            live = game_status_bar.set_live(int(self.winId()), rects)
        elif self._live:
            game_status_bar.set_live(int(self.winId()), [])
        hover = hover if live else None
        if (live, hover) != (self._live, self._hover):
            self._live, self._hover = live, hover
            self.update()

    def _relayed_press(self, action: str) -> None:
        if not self.isVisible():
            return
        logger.info(f"game status bar: player pressed {action} (through the mouse hook)")
        if self._on_press is not None:
            self._on_press(action)

    def mousePressEvent(self, event):
        if not self._live:
            logger.info("game status bar: a press came while its buttons took no clicks")
            return
        point = event.position()
        for action, rect in self._button_rects:
            if rect.contains(point):
                logger.info(f"game status bar: player pressed {action}")
                if self._on_press is not None:
                    self._on_press(action)
                break

    def place(self, area: QRect, px: int) -> None:
        """Top middle of ``area`` (the game's inside, in Qt's units).  The
        window is the card plus room for its soft shadow (see-through, and
        the mouse goes through it)."""
        self.px = px
        small = max(12, px - 2)
        card_h = round(self.PAD * 2 + px * 1.5 + small * 1.5 + 12 + small * 1.5 + 8)
        card_w = round(max(px * 24, min(px * 44, area.width() * WIDTH_RATIO)))
        card_w = min(card_w, area.width() - 2 * SHADOW)
        left = area.x() + (area.width() - card_w) // 2 - SHADOW
        top = area.y() + round(area.height() * TOP_RATIO) - SHADOW
        rect = QRect(left, top, card_w + 2 * SHADOW, card_h + 2 * SHADOW)
        if self.geometry() != rect:
            self.setGeometry(rect)
            self.update()

    def card(self) -> QRectF:
        return QRectF(self.rect()).adjusted(SHADOW, SHADOW - 3, -SHADOW, -SHADOW - 3)

    def paintEvent(self, _event):
        status = self.status
        if status is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = self.card()
        corner = min(16.0, card.height() / 4)
        tone = QColor(DOT.get(status.tone, DOT[RUN]))

        # Soft shadow under the card, then the glass: a little lighter at
        # the top, a faint tone-coloured glow from the left, a hairline of
        # light along the top edge.  No outline (Leo 「裡面不要有框」).
        painter.setPen(Qt.NoPen)
        for step in range(SHADOW, 0, -2):
            fade = 1 - step / SHADOW
            painter.setBrush(QColor(0, 0, 0, round(46 * fade * fade)))
            grow = step * 0.8
            painter.drawRoundedRect(
                card.adjusted(-grow, -grow * 0.5 + 3, grow, grow + 3), corner + grow, corner + grow
            )
        path = QPainterPath()
        path.addRoundedRect(card, corner, corner)
        glass = QLinearGradient(card.topLeft(), card.bottomLeft())
        glass.setColorAt(0.0, QColor(44, 40, 60, 232))
        glass.setColorAt(1.0, QColor(18, 17, 25, 238))
        painter.fillPath(path, glass)
        painter.save()
        painter.setClipPath(path)
        glow = QRadialGradient(card.left() + card.height() * 0.5, card.center().y(), card.height() * 1.6)
        glow_colour = QColor(tone)
        glow_colour.setAlpha(46)
        glow.setColorAt(0.0, glow_colour)
        glow_colour.setAlpha(0)
        glow.setColorAt(1.0, glow_colour)
        painter.fillRect(card, glow)
        shine = QLinearGradient(card.topLeft(), card.topRight())
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 46))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(QRectF(card.left(), card.top(), card.width(), 1), shine)
        if status.progress is not None:
            # The progress line runs along the bottom edge of the card.
            track = QRectF(card.left(), card.bottom() - 3, card.width(), 3)
            painter.fillRect(track, QColor(255, 255, 255, 18))
            done = max(0.0, min(1.0, status.progress))
            if done > 0:
                filled = QRectF(track.left(), track.top(), track.width() * done, 3)
                bar = QLinearGradient(filled.topLeft(), filled.topRight())
                start = QColor(tone)
                start.setAlpha(120)
                bar.setColorAt(0.0, start)
                bar.setColorAt(1.0, tone.lighter(118))
                painter.fillRect(filled, bar)
        painter.restore()

        px, pad = self.px, self.PAD
        small = max(12, px - 2)
        # The task's picture on a rounded tile in the run's colour.
        tile = round(px * 2.4)
        tile_rect = QRectF(card.left() + pad, card.top() + pad + 1, tile, tile)
        painter.setPen(Qt.NoPen)
        fill = QLinearGradient(tile_rect.topLeft(), tile_rect.bottomRight())
        fill.setColorAt(0.0, tone.lighter(112))
        fill.setColorAt(1.0, tone.darker(150))
        painter.setBrush(fill)
        painter.drawRoundedRect(tile_rect, tile * 0.3, tile * 0.3)
        inner = tile * 0.52
        icons.paint(
            painter,
            QRectF(tile_rect.center().x() - inner / 2, tile_rect.center().y() - inner / 2, inner, inner),
            status.icon,
            QColor(255, 255, 255, 245),
            2.0,
        )

        base = theme.body_font(QFont(self.font()))
        title_font = QFont(base)
        title_font.setPixelSize(px)
        detail_font = QFont(base)
        detail_font.setPixelSize(small)
        clock_font = QFont(base)
        clock_font.setPixelSize(round(px * 1.2))
        clock_font = theme.strong(clock_font, digits=True)
        clock_font.setLetterSpacing(QFont.PercentageSpacing, 102)

        text_left = tile_rect.right() + pad
        right = card.right() - pad - 2
        line1 = QRectF(text_left, card.top() + pad, 0, px * 1.5)
        line2 = QRectF(text_left, line1.bottom() + 1, 0, small * 1.5)
        clock_w = QFontMetrics(clock_font).horizontalAdvance(status.clock) + 2 if status.clock else 0
        count_w = QFontMetrics(detail_font).horizontalAdvance(status.count) + 2 if status.count else 0

        # Title: the task bright, its step softer.
        name, _sep, step = status.title.partition(" · ")
        title_room = right - clock_w - 14 - text_left
        name_w = min(QFontMetrics(title_font).horizontalAdvance(name) + 1, title_room)
        self._text(painter, title_font, QColor(255, 255, 255, 245), name,
                   QRectF(text_left, line1.top(), name_w, line1.height()))
        if step:
            step_left = text_left + name_w + 8
            self._text(painter, title_font, QColor(255, 255, 255, 150), step,
                       QRectF(step_left, line1.top(), text_left + title_room - step_left, line1.height()))
        self._text(painter, detail_font, QColor(255, 255, 255, 135), status.detail,
                   QRectF(text_left, line2.top(), right - count_w - 14 - text_left, line2.height()))
        if status.clock:
            self._text(painter, clock_font, QColor(255, 255, 255, 245), status.clock,
                       QRectF(right - clock_w, line1.top(), clock_w, line1.height()), Qt.AlignRight)
        if status.count:
            self._text(painter, detail_font, QColor(255, 255, 255, 120), status.count,
                       QRectF(right - count_w, line2.top(), count_w, line2.height()), Qt.AlignRight)

        row = QRectF(text_left, line2.bottom() + 10, right - text_left, small * 1.5 + 4)
        self._paint_buttons(painter, detail_font, row)

    def _paint_buttons(self, painter, font, row: QRectF) -> None:
        """Soft pills, no outline: the icon and the key set in 设置, no word
        (Leo 2026-10-28 「暫停 停止 不用寫中文 用圖示即可」)."""
        self._button_rects = []
        key_font = QFont(font)
        key_font.setPixelSize(max(11, font.pixelSize() - 2))
        key_metrics = QFontMetrics(key_font)
        x = row.left()
        icon_px = max(10, font.pixelSize() - 2)
        paused = self.status is not None and self.status.tone == PAUSE
        for action, _word, key in self.status.buttons if self.status else ():
            key_w = key_metrics.horizontalAdvance(key)
            pill = QRectF(x, row.top(), 12 + icon_px + 8 + key_w + 12, row.height())
            if pill.right() > row.right():
                break
            hover = self._hover == action
            painter.setPen(Qt.NoPen)
            if hover:
                fill = QLinearGradient(pill.topLeft(), pill.bottomLeft())
                fill.setColorAt(0.0, QColor(140, 126, 230, 240))
                fill.setColorAt(1.0, QColor(104, 91, 186, 240))
                painter.setBrush(fill)
            else:
                painter.setBrush(QColor(255, 255, 255, 20))
            painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            name = ("play" if paused else "pause") if action == hotkeys.PAUSE else "square"
            icons.paint(
                painter,
                QRectF(pill.left() + 12, pill.center().y() - icon_px / 2, icon_px, icon_px),
                name,
                QColor(255, 255, 255, 245 if hover else 200),
                2.2,
            )
            self._text(painter, key_font, QColor(255, 255, 255, 170 if hover else 105), key,
                       QRectF(pill.left() + 12 + icon_px + 8, pill.top(), key_w + 2, pill.height()))
            self._button_rects.append((action, pill))
            x = pill.right() + 8
        if self.status is not None and self.status.picker is not None:
            self._paint_picker(painter, font, row)

    def _paint_picker(self, painter, font, row: QRectF) -> None:
        """「‹ 第 N 关 已通关 ›」 right after 继续/停止, the same soft pill; each arrow
        is its own half and lights up like the buttons (Leo 2026-10-28: the
        round lit arrow on its own at the far right 「看起來很怪」)."""
        shown, _count, cleared = self.status.picker
        word = tf("第 {n} 关", n=shown)
        word_w = QFontMetrics(font).horizontalAdvance(word)
        # A cleared stage says so in words, softer (the ✓ 「也很怪」, Leo 10-28).
        done = t("已通关") if cleared else ""
        done_w = QFontMetrics(font).horizontalAdvance(done) if done else 0
        arrow = round(row.height() * 1.1)
        middle = 4 + word_w + (8 + done_w if done else 0) + 4
        last = self._button_rects[-1][1] if self._button_rects else None
        left = last.right() + 8 if last is not None else row.left()
        pill = QRectF(left, row.top(), arrow + middle + arrow, row.height())
        if pill.right() > row.right():
            return
        radius = pill.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(pill, radius, radius)
        outline = QPainterPath()
        outline.addRoundedRect(pill, radius, radius)
        for action, x, name in (
            (PREV, pill.left(), "chevron-left"),
            (NEXT, pill.right() - arrow, "chevron-right"),
        ):
            half = QRectF(x, pill.top(), arrow, pill.height())
            hover = self._hover == action
            if hover:
                painter.save()
                painter.setClipPath(outline)
                fill = QLinearGradient(half.topLeft(), half.bottomLeft())
                fill.setColorAt(0.0, QColor(140, 126, 230, 240))
                fill.setColorAt(1.0, QColor(104, 91, 186, 240))
                painter.fillRect(half, fill)
                painter.restore()
            size = round(pill.height() * 0.5)
            icons.paint(
                painter,
                QRectF(half.center().x() - size / 2, half.center().y() - size / 2, size, size),
                name,
                QColor(255, 255, 255, 245 if hover else 200),
                2.2,
            )
            self._button_rects.append((action, half))
        text_left = pill.left() + arrow + 4
        self._text(painter, font, QColor(255, 255, 255, 235), word,
                   QRectF(text_left, pill.top(), word_w + 2, pill.height()))
        if done:
            self._text(painter, font, QColor(255, 255, 255, 120), done,
                       QRectF(text_left + word_w + 8, pill.top(), done_w + 2, pill.height()))

    @staticmethod
    def _text(painter, font, colour, text, rect: QRectF, align=Qt.AlignLeft) -> None:
        if not text or rect.width() <= 0:
            return
        painter.setFont(font)
        painter.setPen(colour)
        shown = QFontMetrics(font).elidedText(text, Qt.ElideRight, int(rect.width()))
        painter.drawText(rect, int(align | Qt.AlignVCenter), shown)


# ---------------------------------------------------------------- Windows


def make_invisible_to_run(hwnd: int) -> bool:
    """Keep the window out of screenshots, out of the mouse's way and never
    focused.  False (and the bar stays hidden) when Windows refuses."""
    import sys

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # Qt makes a frameless see-through window layered; layered +
        # WS_EX_TRANSPARENT lets the mouse through.  Not layered: no bar.
        # (Not Qt.WindowTransparentForInput: Qt would then refuse the
        # buttons' clicks too.)
        if not style & WS_EX_LAYERED:
            logger.warning(f"game status bar: not click-through (style {style:#x}); it stays hidden")
            return False
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )
        WDA_EXCLUDEFROMCAPTURE = 0x11
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            logger.warning(
                f"game status bar: Windows refused to keep it out of screenshots "
                f"(error {ctypes.GetLastError()}); it stays hidden"
            )
            return False
        return True
    except Exception as exc:
        logger.warning(f"game status bar: not set up ({exc}); it stays hidden")
        return False


def game_handles() -> set[int]:
    window = getattr(getattr(data.og(), "device_manager", None), "hwnd_window", None)
    handles = {getattr(window, "hwnd", None), getattr(window, "top_hwnd", None)}
    return {int(handle) for handle in handles if handle}


def game_area(hwnd: int) -> QRect | None:
    """The game's inside on screen, in Qt's units, when it is the window in
    front and not minimized; None otherwise."""
    return game_area_why(hwnd)[0]


def game_area_why(hwnd: int) -> tuple[QRect | None, str]:
    """``game_area`` and, when None, why (for the log)."""
    import win32gui

    if not hwnd or not win32gui.IsWindow(hwnd):
        return None, "no game window"
    if win32gui.IsIconic(hwnd):
        return None, "the game is minimised"
    front = win32gui.GetForegroundWindow()
    if game_status_bar.is_bar(front) or game_status_bar.is_bar(win32gui.GetAncestor(front, 2)):
        front = hwnd  # the bar itself in front (it never should be): still over the game
    if win32gui.GetAncestor(front, 2) not in game_handles() and front not in game_handles():
        # another window (the tool too) is in front
        try:
            title = win32gui.GetWindowText(front) or win32gui.GetClassName(front)
        except Exception:
            title = ""
        return None, f"another window is in front ({title!r})"
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (left, top))
    area = native_to_qt(QRect(x, y, right - left, bottom - top))
    return area, "" if area is not None else "the game is on no screen"


def native_to_qt(rect: QRect) -> QRect | None:
    """Screen pixels -> Qt's units.  Qt 6 keeps each screen's top-left corner
    in pixels and scales only the inside by that screen's ratio."""
    centre = rect.center()
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio() or 1.0
        native = QRect(geometry.topLeft(), geometry.size() * ratio)
        if native.contains(centre):
            origin = geometry.topLeft()
            top_left = origin + (rect.topLeft() - origin) / ratio
            return QRect(QPoint(round(top_left.x()), round(top_left.y())), rect.size() / ratio)
    return None


def font_px(area: QRect) -> int:
    return max(13, min(24, round(area.height() * 0.0175)))


# ---------------------------------------------------------------- the watcher


class Watch(QObject):
    """Looks every half second: shows, fills, moves or hides the bar."""

    def __init__(self, parent, on_press: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._on_key = on_press
        self._picker = None  # the stage picker of the task shown, while paused
        self.bar: StatusBar | None = None
        self._watching: tuple[str | None, float | None, str, float | None] | None = None
        self._end: Status | None = None
        self._end_at = 0.0
        self._state: str | None = None  # what the log last said about the bar
        self._timer = QTimer(self)
        self._timer.timeout.connect(guarded("game status bar", self.tick))
        self._timer.start(CHECK_MS)

    def tick(self) -> None:
        now = time.time()
        status = self._status(now)
        if status is None or not game_status_bar.enabled():
            self._hide("no run" if status is None else "turned off in 设置")
            return
        window = getattr(getattr(data.og(), "device_manager", None), "hwnd_window", None)
        area, why = game_area_why(int(getattr(window, "hwnd", 0) or 0))
        if area is None:
            self._hide(why)
            return
        if self.bar is None:
            self.bar = StatusBar(guarded("game status bar press", self._on_press))
        if not self.bar.prepare():
            return
        self.bar.set_status(status)
        self.bar.place(area, font_px(area))
        if not self.bar.isVisible():
            self.bar.show()
        self._note("shown")

    def _on_press(self, action: str) -> None:
        if action in (PREV, NEXT):
            if self._picker is not None:
                step_stage(self._picker, action)
                self.tick()
            return
        if self._on_key is not None:
            self._on_key(action)  # 暂停/继续 and 停止, as the keys do
            self.tick()  # shows 继续 / 正在停止 at once, not on the next look

    def _status(self, now: float) -> Status | None:
        report = run_report.active()
        self._picker = None
        task = data.current_task() if data.busy() else None
        if report is not None or task is not None:
            label = report.get("label") if report else None
            started = report.get("started") if report else getattr(task, "start_time", None)
            name = data.tr(str(getattr(task, "name", ""))) if task is not None else ""
            self._watching = (label, started, name, getattr(task, "start_time", None))
            self._end = None
            child = None
            if report is not None:
                for each in data.batch_children(data.task_by_name(label or "")):
                    if each.key == report.get("current"):
                        child = each.task
                        break
            runner = task
            paused = bool(getattr(runner, "paused", False))
            stopping = task is not None and not getattr(task, "enabled", True)
            status = running_status(report, task, child, paused, stopping, now)
            self._picker = getattr(child or task, "stage_picker", None) if paused else None
            return with_picker(status, self._picker)
        if self._watching is not None:
            label, started, name, task_started = self._watching
            self._watching = None
            finished = run_report.load_run(label, started) if label else None
            self._end = finished_status(finished, name, task_started, now)
            self._end_at = now
        if self._end is not None and now - self._end_at < LINGER_SECONDS:
            return self._end
        self._end = None
        return None

    def _hide(self, why: str) -> None:
        if self.bar is not None and self.bar.isVisible():
            self.bar.hide()
        self._note(f"hidden: {why}")

    def _note(self, state: str) -> None:
        """One log line each time the bar comes or goes, with why it went
        (Leo's 4K 2026-10-28: 「按暫停後我頂部狀態欄消失」, nothing in the log)."""
        if state != self._state:
            if self._state is not None or state != "hidden: no run":
                logger.info(f"game status bar: {state}")
            self._state = state


def start(parent, on_press: Callable[[str], None] | None = None) -> Watch:
    """``on_press`` gets hotkeys.PAUSE / hotkeys.STOP, as the keys do."""
    return Watch(parent, on_press)
