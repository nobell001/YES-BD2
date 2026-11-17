from ok import Logger
from PySide6.QtCore import QObject

logger = Logger.get_logger(__name__)


class Globals(QObject):
    def __init__(self, exit_event):
        super().__init__()
        # 历史上的线程池/周期任务机制已随 BaseBD2Task 死成员一并移除；
        # 保留停机钩子登记，供后续需要统一清理的全局资源使用。
        exit_event.bind_stop(self)

    def stop(self):
        pass

    def on_show_main_window(self, main_window):
        from ok import og

        from src.game_path import seed_device_manager_launch_path
        from src.ui.quest_theme import apply_app_font
        from src.ui.shell.install import install_shell

        apply_app_font()

        launch_path = seed_device_manager_launch_path(og.device_manager)
        if launch_path:
            logger.info(f"seed BD2 Starter path {launch_path}")
        # 新版侧边栏和页面；ok 自己的旧页面只是藏起来。
        install_shell(main_window)

        from src.compat.taskbar_icon import apply_to_main_window

        apply_to_main_window(main_window)

        from src.compat.startup_speed import finish_building

        finish_building()
