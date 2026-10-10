from __future__ import annotations

MAIN_WINDOW_GEOMETRY_DEBOUNCE_MS = 500
FIRST_OPEN_SCREEN_SHARE = 0.92
_PATCH_MARKER = "_ok_bd2_geometry_debounce_enabled"
_FIT_MARKER = "_ok_bd2_first_open_fit_enabled"
# A saved window must show at least this much on some screen, or it opens
# centred (audit #54: saved on a monitor that was later unplugged).
VISIBLE_MIN_WIDTH = 100
VISIBLE_MIN_HEIGHT = 50


def fit_first_open_size(
    width: int, height: int, min_width: int, min_height: int, screen_width: int, screen_height: int
) -> tuple[int, int]:
    """Shrink the default size so a first open never spills off a small screen."""

    width = min(width, int(screen_width * FIRST_OPEN_SCREEN_SHARE))
    height = min(height, int(screen_height * FIRST_OPEN_SCREEN_SHARE))
    return max(width, min_width), max(height, min_height)


def visible_on_a_screen(
    rect: tuple[int, int, int, int], screens: list[tuple[int, int, int, int]]
) -> bool:
    """True when the (x, y, width, height) window shows enough on one screen."""

    x, y, width, height = rect
    for sx, sy, sw, sh in screens:
        overlap_w = min(x + width, sx + sw) - max(x, sx)
        overlap_h = min(y + height, sy + sh) - max(y, sy)
        if overlap_w >= VISIBLE_MIN_WIDTH and overlap_h >= VISIBLE_MIN_HEIGHT:
            return True
    return False


def _available_screens() -> list[tuple[int, int, int, int]]:
    from PySide6.QtGui import QGuiApplication

    rects = []
    for screen in QGuiApplication.screens():
        geometry = screen.availableGeometry()
        rects.append((geometry.x(), geometry.y(), geometry.width(), geometry.height()))
    return rects


def forget_off_screen_position(config, screens: list[tuple[int, int, int, int]]) -> bool:
    """Clear a saved position no screen shows, so ok opens the window centred."""

    if config is None or not screens:
        return False
    try:
        rect = tuple(
            int(config.get(key, 0) or 0)
            for key in ("window_x", "window_y", "window_width", "window_height")
        )
    except (TypeError, ValueError):
        return False
    if rect[2] <= 0 or rect[3] <= 0 or visible_on_a_screen(rect, screens):
        return False
    config["window_x"] = 0
    config["window_y"] = 0
    config["window_maximized"] = False
    return True


def patch_main_window_first_open_size(main_window_class: type, screens=_available_screens) -> None:
    """Fit the configured default size to the screen; a saved size is left
    alone unless no screen shows it any more."""

    if getattr(main_window_class, _FIT_MARKER, False):
        return

    original_set_window_size = main_window_class.set_window_size

    def fitted_set_window_size(self, width, height, min_width, min_height):
        try:
            forget_off_screen_position(getattr(self, "ok_config", None), screens())
        except Exception:  # noqa: BLE001 - never block the window from opening
            pass
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width, height = fit_first_open_size(
                width, height, min_width, min_height, available.width(), available.height()
            )
        return original_set_window_size(self, width, height, min_width, min_height)

    main_window_class.set_window_size = fitted_set_window_size
    setattr(main_window_class, _FIT_MARKER, True)


def patch_main_window_geometry_events(
    main_window_class: type,
    qtimer: type,
) -> None:
    """Save top-level geometry once after a burst of move/resize events."""

    if getattr(main_window_class, _PATCH_MARKER, False):
        return

    original_move_event = main_window_class.moveEvent
    original_resize_event = main_window_class.resizeEvent
    original_close_event = main_window_class.closeEvent

    def schedule_geometry_save(self) -> None:
        timer = getattr(self, "_ok_bd2_geometry_timer", None)
        if timer is None:
            timer = qtimer(self)
            timer.setSingleShot(True)
            timer.setInterval(MAIN_WINDOW_GEOMETRY_DEBOUNCE_MS)
            timer.timeout.connect(self.update_ok_config)
            self._ok_bd2_geometry_timer = timer
        timer.start()

    def flush_geometry_save(self) -> None:
        timer = getattr(self, "_ok_bd2_geometry_timer", None)
        if timer is None or not timer.isActive():
            return
        timer.stop()
        self.update_ok_config()

    def stable_move_event(self, event):
        result = original_move_event(self, event)
        schedule_geometry_save(self)
        return result

    def stable_resize_event(self, event):
        result = original_resize_event(self, event)
        schedule_geometry_save(self)
        return result

    def stable_close_event(self, event):
        flush_geometry_save(self)
        return original_close_event(self, event)

    main_window_class.moveEvent = stable_move_event
    main_window_class.resizeEvent = stable_resize_event
    main_window_class.closeEvent = stable_close_event
    setattr(main_window_class, _PATCH_MARKER, True)


def install_main_window_geometry_debounce() -> None:
    from ok.ui.qt.MainWindow import MainWindow
    from PySide6.QtCore import QTimer

    patch_main_window_geometry_events(MainWindow, QTimer)
    patch_main_window_first_open_size(MainWindow)
