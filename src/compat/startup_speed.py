"""Build ok's old pages faster when the tool opens (Leo 2026-11-17 「啟動工具的
速度可不可以再快一點」).

Measured on Leo's 4K PC (copy of v0.3.22, nothing else running): ok's main
window took 4.0 s and YES-BD2's own pages 2.0 s more.  Two things made it slow,
both for ok's old pages that the new window hides and never opens
(src/ui/shell/install.py):

1. Every old page put an app-wide Python event filter on the application (the
   touch-scroll click guard).  While the window was being built, every event of
   every new widget went through all of them: 742 770 filter calls in one open.
   install.py already takes them all off once the window is built; now they are
   not put on while it is being built, so the end state is the same.
2. Every task card of the old 「任务」 pages built all its settings widgets up
   front (28 cards, 3 s of the 4 s).  Those widgets only show when a card is
   opened, so a card now builds them the first time it opens.

Nothing here changes what the new window shows or what a task reads: the
settings live in each task's config, not in these widgets.
"""

from __future__ import annotations

import sys

from ok import Logger

logger = Logger.get_logger(__name__)

PATCH_MARKER = "_ok_bd2_startup_speed"

# True while the main window is being built (see finish_building()).
_building = True


def building() -> bool:
    return _building


def finish_building() -> None:
    """The main window and YES-BD2's pages are built: later scroll areas
    (dialogs) get ok's touch-scroll guard as before."""
    global _building
    _building = False


def _touch_scrolling_without_guard(original):
    def enable_touch_scrolling(scroll_area):
        if not _building:
            return original(scroll_area)
        # What ok does, minus the app-wide click guard (install.py would take
        # it off right after the window is built anyway).
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QScroller

        viewport = scroll_area.viewport()
        viewport.setAttribute(Qt.WA_AcceptTouchEvents, True)
        QScroller.grabGesture(viewport, QScroller.ScrollerGestureType.TouchGesture)

    enable_touch_scrolling._ok_bd2_original = original
    return enable_touch_scrolling


def install_touch_guard_skip() -> None:
    import ok.ui.qt.util.touch_scroll as touch_scroll

    original = touch_scroll.enable_touch_scrolling
    if getattr(original, "_ok_bd2_original", None) is not None:
        return
    patched = _touch_scrolling_without_guard(original)
    # Modules that did ``from ... import enable_touch_scrolling`` keep their own name.
    import ok.ui.qt.MainWindow  # noqa: F401
    import ok.ui.qt.widget.Tab  # noqa: F401

    for name, module in list(sys.modules.items()):
        if name.startswith("ok.") and getattr(module, "enable_touch_scrolling", None) is original:
            module.enable_touch_scrolling = patched


def install_lazy_config_cards() -> None:
    """ok's ConfigCard builds its settings widgets the first time it opens."""
    from ok.ui.qt.tasks.ConfigCard import ConfigCard, ConfigContentMixin

    if getattr(ConfigCard, PATCH_MARKER, False):
        return
    build_content = ConfigContentMixin._init_config_content
    set_expand = ConfigCard.setExpand
    update_config = ConfigContentMixin.update_config

    def _init_config_content(self, task, config, default_config, config_description, config_type):
        empty = not config or not (config.has_user_config() or default_config or config_type)
        if empty:
            # No widgets to build: keep ok's own handling (the card can't open).
            return build_content(
                self, task, config, default_config, config_description, config_type
            )
        # What ok sets before building, so code reading these finds them.
        self.config = config
        self.config_widgets = []
        self.config_widget_by_key = {}
        self.config_keys = []
        self.default_config = default_config
        self.config_description = config_description
        self.config_type = config_type
        self.sub_configs_rules = {}
        self.sub_configs_controlled_keys = {}
        self.task = task
        self.reset_config = None
        self._ok_bd2_pending_content = (
            task,
            config,
            default_config,
            config_description,
            config_type,
        )

    def _build_pending(self):
        pending = getattr(self, "_ok_bd2_pending_content", None)
        if pending is None:
            return
        self._ok_bd2_pending_content = None
        # The task attribute may have been replaced after __init__ (TaskCard sets it).
        task = getattr(self, "task", None) or pending[0]
        build_content(self, task, *pending[1:])

    def setExpand(self, isExpand: bool):
        if isExpand:
            try:
                _build_pending(self)
            except Exception as exc:
                logger.error(f"building the settings of {getattr(self, 'task', None)} failed", exc)
        return set_expand(self, isExpand)

    def _update_config(self):
        if getattr(self, "_ok_bd2_pending_content", None) is not None:
            return  # built from the current config when the card opens
        return update_config(self)

    ConfigCard._init_config_content = _init_config_content
    ConfigCard.setExpand = setExpand
    ConfigCard.update_config = _update_config
    ConfigCard.build_pending_content = _build_pending
    setattr(ConfigCard, PATCH_MARKER, True)


def install() -> None:
    for step in (install_touch_guard_skip, install_lazy_config_cards):
        try:
            step()
        except Exception as exc:
            logger.error(f"startup speed-up {step.__name__} not installed", exc)
