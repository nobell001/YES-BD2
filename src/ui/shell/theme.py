# ruff: noqa: E501
"""Colours, sizes and the shared style sheet of the new main window.

淡紫 is the light side and 深色 its dark twin (Leo, 2026-10-05; they
replaced the first 浅色 and the blue-grey 深色): lavender-grey or
purple-black ground, cards with large corners, round outline icons, the
selected page marked with a violet circle, pill buttons.  Both share one set
of shapes (``SHAPES``); only the colours differ.  Everything reads its
corners from ``radius()`` / ``corner()`` instead of fixed numbers.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QFont
from qfluentwidgets import Theme, isDarkTheme, qconfig


def _mix(colour: str, base: str, amount: float) -> str:
    """``colour`` laid over ``base`` at ``amount`` opacity, as an opaque #RRGGBB."""
    top, bottom = QColor(colour), QColor(base)
    mixed = QColor(
        round(bottom.red() + (top.red() - bottom.red()) * amount),
        round(bottom.green() + (top.green() - bottom.green()) * amount),
        round(bottom.blue() + (top.blue() - bottom.blue()) * amount),
    )
    return mixed.name().upper()


# Task kinds for the icon tiles: 领取, 战斗, 养成, 跑商, 周常, 跑图 and the rest.
KINDS = ("claim", "fight", "grow", "trade", "week", "map", "plain")

_LAV = "#7467C4"
_LAV_SOFT = "#EFEDF6"

# 淡紫, with the exact colours of the approved draft (Leo, 2026-10-05).
LIGHT = {
    "bg": "#F4F3F9",
    # The sidebar is a rounded panel on the ground (painted by the sidebar).
    "side": "#EEECF6",
    "side_line": "transparent",
    "card": "#FFFFFF",
    # cards float without an outline, as in the draft
    "card_line": "#FFFFFF",
    "inset": "#F6F5FA",
    "line": "#EEECF6",
    "line2": "#DEDBEA",
    "track": "#EEECF6",
    # Dark text on a light ground reads thinner than light text on dark
    # (Leo, 2026-10-05), so the greys sit a step darker than the draft.
    "ink": "#1F1D29",
    "ink2": "#4A4759",
    "ink3": "#5C596B",
    "primary": _LAV,
    "primary_hover": "#675AB5",
    "on_primary": "#FFFFFF",
    "ghost_ink": "#5B4FB0",
    "ghost_line": "#DEDBEA",
    "accent": _LAV,
    "accent_soft": _LAV_SOFT,
    "on_accent": "#FFFFFF",
    "run": _LAV,
    "run_bar": _LAV,
    # a cool, quiet green and a dusty rose: brighter ones jumped out next to
    # the violet (Leo, 2026-10-05)
    "ok": "#2E7A70",
    "ok_soft": "#E4F1EF",
    "warn": "#B98012",
    "warn_soft": "#FAF0D7",
    "bad": "#D4788C",
    "bad_soft": "#FAEBEF",
    "skip": "#C9C5D8",
    "done_line": "#FFFFFF",
    "shot": "#1B1A26",
    # soft violet-grey card shadow (Leo, 2026-10-05: the light look needs depth)
    "shadow": "#4A3F8C",
    # sidebar: icons sit in round outlines; the selected page is a white
    # pill whose icon circle is filled violet
    "nav_icon": "#4F4B60",
    "nav_on": "#FFFFFF",
    "nav_on_line": "transparent",
    "nav_on_ink": "#1F1D29",
    "nav_on_icon": "#FFFFFF",
    "nav_on_circle": _LAV,
    "ring": "#DEDBEA",
    # counts on the right of the sidebar sit in small soft chips
    "badge": _LAV_SOFT,
    "badge_ink": "#5C596B",
    "badge_on": _LAV_SOFT,
    "badge_on_ink": "#5B4FB0",
    "badge_run": _LAV_SOFT,
    "badge_run_ink": _LAV,
    "badge_ok": "#E4F1EF",
    # 必看 on 使用说明: the dusty rose, a step deeper so the small text reads
    # (Leo 2026-10-22 「沒那麼違和的紅字」)
    "badge_must": "#FAEBEF",
    "badge_must_ink": "#BF5F78",
    "box": "#FFFFFF",
    "box_line": "#FFFFFF",
    "row_on": _LAV_SOFT,
    "row_on_bar": "transparent",
    "pill": "#F1EFF7",
    "pill_line": "#F1EFF7",
    "pill_run": _LAV_SOFT,
    "pill_run_ink": _LAV,
    "tag": _LAV_SOFT,
    "tag_ink": _LAV,
    # the dish pictures carry their own frame: no outline around them
    "dish_on_line": "transparent",
    "dish_badge": _LAV,
    "dish_badge_ink": "#FFFFFF",
    # 跑图: finished cartridges, maps and the week bar
    "map_done": _LAV,
    "today": _LAV_SOFT,
    "today_ink": _LAV,
    "pick": _LAV,
    "pick_bg": _LAV_SOFT,
    # task icons: violet line icons on a soft violet circle (the draft)
    **{f"kind_{kind}": _LAV for kind in KINDS},
    **{f"kind_{kind}_bg": _LAV_SOFT for kind in KINDS},
}

# 深色 (Leo approved the draft 2026-10-05): the same look on a purple-black
# ground, cards a little lighter, the same violet for buttons and selections.
_NIGHT = "#7467C4"
_NIGHT_CARD = "#23222E"
_NIGHT_SOFT = "#2C2A3B"

DARK = {
    "bg": "#16151D",
    # The sidebar is a lighter rounded panel on the ground.
    "side": "#2B2A37",
    "side_line": "transparent",
    "card": _NIGHT_CARD,
    # cards float without an outline, as in the draft
    "card_line": _NIGHT_CARD,
    "inset": "#1E1D27",
    "line": "#2B2A37",
    "line2": "#383646",
    "track": "#2B2A37",
    "ink": "#ECEAF4",
    "ink2": "#B5B2C4",
    "ink3": "#9B98AD",
    "primary": _NIGHT,
    "primary_hover": "#8A80D8",
    "on_primary": "#FFFFFF",
    "ghost_ink": "#B4ABF6",
    "ghost_line": "#383646",
    "accent": _NIGHT,
    "accent_soft": _NIGHT_SOFT,
    "on_accent": "#FFFFFF",
    "run": "#B4ABF6",
    "run_bar": _NIGHT,
    "ok": "#93CFC5",
    "ok_soft": "#1F3534",
    "warn": "#E3B04B",
    "warn_soft": _mix("#E3B04B", _NIGHT_CARD, 0.16),
    "bad": "#D4788C",
    "bad_soft": _mix("#D4788C", _NIGHT_CARD, 0.16),
    "skip": "#4C4A5B",
    "done_line": _NIGHT_CARD,
    "shot": "#0E0D13",
    "shadow": "#000000",
    # sidebar: the selected page is a card-coloured pill whose icon circle
    # is filled violet
    "nav_icon": "#C6C3D5",
    "nav_on": _NIGHT_CARD,
    "nav_on_line": "transparent",
    "nav_on_ink": "#ECEAF4",
    "nav_on_icon": "#FFFFFF",
    "nav_on_circle": _NIGHT,
    "ring": "#383646",
    "badge": _NIGHT_SOFT,
    "badge_ink": "#9B98AD",
    "badge_on": _NIGHT_SOFT,
    "badge_on_ink": "#B4ABF6",
    "badge_run": _NIGHT_SOFT,
    "badge_run_ink": "#B4ABF6",
    "badge_ok": "#1F3534",
    "badge_must": _mix("#D4788C", _NIGHT_CARD, 0.18),
    "badge_must_ink": "#E597A8",
    "box": _NIGHT_CARD,
    "box_line": _NIGHT_CARD,
    "row_on": _NIGHT_SOFT,
    "row_on_bar": "transparent",
    "pill": "#262532",
    "pill_line": "#262532",
    "pill_run": _NIGHT_SOFT,
    "pill_run_ink": "#B4ABF6",
    "tag": _NIGHT_SOFT,
    "tag_ink": "#B4ABF6",
    "dish_on_line": "transparent",
    "dish_badge": _NIGHT,
    "dish_badge_ink": "#FFFFFF",
    "map_done": _NIGHT,
    "today": _NIGHT_SOFT,
    "today_ink": "#B4ABF6",
    "pick": _NIGHT,
    "pick_bg": _NIGHT_SOFT,
    # task icons: violet line icons on a soft violet circle (the draft)
    **{f"kind_{kind}": "#9A8FEA" for kind in KINDS},
    **{f"kind_{kind}_bg": _NIGHT_SOFT for kind in KINDS},
}

# Corners and how icons and the sidebar are drawn (both themes).
SHAPES = {
    "card": 20,
    "button": 0,
    "inset": 14,
    "scale": 2.6,
    "round_icons": True,
    "side_inset": 10,
    # total opacity of the card shadow, split over its layers
    "shadow": 0.11,
}


def shape(name: str):
    return SHAPES[name]


def radius() -> int:
    """Corner of cards and framed boxes."""
    return int(shape("card"))


def corner(base: float, cap: float | None = None) -> float:
    """A corner of ``base`` px in the first small-corner design, scaled to this round look."""
    value = base * float(shape("scale"))
    return min(value, cap) if cap is not None else value


def seg_item_radius(height: float) -> float:
    """Corner of the chosen option's pill in a segmented row (as in the style sheet)."""
    return min(13.0, height / 2) if shape("button") == 0 else 4.0


def body_weight() -> QFont.Weight:
    """Weight of plain (not bold) text: Regular.  Medium was picked for Noto
    (2026-10-05); the Windows UI fonts have no Medium, and Regular is how
    they are drawn evenly (2026-10-27)."""
    return QFont.Weight.Normal


# Chinese below this size is never bold: the strokes of a dense character
# (the three bars of 精) have no pixel between them and run together
# (Leo 2026-10-27, 「不行就不要粗體」).  MaaEnd uses no bold at all.
BOLD_MIN_PX = 20


def strong(font: QFont, digits: bool = False) -> QFont:
    """``font`` bold where bold stays readable: from BOLD_MIN_PX up, or at
    any size for text that is only digits / Latin letters (``digits``)."""
    size = font.pixelSize()
    if size <= 0:
        size = round(font.pointSizeF() * 96 / 72)
    font.setBold(digits or size >= BOLD_MIN_PX)
    return font


def body_font(base: QFont) -> QFont:
    """``base`` with the plain-text weight of the current look."""
    font = QFont(base)
    font.setWeight(body_weight())
    return font


def tokens() -> dict[str, str]:
    return DARK if isDarkTheme() else LIGHT


def color(name: str, alpha: float | None = None) -> QColor:
    value = QColor(tokens()[name])
    if alpha is not None:
        value.setAlphaF(max(0.0, min(1.0, alpha)))
    return value


def kind_colours(kind: str) -> tuple[QColor, QColor]:
    """Icon and tile colour of a task kind (an unknown kind looks like "plain")."""
    if kind not in KINDS:
        kind = "plain"
    return color(f"kind_{kind}"), color(f"kind_{kind}_bg")


def rgba(name: str, alpha: float) -> str:
    value = QColor(tokens()[name])
    return f"rgba({value.red()},{value.green()},{value.blue()},{alpha:.3f})"


def theme_mode() -> str:
    """'light' (淡紫) / 'dark' / 'auto', the app's own setting (ui_config.json)."""
    mode = qconfig.themeMode.value
    if mode == Theme.LIGHT:
        return "light"
    if mode == Theme.DARK:
        return "dark"
    return "auto"


def set_theme_mode(mode: str) -> None:
    """Switch and remember 淡紫 / 深色 / 跟随系统."""
    from qfluentwidgets import setTheme

    theme = {"light": Theme.LIGHT, "dark": Theme.DARK}.get(mode, Theme.AUTO)
    if qconfig.themeMode.value != theme:
        setTheme(theme, save=True, lazy=True)


def sync_fluent_accent() -> None:
    """Fluent's own controls (text boxes, spin boxes, message boxes) take the
    tool's violet instead of their default teal (2026-10-22 check)."""
    from qfluentwidgets import setThemeColor

    setThemeColor(QColor(tokens()["primary"]), lazy=True)


def toggle_dark() -> None:
    set_theme_mode("light" if isDarkTheme() else "dark")


class _ThemeWatcher(QObject):
    """Calls every registered callback after a theme change finished."""

    def __init__(self):
        super().__init__()
        self._callbacks: list[tuple[object, Callable[[], None]]] = []
        qconfig.themeChangedFinished.connect(self._fire)

    def add(self, owner, callback: Callable[[], None]) -> None:
        self._callbacks.append((owner, callback))
        try:
            owner.destroyed.connect(lambda *_: self._drop(owner))
        except Exception:
            pass

    def _drop(self, owner) -> None:
        self._callbacks = [(o, c) for o, c in self._callbacks if o is not owner]

    def _fire(self) -> None:
        for _owner, callback in list(self._callbacks):
            try:
                callback()
            except RuntimeError:
                # The C++ widget went away between the change and this call.
                continue


_watcher: _ThemeWatcher | None = None


def on_theme_changed(owner, callback: Callable[[], None]) -> None:
    global _watcher
    if _watcher is None:
        _watcher = _ThemeWatcher()
    _watcher.add(owner, callback)


def style_sheet() -> str:
    """The style shared by the sidebar and every new page."""
    t = tokens()
    inset = int(shape("inset"))
    pill = shape("button") == 0
    # Pill buttons in 淡紫: the corner is half of each button height.
    button, button_lg, button_sm = (16, 19, 14) if pill else (shape("button"),) * 3
    seg, seg_item = (16, 13) if pill else (shape("button"), 4)
    side_bg = "transparent" if shape("side_inset") else t["side"]
    # Plain text is Regular, see body_weight().
    body_weight = " font-weight: 400;"
    secondary = (
        f"background: {t['inset']}; color: {t['ink']}; border: none;"
        if pill
        else f"background: {t['card']}; color: {t['ink']}; border: 1px solid {t['line2']};"
    )
    return f"""
QWidget#shellPage, QWidget#shellView {{ background: {t["bg"]}; }}
QAbstractScrollArea[shell="true"] {{ background: {t["bg"]}; border: none; }}
QWidget#shellSide {{ background: {side_bg}; border-right: 1px solid {t["side_line"]}; }}
QLabel {{ color: {t["ink"]}; background: transparent;{body_weight} }}
QLabel[role="h1"] {{ font-size: 23px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; }}
QLabel[role="h3"] {{ font-size: 14px; }}
QLabel[role="sub"] {{ color: {t["ink2"]}; font-size: 13px; }}
QLabel[role="muted"] {{ color: {t["ink3"]}; font-size: 12px; }}
QLabel[role="eyebrow"] {{ color: {t["ink3"]}; font-size: 12px; }}
QLabel[role="guide"] {{ font-size: 16px; }}
QLabel[role="guide_note"] {{ color: {t["ink2"]}; font-size: 15px; }}
QLabel[role="card_title"] {{ font-size: 17px; }}
QLabel[role="card_desc"] {{ color: {t["ink2"]}; font-size: 13px; }}
QLabel[role="pill"][tone="must"] {{ color: {t["badge_must_ink"]}; background: {t["badge_must"]}; border-color: {t["badge_must"]}; }}
QLabel[role="big"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="huge"] {{ font-size: 30px; font-weight: 700; }}
QLabel[role="big"][tone="ok"] {{ color: {t["ok"]}; }}
QLabel[role="big"][tone="bad"] {{ color: {t["bad"]}; }}
QLabel[role="big"][tone="warn"] {{ color: {t["warn"]}; }}
QLabel[role="big"][tone="run"] {{ color: {t["run"]}; }}
QLabel[role="ok"] {{ color: {t["ok"]}; }}
QLabel[role="bad"] {{ color: {t["bad"]}; }}
QLabel[role="warn"] {{ color: {t["warn"]}; }}
QLabel[role="pill"] {{ color: {t["ink2"]}; background: {t["pill"]}; border: 1px solid {t["pill_line"]};
    border-radius: 11px; padding: 2px 10px; font-size: 12px; }}
QLabel[role="pill"][tone="ok"] {{ color: {t["ok"]}; background: {t["ok_soft"]}; border-color: {t["ok_soft"]}; }}
QLabel[role="pill"][tone="run"] {{ color: {t["pill_run_ink"]}; background: {t["pill_run"]}; border-color: {t["pill_run"]}; }}
QLabel[role="pill"][tone="warn"] {{ color: {t["warn"]}; background: {t["warn_soft"]}; border-color: {t["warn_soft"]}; }}
QLabel[role="pill"][tone="bad"] {{ color: {t["bad"]}; background: {t["bad_soft"]}; border-color: {t["bad_soft"]}; }}
QLabel[role="tag"] {{ color: {t["tag_ink"]}; background: {t["tag"]}; border-radius: 3px;
    padding: 0px 5px; font-size: 11px; }}

QFrame[card="true"] {{ background: transparent; border: none; }}
QFrame[box="true"] {{ background: {t["box"]}; border: 1px solid {t["box_line"]}; border-radius: {inset}px; }}
QFrame[inset="true"] {{ background: {t["inset"]}; border: none; border-radius: {inset}px; }}
QFrame[inset="true"][outlined="true"] {{ border: 1px solid transparent; }}
QFrame[inset="true"][outlined="true"][bad="true"] {{ border: 1px solid {t["bad"]}; }}
QFrame[sep="true"] {{ background: {t["line"]}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{ font-size: 13px; border-radius: {button}px; min-height: 32px; max-height: 32px;
    padding: 0px 14px; }}
QPushButton[kind="primary"] {{ background: {t["primary"]}; color: {t["on_primary"]}; border: none; }}
QPushButton[kind="primary"]:hover {{ background: {t["primary_hover"]}; }}
QPushButton[kind="primary"]:disabled {{ background: {t["line2"]}; color: {t["ink3"]}; }}
QPushButton[kind="secondary"] {{ {secondary} }}
QPushButton[kind="secondary"]:hover {{ background: {t["accent_soft"] if pill else t["inset"]}; }}
QPushButton[kind="secondary"]:disabled {{ color: {t["ink3"]}; }}
QPushButton[kind="ghost"] {{ background: {t["accent_soft"] if pill else "transparent"}; color: {t["ghost_ink"]};
    border: 1px solid {"transparent" if pill else t["ghost_line"]}; }}
QPushButton[kind="ghost"]:hover {{ background: {rgba("ink", 0.06)}; }}
QPushButton[kind="ghost"]:disabled {{ color: {t["ink3"]}; }}
QPushButton[kind="danger"] {{ background: {t["card"]}; color: {t["bad"]}; border: 1px solid {t["line2"]}; }}
QPushButton[kind="danger"]:hover {{ background: {t["bad_soft"]}; }}
QPushButton[kind="icon"] {{ background: transparent; border: 1px solid {t["line2"]}; padding: 0px;
    min-width: 32px; max-width: 32px; }}
QPushButton[kind="icon"]:hover {{ background: {rgba("ink", 0.06)}; }}
QPushButton[kind="flat"] {{ background: transparent; border: none; color: {t["ink2"]}; padding: 0px 6px; }}
QPushButton[kind="flat"]:hover {{ color: {t["ink"]}; }}
QPushButton[kind="chip"] {{ background: transparent; color: {t["ink2"]}; border: 1px solid transparent; padding: 0px 8px; }}
QPushButton[kind="chip"]:hover {{ background: {t["accent_soft"]}; color: {t["accent"]}; border: 1px solid {t["accent"]}; }}
QPushButton[size="lg"] {{ min-height: 38px; max-height: 38px; font-size: 14px; padding: 0px 18px;
    border-radius: {button_lg}px; }}
QPushButton[size="sm"] {{ min-height: 28px; max-height: 28px; font-size: 12px; padding: 0px 10px;
    border-radius: {button_sm}px; }}

QFrame[segmented="true"] {{ background: {t["inset"]}; border: 1px solid {rgba("ink3", 0.38)};
    border-radius: {seg}px; }}
QPushButton[seg="true"] {{ background: transparent; color: {t["ink2"]}; border: none; border-radius: {seg_item}px;
    min-height: 26px; max-height: 999px; padding: 0px 12px; font-size: 12px; }}
QPushButton[seg="true"]:hover {{ color: {t["ink"]}; }}
QPushButton[seg="true"]:checked {{ background: transparent; color: {t["ink"]};
    border: 1px solid transparent; }}
QPushButton[seg="true"][segAccent="true"]:checked {{ color: {t["on_accent"]}; }}

QToolTip {{ color: {t["ink"]}; background: {t["card"]}; border: 1px solid {t["line2"]}; padding: 4px 6px; }}
"""
