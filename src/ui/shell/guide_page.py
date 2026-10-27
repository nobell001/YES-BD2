"""使用说明: a short picture guide for new players (Leo, 2026-10-05).

Bullets, not paragraphs (Leo: 「條列式言簡意賅…提示即可」), on cards turned
left and right (Leo 2026-10-22 「要分類 卡片型式」「不要下拉 每個卡片左右切」):
微信通知 first, then the two ways to run the dailies with a nudge to look at
the settings once, then the three game settings 跑图 depends on, one each.
The game pictures are Leo's own screenshots with the parts to look at
circled (assets/ui/guide); a click shows one large.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QKeySequence, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.shell import motion, theme
from src.ui.shell.page import Page, pill
from src.ui.shell.widgets import (
    Button,
    Card,
    IconTile,
    Inset,
    Picture,
    Segmented,
    Separator,
    Text,
    hbox,
    tf,
    vbox,
)

ROOT = Path(__file__).resolve().parents[3]
GUIDE_DIR = ROOT / "assets" / "ui" / "guide"
# Remembers that the guide was opened once, so the sidebar stops pointing at it.
SEEN_FILE = ROOT / "configs" / "ui_guide.json"
WECHAT_NOTE = "免费版每天 5 则，一天跑一次只用 1 则。只发完成几项、失败原因和用时，不发账号名称。"


def picture_path(name: str) -> str:
    return str(GUIDE_DIR / f"{name}.png")


def seen(key: str = "seen") -> bool:
    """Whether the guide (or another first-visit note, by ``key``) was shown once."""
    try:
        return bool(json.loads(SEEN_FILE.read_text(encoding="utf-8")).get(key))
    except (OSError, ValueError, AttributeError):
        return False


def mark_seen(key: str = "seen") -> None:
    try:
        try:
            marks = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            marks = {}
        if not isinstance(marks, dict):
            marks = {}
        marks[key] = True
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(marks), encoding="utf-8")
    except OSError:
        pass


class GuidePicture(Picture):
    """A guide screenshot: keeps its shape, at most ``max_width`` wide; click to enlarge."""

    def __init__(self, name: str, max_width: int, parent=None):
        super().__init__(picture_path(name), parent, radius=theme.corner(4, 10))
        self._max_width = max_width
        native = self._pixmap.size()
        self._ratio = native.height() / native.width() if native.width() else 0.6
        self.setMaximumWidth(max_width)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._enlarge)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return round(min(width, self._max_width) * self._ratio)

    def sizeHint(self) -> QSize:
        return QSize(self._max_width, self.heightForWidth(self._max_width))

    def minimumSizeHint(self) -> QSize:
        return QSize(120, round(120 * self._ratio))

    def _enlarge(self) -> None:
        from src.ui.shell.home import PictureDialog

        PictureDialog(self._path, self).exec()

    def set_path(self, path: str | None) -> None:
        self._path = path or ""
        super().set_path(path)


class StepNumber(QWidget):
    """The violet numbered circle in front of each 跑图 step."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self._number = str(number)
        self.setFixedSize(26, 26)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary"))
        painter.drawEllipse(QRectF(self.rect()))
        font = QFont(self.font())
        font.setPixelSize(13)
        theme.strong(font, digits=True)
        painter.setFont(font)
        painter.setPen(theme.color("on_primary"))
        painter.drawText(QRectF(self.rect()), Qt.AlignCenter, self._number)


class SlidePicture(Picture):
    """A guide screenshot on a slide: shrinks with the slide (keeps its shape,
    never past ``max_width``), sits at the top left; click to enlarge."""

    def __init__(self, name: str, max_width: int, parent=None):
        super().__init__(picture_path(name), parent, radius=theme.corner(4, 10))
        native = self._pixmap.size()
        self._ratio = native.height() / native.width() if native.width() else 0.6
        self._max_width = max_width
        self.setMaximumSize(max_width, round(max_width * self._ratio))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._enlarge)

    def sizeHint(self) -> QSize:
        return QSize(self._max_width, round(self._max_width * self._ratio))

    def minimumSizeHint(self) -> QSize:
        return QSize(90, round(90 * self._ratio))

    def paintEvent(self, _event):
        # Top left in its box (Picture centres), corners rounded on the picture.
        fit = self._pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        if fit.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        box = QRectF(0, 0, fit.width(), fit.height())
        clip = QPainterPath()
        clip.addRoundedRect(box, self._radius, self._radius)
        painter.setClipPath(clip)
        ratio = self.devicePixelRatioF()
        key = (fit.width(), fit.height(), ratio)
        if self._scaled is None or self._scaled[0] != key:
            scaled = self._pixmap.scaled(
                round(fit.width() * ratio),
                round(fit.height() * ratio),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(ratio)
            self._scaled = (key, scaled)
        painter.drawPixmap(0, 0, self._scaled[1])

    def _enlarge(self) -> None:
        from src.ui.shell.home import PictureDialog

        PictureDialog(self._path, self).exec()

    def set_path(self, path: str | None) -> None:
        self._path = path or ""
        super().set_path(path)


class CategoryCard(Card):
    """One slide of the guide, drawn like a shadcn card: a thin outline, a
    bold title with a muted line under it, a rule, then the content."""

    def __init__(self, icon_name: str, title: str, desc: str, tag: str = "", tag_tone=None):
        super().__init__()
        outer = vbox(self, (20, 18, 20, 20), 14)
        head = hbox(None, (0, 0, 0, 0), 12)
        head.addWidget(IconTile(icon_name, 38, 20), 0, Qt.AlignTop)
        texts = vbox(None, (0, 0, 0, 0), 2)
        self.title = Text(title, "card_title", wrap=True)
        texts.addWidget(self.title)
        texts.addWidget(Text(desc, "card_desc", wrap=True))
        head.addLayout(texts, 1)
        if tag:
            head.addWidget(pill(tag, tag_tone), 0, Qt.AlignTop)
        outer.addLayout(head)
        outer.addWidget(Separator())
        self.column = vbox(None, (0, 0, 0, 0), 12)
        outer.addLayout(self.column, 1)

    def edge_colour(self):
        return theme.color("line2")


class Slides(QWidget):
    """The cards side by side behind a window one card wide; ``go`` slides
    to another (shadcn Carousel)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: list[QWidget] = []
        self.index = 0
        self._offset = motion.Tween(self, self._place, 260, 0.0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add(self, card: QWidget) -> None:
        card.setParent(self)
        self.cards.append(card)
        self._place()

    def go(self, index: int) -> None:
        index = max(0, min(index, len(self.cards) - 1))
        if index != self.index:
            self.index = index
            self._offset.go(float(index))

    def sizeHint(self) -> QSize:
        return QSize(640, 480)

    def minimumSizeHint(self) -> QSize:
        heights = [card.minimumSizeHint().height() for card in self.cards] or [0]
        return QSize(320, max(heights))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        width, gap = self.width(), 24
        for number, card in enumerate(self.cards):
            x = round((number - self._offset.value) * (width + gap))
            card.setGeometry(x, 0, width, self.height())
            # Cards out of the window stay hidden (and out of tab order).
            card.setVisible(-width - gap < x < width + gap)


class Dots(QWidget):
    """Which card is showing; the current one is a longer violet pill."""

    def __init__(self, count: int, on_pick: Callable[[int], None], parent=None):
        super().__init__(parent)
        self._count = count
        self._index = 0
        self._on_pick = on_pick
        self.setFixedSize(count * 14 + 12, 20)
        self.setCursor(Qt.PointingHandCursor)

    def set_index(self, index: int) -> None:
        self._index = index
        self.update()

    def _rects(self) -> list[QRectF]:
        rects, x = [], 0.0
        for number in range(self._count):
            width = 20.0 if number == self._index else 8.0
            rects.append(QRectF(x, 6, width, 8))
            x += width + 6
        return rects

    def mouseReleaseEvent(self, event):
        for number, rect in enumerate(self._rects()):
            if rect.adjusted(-3, -6, 3, 6).contains(event.position()):
                self._on_pick(number)
                return

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for number, rect in enumerate(self._rects()):
            on = number == self._index
            painter.setBrush(theme.color("primary") if on else theme.color("line2"))
            painter.drawRoundedRect(rect, 4, 4)


class GuidePage(Page):
    """Leo 2026-10-22 「不要下拉 每個卡片左右切 參考shadcn」: one card at a
    time, tabs for the three topics on top, arrows and dots under it."""

    interval = 60000
    TOPICS = (("wechat", "微信通知"), ("start", "开始跑日常"), ("map", "跑图设定"))

    def __init__(self, navigate: Callable[[str], None] | None = None, sidebar=None):
        super().__init__("shellGuide", "使用说明", "第一次用，先花一分钟看完")
        self._navigate = navigate
        self._sidebar = sidebar
        self._topic_of: list[str] = []

        self.tabs = Segmented(
            [key for key, _label in self.TOPICS],
            "wechat",
            labels=dict(self.TOPICS),
        )
        self.tabs.changed.connect(self._show_topic)
        self.body.addWidget(self.tabs, 0, Qt.AlignLeft)

        self.slides = Slides()
        self._build_wechat()
        self._build_start()
        self._build_map()
        self.body.addWidget(self.slides, 1)

        nav = hbox(None, (0, 0, 0, 0), 10)
        self.back = Button("", "secondary", "chevron-left", on_click=lambda: self.go(-1))
        self.next = Button("", "secondary", "chevron-right", on_click=lambda: self.go(1))
        for button in (self.back, self.next):
            button.setFixedWidth(40)
        self.dots = Dots(len(self.slides.cards), self.show_card)
        self.count = Text("", "muted")
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.dots, 0, Qt.AlignVCenter)
        nav.addWidget(self.next)
        nav.addSpacing(4)
        nav.addWidget(self.count, 0, Qt.AlignVCenter)
        nav.addStretch(1)
        self.body.addLayout(nav)

        for key, step in ((Qt.Key_Left, -1), (Qt.Key_Right, 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda s=step: self.go(s))
        self.show_card(0)
        # Leo 2026-10-09: always marked 必看 (it used to go once opened);
        # 2026-10-22 in a soft rose.
        if sidebar is not None and "guide" in getattr(sidebar, "items", {}):
            sidebar.items["guide"].set_badge("必看", "must")

    def showEvent(self, event):
        super().showEvent(event)
        if not seen():
            mark_seen()

    # ---------------------------------------------------------- turning

    def go(self, step: int) -> None:
        self.show_card(self.slides.index + step)

    def show_card(self, index: int) -> None:
        self.slides.go(index)
        index = self.slides.index
        self.dots.set_index(index)
        self.back.setEnabled(index > 0)
        self.next.setEnabled(index < len(self.slides.cards) - 1)
        self.count.set_text(f"{index + 1} / {len(self.slides.cards)}")
        self.tabs.set_value(self._topic_of[index])

    def _show_topic(self, topic: str) -> None:
        self.show_card(self._topic_of.index(topic))

    # ---------------------------------------------------------- pieces

    def _category(self, topic: str, icon_name: str, title: str, desc: str, tag="", tone=None):
        card = CategoryCard(icon_name, title, desc, tag, tone)
        self.slides.add(card)
        self._topic_of.append(topic)
        return card.column

    def _bullets(self, column, lines) -> None:
        for line in lines:
            row = hbox(None, (0, 0, 0, 0), 8)
            # as wide as the dot needs (a fixed 12 px cut it at 16 px text)
            dot = Text("•", "guide")
            row.addWidget(dot, 0, Qt.AlignTop)
            row.addWidget(Text(line, "guide", wrap=True), 1)
            column.addLayout(row)

    def _numbered(self, column, lines) -> None:
        for number, line in enumerate(lines, 1):
            row = hbox(None, (0, 0, 0, 0), 10)
            row.addWidget(StepNumber(number), 0, Qt.AlignTop)
            row.addWidget(Text(line, "guide", wrap=True), 1)
            column.addLayout(row)

    def _go(self, key: str) -> None:
        if self._navigate is not None:
            self._navigate(key)

    # ---------------------------------------------------------- 1 微信通知

    def _build_wechat(self) -> None:
        """跑完通知 (src/utils/run_notify.py): where to get a Server酱 SendKey
        and where it goes; the setup window in 设置 has the same steps."""
        column = self._category(
            "wechat",
            "send",
            "微信通知（跑完通知）",
            "一键完成日常跑完，结果自动发到你自己的微信",
            "新",
            "run",
        )
        self._numbered(
            column,
            (
                "打开 Server酱 网站：sct.ftqq.com/sendkey",
                "用微信扫码登录，照网页提示关注公众号",
                "复制 SCT 开头的那一串 SendKey",
                "回到工具：左边「设置」→「通知」→「跑完发到微信」，点「设定」",
                "贴上 SendKey，按「发测试」",
                "微信收到测试后按「完成」，以后每次跑完都会发",
            ),
        )
        buttons = hbox(None, (36, 2, 0, 0), 8)
        buttons.addWidget(
            Button("打开 Server酱 网站", "secondary", "external-link", "sm", on_click=self._site)
        )
        buttons.addWidget(
            Button("去设置", "secondary", "settings", "sm", on_click=lambda: self._go("settings"))
        )
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addWidget(Text(WECHAT_NOTE, "muted", wrap=True))
        column.addStretch(1)

    @staticmethod
    def _site() -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from src.utils import run_notify

        QDesktopServices.openUrl(QUrl(run_notify.SITE))

    # ---------------------------------------------------------- 2 开始跑

    def _build_start(self) -> None:
        column = self._category("start", "play", "开始跑日常", "两种跑法，两个按钮都在「首页」")
        row = hbox(None, (0, 0, 0, 0), 12)
        for title, tag, lines in (
            (
                "一键完成日常",
                "最常用",
                (
                    "游戏开在前面，工具直接点游戏",
                    "跑的时候不要动鼠标、键盘",
                    "游戏没开会先问你，再帮你开",
                ),
            ),
            (
                "在桌面分身跑",
                "边跑边用电脑",
                (
                    "游戏在另一个分身窗口里跑，缩小也照跑",
                    "电脑照常用，鼠标键盘不会被抢",
                    "要 Windows 专业版；怎么设定看左边「桌面分身」页",
                ),
            ),
        ):
            box = Inset()
            inner = vbox(box, (14, 12, 14, 14), 8)
            head = hbox(None, (0, 0, 0, 0), 8)
            head.addWidget(Text(title, "h2"), 1)
            head.addWidget(pill(tag))
            inner.addLayout(head)
            self._bullets(inner, lines)
            inner.addStretch(1)
            row.addWidget(box, 1)
        column.addLayout(row)

        column.addWidget(Separator())
        texts = vbox(None, (0, 0, 0, 0), 2)
        texts.addWidget(Text("先看一次设定", "h2"))
        texts.addWidget(Text("要跑哪些、跑几次、要不要做料理，都在这几页", "guide_note", wrap=True))
        column.addLayout(texts)
        buttons = hbox(None, (0, 0, 0, 0), 8)
        for key, label in (
            ("daily", "任务设定"),
            ("trade", "跑商"),
            ("map", "跑图"),
        ):
            buttons.addWidget(
                Button(label, "secondary", size="sm", on_click=lambda k=key: self._go(k))
            )
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addStretch(1)

    # ---------------------------------------------------------- 3 跑图

    def _step(self, number: int, title: str, important: bool = False):
        """One of the three 跑图 settings, a card of its own."""
        return self._category(
            "map",
            "map",
            title,
            tf("跑图前，游戏里先设好这三样（{n}/3）", n=number),
            "重要" if important else "",
            "must",
        )

    def _build_map(self) -> None:
        column = self._step(1, "技能按顺序放")
        row = hbox(None, (0, 0, 0, 0), 18)
        row.addWidget(SlidePicture("skills", 300), 0, Qt.AlignTop | Qt.AlignLeft)
        texts = vbox(None, (0, 4, 0, 0), 8)
        self._bullets(
            texts,
            (
                "右下角技能，按 1 → 4 放：探查、吸收、召集、压制",
                "用哪一组技能（TAB 切换的 1/2/3）都可以",
                "建议跑之前先放好",
            ),
        )
        texts.addStretch(1)
        row.addLayout(texts, 1)
        column.addLayout(row, 1)

        column = self._step(2, "左上角保持小地图")
        self._bullets(column, ("地图放大了，按小地图旁边的「−」缩回来",))
        row = hbox(None, (0, 0, 0, 0), 14)
        for name, label, tone in (
            ("minimap_small", "✓ 保持小地图", "ok"),
            ("minimap_big", "✗ 不要放大", "bad"),
        ):
            box = vbox(None, (0, 0, 0, 0), 8)
            box.addWidget(pill(label, tone), 0, Qt.AlignLeft)
            box.addWidget(SlidePicture(name, 340), 1, Qt.AlignTop | Qt.AlignLeft)
            row.addLayout(box, 1)
        column.addLayout(row, 1)

        column = self._step(3, "战场角色设定", important=True)
        row = hbox(None, (0, 0, 0, 0), 18)
        left = vbox(None, (0, 0, 0, 0), 10)
        self._bullets(left, ("点画面最下面中间的按钮",))
        left.addWidget(SlidePicture("battle_button", 260), 0, Qt.AlignLeft)
        self._bullets(
            left,
            (
                "「天赋技能使用角色设置」一定要选右边的「战场角色」",
                "上面的阵形选哪个都可以",
            ),
        )
        left.addStretch(1)
        row.addLayout(left, 2)
        row.addWidget(SlidePicture("battle_dialog", 620), 3, Qt.AlignTop | Qt.AlignLeft)
        column.addLayout(row, 1)
