"""A task's own settings as a short form: label on the left, control on the right.

Uses the same config, types, hidden rows and sub-settings as the old task
cards, so nothing a task reads changes; long explanations move into the
ⓘ tooltip next to each label.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget
from qfluentwidgets import DoubleSpinBox, FlowLayout, LineEdit

from src.ui.hide_config_rows import mark_hidden_config_keys
from src.ui.shell import theme
from src.ui.shell.widgets import (
    Button,
    CheckBox,
    IconLabel,
    Segmented,
    Select,
    Slider,
    Stepper,
    Text,
    Toggle,
    attach_hint,
    hbox,
    t,
    vbox,
)

SEGMENTED_MAX_TEXT = 26
# A slider row's width: the bar plus its number box (design language: 8 × the
# middle control height).
SLIDER_WIDTH = theme.size("control_md") * 8
# Task class -> the only settings that keep their ⓘ hint (Leo, 2026-10-04:
# 「日常設定 下面的備注 ... 不需要」).  Only the hint goes; the setting stays.
HINTS_KEPT = {
    "DailyTask": (),
    "QuickHuntTask": (),
    "JunkGearTask": (),
    "PVPTask": ("舞台移动方式",),
    "EventBattleTask": ("只刷普通难度", "挑战战斗最高关卡"),
    "MissionRewardTask": (),
    "MailRewardTask": (),
}


def _pvp_panel(task, parent, on_change):
    from src.ui.shell.pvp_panel import PvpPanel

    return PvpPanel(task, parent, on_change)


# Task class -> (settings shown by one panel of their own, panel factory).
# 镜中之战: 倍数 and 场数 as steppers that keep 倍数 × 场数 ≤ 40 (Leo 2026-10-14).
PANELS = {
    "PVPTask": (("竞技场战斗倍数", "战斗场数"), _pvp_panel),
}


def _type_of(task, key) -> dict:
    the_type = (getattr(task, "config_type", None) or {}).get(key)
    if isinstance(the_type, dict):
        return the_type
    if the_type is None:
        return {}
    return {"type": the_type}


def hidden_keys(task) -> set[str]:
    try:
        mark_hidden_config_keys(task)
    except Exception:
        pass
    hidden = set()
    for key in task.config.keys():
        if str(key).startswith("_") or _type_of(task, key).get("hidden"):
            hidden.add(key)
    return hidden


def visible_keys(task, skip: Iterable[str] = ()) -> list[str]:
    skip = set(skip) | hidden_keys(task)
    order = list((getattr(task, "default_config", None) or {}).keys())
    keys = [key for key in order if key in task.config]
    keys += [key for key in task.config.keys() if key not in keys]
    return [key for key in keys if key not in skip]


def parents(task) -> dict[str, tuple[str, object]]:
    """key -> (parent key, value the parent must have for it to show)."""
    result: dict[str, tuple[str, object]] = {}
    for key, the_type in (getattr(task, "config_type", None) or {}).items():
        if not isinstance(the_type, dict):
            continue
        rules = the_type.get("sub_configs")
        if not isinstance(rules, dict):
            continue
        for value, children in rules.items():
            if isinstance(children, str):
                children = [children]
            for child in children or ():
                result.setdefault(child, (key, value))
    return result


def condition_met(task, key: str, rules: dict[str, tuple[str, object]]) -> bool:
    seen = set()
    while key in rules and key not in seen:
        seen.add(key)
        parent, value = rules[key]
        current = task.config.get(parent)
        if isinstance(value, str) and isinstance(current, bool):
            current = str(current).lower()
        if current != value:
            return False
        key = parent
    return True


def _label_text(task, key: str) -> str:
    try:
        from ok import og

        return og.app.tr(key)
    except Exception:
        return key


class ConfigForm(QWidget):
    """Rows for ``keys`` of ``task.config``; writes go straight to the config."""

    def __init__(
        self,
        task,
        keys: list[str] | None = None,
        skip: Iterable[str] = (),
        labels: dict[str, str] | None = None,
        parent=None,
        on_change: Callable[[str], None] | None = None,
        right_inset: int = 0,
    ):
        super().__init__(parent)
        self.task = task
        self._labels = labels or {}
        self._on_change = on_change
        self.keys = keys if keys is not None else visible_keys(task, skip)
        self._rules = parents(task)
        self._rows: dict[str, tuple[QWidget, QWidget, Callable[[], None]]] = {}
        self._panels: list[QWidget] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, right_inset, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(12)
        self.grid.setColumnStretch(1, 1)
        row = 0
        panel_keys = PANELS.get(type(task).__name__, ((), None))[0]
        for key in self.keys:
            if key in panel_keys:
                if key == next(k for k in self.keys if k in panel_keys):
                    # Settings drawn together by their own panel, at the first one's place.
                    panel = PANELS[type(task).__name__][1](task, self, on_change)
                    self.grid.addWidget(panel, row, 0, 1, 2)
                    row += 1
                    self._panels.append(panel)
                continue
            label = self._label(key)
            control, sync = self._control(key)
            if _type_of(task, key).get("type") == "multi_selection":
                # Long option lists get the full width under their label.
                self.grid.addWidget(label, row, 0, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
                self.grid.addWidget(control, row + 1, 0, 1, 2)
                row += 2
            else:
                # Text boxes fill the row; switches and pickers sit on the right.
                align = Qt.AlignVCenter
                if not isinstance(control, LineEdit):
                    align |= Qt.AlignRight
                self.grid.addWidget(label, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
                self.grid.addWidget(control, row, 1, align)
                row += 1
            self._rows[key] = (label, control, sync)
        self.sync()

    def is_empty(self) -> bool:
        return not self.keys

    # ---------------------------------------------------------------- rows

    def _label(self, key: str) -> QWidget:
        box = QWidget(self)
        row = hbox(box, (0, 0, 0, 0), 4)
        row.addWidget(Text(self._labels.get(key) or _label_text(self.task, key), "sub"))
        description = (getattr(self.task, "config_description", None) or {}).get(key)
        kept = HINTS_KEPT.get(type(self.task).__name__)
        if kept is not None and key not in kept:
            description = None
        # The ⓘ only where there is a hint to read; hovering the words shows it too.
        if description and str(description).strip() and attach_hint(box, t(str(description))):
            row.addWidget(IconLabel("info", 13, "ink3"))
        return box

    def _set(self, key: str, value) -> None:
        self.task.config[key] = value
        if self._on_change is not None:
            self._on_change(key)
        self.sync()

    def _control(self, key: str):
        value = self.task.config.get(key)
        the_type = _type_of(self.task, key)
        kind = the_type.get("widget") or the_type.get("type")
        if kind == "drop_down":
            return self._drop_down(key, list(the_type.get("options") or []))
        if kind == "segmented":
            return self._segmented(key, list(the_type.get("options") or []))
        if kind == "multi_selection":
            return self._multi(key, list(the_type.get("options") or []))
        if kind == "toggle_choice":
            return self._toggle_choice(key, list(the_type.get("options") or []))
        if kind == "button":
            return self._buttons(key, the_type)
        if isinstance(value, bool):
            toggle = Toggle(bool(value), self)
            toggle.toggled.connect(lambda checked, k=key: self._set(k, bool(checked)))
            return toggle, lambda: toggle.set_checked_quietly(bool(self.task.config.get(key)))
        bounded = "min" in the_type and "max" in the_type
        if isinstance(value, (int, float)) and bounded:
            # A number with both ends known: a slider with the number shown
            # (Leo 2026-11-09 「數字類可以用 SLIDER 加顯示數字」).
            is_float = isinstance(value, float)
            step = the_type.get("step", 0.1 if is_float else 1)
            decimals = 0
            if is_float:
                decimals = 2 if float(step) < 0.1 else 1
            cast = float if is_float else int
            slider = Slider(self, decimals=decimals)
            slider.setRange(cast(the_type["min"]), cast(the_type["max"]))
            slider.setSingleStep(cast(step))
            slider.setValue(cast(value))
            slider.setFixedWidth(SLIDER_WIDTH)
            slider.valueChanged.connect(lambda v, k=key, c=cast: self._set(k, c(v)))
            return slider, lambda: self._quiet(
                slider, lambda: slider.setValue(cast(self.task.config.get(key) or 0))
            )
        if isinstance(value, int):
            spin = Stepper(self)  # no ends known: − number +
            spin.setRange(int(the_type.get("min", -999999)), int(the_type.get("max", 999999)))
            spin.setValue(int(value))
            spin.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
            return spin, lambda: self._quiet(
                spin, lambda: spin.setValue(int(self.task.config.get(key) or 0))
            )
        if isinstance(value, float):
            spin = DoubleSpinBox(self)
            spin.setRange(
                float(the_type.get("min", -999999.0)), float(the_type.get("max", 999999.0))
            )
            step = float(the_type.get("step", 0.1))
            spin.setSingleStep(step)
            spin.setDecimals(2 if step < 0.1 else 1)
            spin.setValue(float(value))
            spin.setFixedWidth(150)
            spin.valueChanged.connect(lambda v, k=key: self._set(k, float(v)))
            return spin, lambda: self._quiet(
                spin, lambda: spin.setValue(float(self.task.config.get(key) or 0))
            )
        if isinstance(value, str):
            edit = LineEdit(self)
            edit.setMinimumWidth(180)
            edit.editingFinished.connect(lambda k=key, e=edit: self._set(k, e.text()))

            def sync_edit():
                if edit.hasFocus():
                    return
                text = str(self.task.config.get(key) or "")
                if edit.text() != text:
                    edit.setText(text)
                edit.setCursorPosition(0)  # show the start of long text

            sync_edit()
            return edit, sync_edit
        shown = Text(str(value), "muted")
        return shown, lambda: shown.set_text(str(self.task.config.get(key)))

    @staticmethod
    def _quiet(widget: QWidget, action: Callable[[], None]) -> None:
        widget.blockSignals(True)
        try:
            action()
        finally:
            widget.blockSignals(False)

    def _segmented(self, key: str, options: list[str]):
        # The chosen option filled violet like a lit switch, so it reads at a
        # glance (Leo 2026-10-20 「選取的選項要深紫色」).
        segmented = Segmented(options, str(self.task.config.get(key)), self, accent=True)
        segmented.changed.connect(lambda v, k=key: self._set(k, v))
        return segmented, lambda: segmented.set_value(str(self.task.config.get(key)))

    def _drop_down(self, key: str, options: list[str]):
        if len(options) <= 4 and sum(len(str(option)) for option in options) <= SEGMENTED_MAX_TEXT:
            return self._segmented(key, options)
        combo = Select(self)  # oink-ui Select (2026-11-09)
        for option in options:
            combo.addItem(t(str(option)), userData=option)
        combo.setMinimumWidth(200)

        def select():
            current = self.task.config.get(key)
            index = options.index(current) if current in options else -1
            if index >= 0 and combo.currentIndex() != index:
                self._quiet(combo, lambda: combo.setCurrentIndex(index))

        select()
        combo.currentIndexChanged.connect(
            lambda index, k=key: self._set(k, options[index]) if 0 <= index < len(options) else None
        )
        return combo, select

    def _multi(self, key: str, options: list[str]):
        box = QWidget(self)
        flow = FlowLayout(box, needAni=False)
        flow.setContentsMargins(0, 0, 0, 2)
        flow.setHorizontalSpacing(16)
        flow.setVerticalSpacing(8)
        boxes = {}
        for option in options:
            check = CheckBox(str(option), option in (self.task.config.get(key) or []), box)
            check.toggled.connect(lambda _c, k=key: self._set_multi(k, options, boxes))
            flow.addWidget(check)
            boxes[option] = check

        def sync():
            selected = set(self.task.config.get(key) or [])
            for option, check in boxes.items():
                check.set_checked_quietly(option in selected)

        return box, sync

    def _toggle_choice(self, key: str, options: list[str]):
        """One switch per option, always exactly one on: switching one on turns the
        others off, and the one that is on cannot be switched off (Leo 2026-10-12)."""
        box = QWidget(self)
        row = hbox(box, (0, 0, 0, 0), 18)
        toggles = {}
        sync_ref: list[Callable[[], None]] = []
        for option in options:
            pair = hbox(None, (0, 0, 0, 0), 8)
            pair.addWidget(Text(str(option), "sub"))
            toggle = Toggle(self.task.config.get(key) == option, box)
            toggle.toggled.connect(
                lambda on, k=key, o=option, s=sync_ref: self._set(k, o) if on else s[0]()
            )
            pair.addWidget(toggle)
            row.addLayout(pair)
            toggles[option] = toggle

        def sync():
            current = self.task.config.get(key)
            for option, toggle in toggles.items():
                toggle.set_checked_quietly(option == current)

        sync_ref.append(sync)
        return box, sync

    def _set_multi(self, key: str, options: list[str], boxes: dict) -> None:
        self._set(key, [option for option in options if boxes[option].isChecked()])

    def _buttons(self, key: str, the_type: dict):
        box = QWidget(self)
        row = hbox(box, (0, 0, 0, 0), 8)
        buttons = the_type.get("buttons") or [the_type]
        for spec in buttons:
            callback = spec.get("callback")
            button = Button(
                str(spec.get("text") or key),
                "secondary",
                size="sm",
                on_click=callback if callable(callback) else None,
            )
            row.addWidget(button)
        row.addStretch(1)
        return box, lambda: None

    # ---------------------------------------------------------------- state

    def sync(self) -> None:
        """Show only rows whose parent switch allows them; match saved values."""
        for key, (label, control, sync) in self._rows.items():
            visible = condition_met(self.task, key, self._rules)
            label.setVisible(visible)
            control.setVisible(visible)
            if visible:
                sync()
        for panel in self._panels:
            panel.sync()
        self.updateGeometry()

    def reset(self) -> None:
        for key in self.keys:
            default = self.task.config.get_default(key)
            if default is not None:
                self.task.config[key] = default
        self.sync()


def form_card_body(form: ConfigForm, title: str | None = None) -> QWidget:
    box = QWidget()
    column = vbox(box, (0, 0, 0, 0), 10)
    if title:
        column.addWidget(Text(title, "h3"))
    column.addWidget(form)
    return box
