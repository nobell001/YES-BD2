"""The 问题摘要 as a picture or a few lines of text (Leo 2026-10-09).

The picture is what the author reads first: the run, where it stopped and
why, the game window and screen, the last log lines, a few small frames of
the seconds before, and the game frame of that moment.  It always uses the light colours, whatever the app's look, so
every player's picture reads the same, and Simplified Chinese, whatever the
tool's language, since it is for the author.  The text is four short lines for
places that take no pictures (Leo: 「不要一大串 只複製重要的」).
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen

from src.tasks import problem_report

ICON_FILE = Path(__file__).resolve().parents[3] / "icons" / "icon.png"
SUPPORTED = ((1920, 1080), (2560, 1440), (3840, 2160))

WIDTH = 820
PAD = 22
CARD_PAD = 16
# Drawn at twice the size so it stays sharp after a comment box shrinks it.
SCALE = 2

INK = QColor("#1F1D29")
INK2 = QColor("#4A4759")
INK3 = QColor("#5C596B")
GROUND = QColor("#F4F3F9")
CARD = QColor("#FFFFFF")
LINE = QColor("#EEECF6")
ACCENT = QColor("#7467C4")
BAD = QColor("#B4475F")
BAD_SOFT = QColor("#FAEBEF")
OK = QColor("#2E7A70")
OK_SOFT = QColor("#E4F1EF")
WARN = QColor("#9A6A0C")
WARN_SOFT = QColor("#FAF0D7")



def t(text: str) -> str:
    """The picture and text are for the author: always Simplified Chinese,
    whatever language the player's tool shows (the log lines are too)."""
    return text


def tf(template: str, **values) -> str:
    return template.format(**values)


HOW_TEXT = {"stop": "手动停止", "error": "程序出错", "fail": "失败"}


# ------------------------------------------------------------------ facts


def _local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts).astimezone()


def _size_supported(size) -> bool:
    return any(abs(size[0] - w) <= 2 and abs(size[1] - h) <= 2 for w, h in SUPPORTED)


def ended_text(record: dict) -> str:
    return t(problem_report.ENDED_TEXT.get(record.get("ended") or "", "跑完了"))


def where_text(record: dict) -> str:
    """'每周跑图 · 找不到第 12 章卡带' for where the run stopped."""
    problem = record.get("problem") or {}
    if not problem:
        return t("没有失败，也没有中途停下")
    reason = problem.get("stage") or problem.get("note") or t(HOW_TEXT.get(problem.get("how"), ""))
    parts = [t(problem.get("task") or ""), t(reason)]
    if problem.get("stage") and problem.get("note") and problem["note"] not in problem["stage"]:
        parts.append(t(problem["note"]))
    return " · ".join(part for part in parts if part)


def size_text(env: dict) -> str:
    """'1467×824 窗口化' for the game window."""
    size = env.get("game_size")
    if not size:
        return ""
    mode = t(env.get("window_mode") or "")
    return f"{size[0]}×{size[1]} {mode}".strip()


def screen_parts(env: dict) -> list[str]:
    parts = [size_text(env)] if env.get("game_size") else []
    if env.get("scaling"):
        parts.append(tf("缩放 {n}%", n=env["scaling"]))
    if "hdr" in env:
        parts.append(t("HDR 开") if env["hdr"] else t("HDR 关"))
    if env.get("ui_language"):
        parts.append(env["ui_language"])
    if "clone" in env:
        parts.append(t("用了桌面分身") if env["clone"] else t("没用分身"))
    return parts


def last_line(record: dict) -> str:
    """The last warning or error (else the last line), with how often it came.

    A line that only repeats where the run stopped (the 停在 line, which now
    carries the reason) is passed over, so 「最后」 adds something.
    """
    logs = problem_report.logs_of(record)
    stage = str((record.get("problem") or {}).get("stage") or "").strip().rstrip("。.")
    if stage:
        logs = [entry for entry in logs if stage not in str(entry.get("text") or "")]
    if not logs:
        return ""
    worst = [entry for entry in logs if entry.get("level", 0) >= 30]
    entry = (worst or logs)[-1]
    text = str(entry.get("text") or "")
    if entry.get("count", 1) > 1:
        text = tf("{text}，重复 {n} 次", text=text, n=entry["count"])
    return text


def version_text(env: dict) -> str:
    """「v0.1.11」; the saved version may already start with v."""
    version = str(env.get("version") or "").strip().lstrip("vV")
    return f"v{version}" if version else ""


def summary_text(record: dict) -> str:
    """The four lines 「复制文字」 puts on the clipboard."""
    env = problem_report.env_of(record)
    head = f"【YES-BD2 {version_text(env)}】".replace(" 】", "】")
    lines = [f"{head}{t(record.get('label') or '')} · {ended_text(record)}"]
    where = where_text(record)
    lines.append(tf("停在：{where}", where=where) if record.get("problem") else where)
    parts = screen_parts(env)
    if parts:
        lines.append(tf("画面：{parts}", parts=" · ".join(parts)))
    last = last_line(record)
    if last:
        lines.append(tf("最后：{text}", text=last))
    return "\n".join(lines)


def file_name(record: dict) -> str:
    moment = _local(float(record.get("finished") or time.time()))
    return f"YES-BD2-{t('问题')}-{moment:%m-%d-%H%M}.png"


# ---------------------------------------------------------------- picture


class _Pen:
    """Lays out and paints top to bottom; run once to measure, once to paint."""

    def __init__(self, painter: QPainter | None, family: str):
        self.p = painter
        self.family = family
        self.y = 0.0

    def font(self, size: float, bold: bool = False, mono: bool = False) -> QFont:
        font = QFont(self.family)
        if mono:
            font.setStyleHint(QFont.Monospace)
        font.setPixelSize(round(size))
        font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Medium)
        return font

    def text_height(self, text: str, font: QFont, width: float) -> float:
        metrics = QFontMetricsF(font)
        rect = metrics.boundingRect(QRectF(0, 0, width, 100000), Qt.TextWordWrap, text)
        return max(metrics.height(), rect.height())

    def text(self, x, y, width, text, font, colour, align=Qt.AlignLeft) -> float:
        height = self.text_height(text, font, width)
        if self.p is not None:
            self.p.setFont(font)
            self.p.setPen(colour)
            self.p.drawText(QRectF(x, y, width, height), int(align) | Qt.TextWordWrap, text)
        return height

    def round_rect(self, rect: QRectF, colour: QColor, radius: float) -> None:
        if self.p is not None:
            self.p.setPen(Qt.NoPen)
            self.p.setBrush(colour)
            self.p.drawRoundedRect(rect, radius, radius)


def _paint(pen: _Pen, record: dict, frame, before=()) -> float:
    env = problem_report.env_of(record)
    inner = WIDTH - 2 * PAD
    y = PAD

    # Head: logo, title, version and time, how it ended.
    if pen.p is not None:
        logo = QImage(str(ICON_FILE)) if ICON_FILE.exists() else QImage()
        if not logo.isNull():
            pen.p.drawImage(QRectF(PAD, y, 40, 40), logo)
        else:
            pen.round_rect(QRectF(PAD, y, 40, 40), ACCENT, 11)
    title_x = PAD + 52
    pen.text(title_x, y, 400, t("YES-BD2 问题摘要"), pen.font(20, True), INK)
    finished = float(record.get("finished") or time.time())
    sub = " · ".join(p for p in (version_text(env), f"{_local(finished):%Y-%m-%d %H:%M}") if p)
    pen.text(title_x, y + 26, 400, sub, pen.font(13), INK3)
    state = ended_text(record)
    bad = record.get("ended") != problem_report.DONE
    state_font = pen.font(15)
    state_width = QFontMetricsF(state_font).horizontalAdvance(state) + 28
    state_rect = QRectF(WIDTH - PAD - state_width, y + 5, state_width, 30)
    pen.round_rect(state_rect, BAD_SOFT if bad else OK_SOFT, 15)
    if pen.p is not None:
        pen.p.setFont(state_font)
        pen.p.setPen(BAD if bad else OK)
        pen.p.drawText(state_rect, Qt.AlignCenter, state)
    y += 54

    # Facts.
    rows = []
    counts = record.get("counts")
    run = t(record.get("label") or "")
    if counts:
        run += "（" + tf(
            "完成 {done} · 跳过 {skip} · 失败 {fail}",
            done=counts.get("done", 0), skip=counts.get("skip", 0), fail=counts.get("fail", 0),
        ) + "）"
    rows.append((t("这次跑的"), run, None))
    rows.append((t("停在") if record.get("problem") else t("结果"), where_text(record),
                 BAD if record.get("problem") else None))
    size = env.get("game_size")
    if size:
        shown = size_text(env)
        if not _size_supported(size):
            shown += "  " + t("（工具测过：1920×1080、2560×1440、3840×2160）")
        rows.append((t("游戏画面"), shown, None if _size_supported(size) else WARN))
    screen = []
    if env.get("monitor"):
        screen.append(f"{env['monitor'][0]}×{env['monitor'][1]}")
    if env.get("scaling"):
        screen.append(tf("缩放 {n}%", n=env["scaling"]))
    if "hdr" in env:
        screen.append(t("HDR 开") if env["hdr"] else t("HDR 关"))
    if screen:
        rows.append((t("显示器"), " · ".join(screen), None))
    other = []
    if env.get("ui_language"):
        other.append(tf("工具语言：{name}", name=env["ui_language"]))
    if "clone" in env:
        other.append(t("用了桌面分身") if env["clone"] else t("没用分身"))
    if other:
        rows.append((t("其他"), " · ".join(other), None))
    y = _card(pen, y, inner, lambda p, top: _rows(p, top, inner, rows))

    # The last lines.
    logs = problem_report.logs_of(record)
    if logs:
        title = t("停下前的记录") if record.get("problem") else t("最后的记录")
        y = _card(pen, y, inner, lambda p, top: _logs(p, top, inner, title, logs))

    # The seconds before, oldest first.
    shots = [(at, image) for at, image in before if image is not None and not image.isNull()]
    if shots:
        at = float((record.get("problem") or {}).get("at") or record.get("finished") or 0)
        y = _card(pen, y, inner, lambda p, top: _strip(p, top, inner, shots, at))

    # The game at that moment.
    if frame is not None and not frame.isNull():
        def picture(p, top):
            width = inner - 2 * CARD_PAD
            height = p.text(PAD + CARD_PAD, top, width, t("停下前的游戏画面"), p.font(14), INK3)
            shown = width * frame.height() / max(1, frame.width())
            if p.p is not None:
                p.p.drawImage(QRectF(PAD + CARD_PAD, top + height + 8, width, shown), frame)
            return height + 8 + shown
        y = _card(pen, y, inner, picture)

    y += pen.text(PAD, y, inner, t("由 YES-BD2 生成 · 不含账号和电脑用户名"), pen.font(12), INK3,
                  Qt.AlignHCenter)
    return y + PAD


def _card(pen: _Pen, y: float, inner: float, body) -> float:
    """A white card around ``body(pen, top) -> height``, measured before painting."""
    height = body(_Pen(None, pen.family), y + CARD_PAD)
    pen.round_rect(QRectF(PAD, y, inner, height + 2 * CARD_PAD), CARD, 14)
    if pen.p is not None:
        body(pen, y + CARD_PAD)
    return y + height + 2 * CARD_PAD + 12


def _rows(pen: _Pen, top: float, inner: float, rows) -> float:
    key_width = 110
    x = PAD + CARD_PAD
    value_width = inner - 2 * CARD_PAD - key_width
    used = 0.0
    font = pen.font(15)
    for index, (key, value, tone) in enumerate(rows):
        y = top + used
        height = max(
            pen.text_height(key, font, key_width), pen.text_height(value, font, value_width)
        ) + 12
        pen.text(x, y + 6, key_width, key, font, INK3)
        pen.text(x + key_width, y + 6, value_width, value, font, tone or INK)
        if index < len(rows) - 1 and pen.p is not None:
            pen.p.setPen(QPen(LINE, 1))
            pen.p.drawLine(QPointF(x, y + height), QPointF(x + inner - 2 * CARD_PAD, y + height))
        used += height
    return used


def _logs(pen: _Pen, top: float, inner: float, title: str, logs) -> float:
    x = PAD + CARD_PAD
    width = inner - 2 * CARD_PAD
    used = pen.text(x, top, width, title, pen.font(14), INK3) + 8
    font = pen.font(13.5, mono=True)
    for entry in logs:
        moment = _local(float(entry.get("at") or 0))
        text = f"{moment:%H:%M:%S}  {entry.get('text') or ''}"
        if entry.get("count", 1) > 1:
            text += "  " + tf("（重复 {n} 次）", n=entry["count"])
        colour = BAD if entry.get("level", 0) >= 30 else INK2
        used += pen.text(x, top + used, width, text, font, colour) + 3
    return used


STRIP_GAP = 8


def _strip(pen: _Pen, top: float, inner: float, shots, at: float) -> float:
    """「停下前几秒」: the small frames in a row, each with how long before."""
    x = PAD + CARD_PAD
    width = inner - 2 * CARD_PAD
    used = pen.text(x, top, width, t("停下前几秒（从早到晚）"), pen.font(14), INK3) + 8
    count = problem_report.BEFORE_FRAMES
    thumb = (width - STRIP_GAP * (count - 1)) / count
    tall = max(
        thumb * image.height() / max(1, image.width()) for _when, image in shots
    )
    font = pen.font(12.5)
    label = 0.0
    for index, (when, image) in enumerate(shots):
        left = x + index * (thumb + STRIP_GAP)
        shown = thumb * image.height() / max(1, image.width())
        if pen.p is not None:
            pen.p.drawImage(QRectF(left, top + used, thumb, shown), image)
        seconds = max(1, round(at - float(when or at))) if at else 0
        text = tf("{n} 秒前", n=seconds) if seconds else ""
        label = max(label, pen.text(
            left, top + used + tall + 4, thumb, text, font, INK3, Qt.AlignHCenter
        ))
    return used + tall + 4 + label


def _family() -> str:
    app = QGuiApplication.instance()
    return app.font().family() if app is not None else ""


def render(record: dict) -> QImage:
    """The 问题摘要 picture of a record."""
    frame = QImage(record["frame_path"]) if record.get("frame_path") else None
    before = [
        (item.get("at"), QImage(item["path"]))
        for item in record.get("before_paths") or []
        if item.get("path")
    ]
    family = _family()
    height = _paint(_Pen(None, family), record, frame, before)
    image = QImage(round(WIDTH * SCALE), round(height * SCALE), QImage.Format_RGB32)
    image.fill(GROUND)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.scale(SCALE, SCALE)
    _paint(_Pen(painter, family), record, frame, before)
    painter.end()
    return image


# ---------------------------------------------------------------- actions


def copy_image(record: dict) -> None:
    QGuiApplication.clipboard().setImage(render(record))


def copy_text(record: dict) -> None:
    QGuiApplication.clipboard().setText(summary_text(record))


def desktop() -> Path:
    found = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    return Path(found) if found else Path.home() / "Desktop"


def save_image(record: dict, folder: Path | None = None) -> Path | None:
    """Save the picture on the desktop; returns where, or None if it failed."""
    folder = folder or desktop()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = folder / file_name(record)
    return path if render(record).save(str(path), "PNG") else None
