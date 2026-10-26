"""网络慢时的等待：玩家在「设置」里自己调（YES-BD2 #56，2026-10-26）。

玩家：网络慢的时候，打开游戏和登录要等很久，希望等多久、重试几次能自己
设，工具先给一套保守的默认值。这里存四个数，「设置 → 游戏」可以改：

- 打开游戏最长等多久（秒）：等游戏视窗出现、等游戏能截图，各自最多等这么久
- 打开游戏没好再试几次：等太久时自动再等一轮（游戏已经开着就不会再开一次）
- 登录后等主页最长多久（秒）：按了 TOUCH TO START 之后等进主页
- 登录没进主页重试几次：连续这么多次没进主页，就取消这次一键日常/周常

和静音设定一样存在 configs 资料夹里，桌面分身里的工具读同一个档案。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ok import Logger

from src.compat.safe_json import write_text_atomic

logger = Logger.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = ROOT / "configs" / "wait_settings.json"


@dataclass(frozen=True)
class Setting:
    key: str
    title: str
    sub: str
    default: int
    low: int
    high: int
    unit: str  # 秒 or 次


START_TIMEOUT = Setting(
    "start_timeout",
    "打开游戏最长等多久",
    "等游戏视窗出现、等到能截图，各自最多等这么久",
    180,
    60,
    600,
    "秒",
)
START_RETRIES = Setting(
    "start_retries",
    "打开游戏没好，再等几轮",
    "等太久时自动再等一轮，游戏开着就不会再开一次",
    1,
    0,
    3,
    "次",
)
LOGIN_HOME_WAIT = Setting(
    "login_home_wait",
    "登录后等主页最长多久",
    "按了 TOUCH TO START 之后，最多等这么久进主页",
    300,
    120,
    900,
    "秒",
)
LOGIN_GIVE_UP = Setting(
    "login_give_up",
    "登录没进主页，重试几次",
    "连续这么多次没进主页，就取消这次一键日常/周常",
    3,
    1,
    10,
    "次",
)
SETTINGS = (START_TIMEOUT, START_RETRIES, LOGIN_HOME_WAIT, LOGIN_GIVE_UP)


def _read() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def clamp(setting: Setting, value) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return setting.default
    return max(setting.low, min(setting.high, number))


def saved(setting: Setting) -> int | None:
    """The player's own value, or None when they never changed it."""
    value = _read().get(setting.key)
    return None if value is None else clamp(setting, value)


def get(setting: Setting) -> int:
    """Read from the file each time: 设置 may have changed it since the last start."""
    value = saved(setting)
    return setting.default if value is None else value


def set_values(values: dict[Setting, int]) -> None:
    current = _read()
    for setting, value in values.items():
        current[setting.key] = clamp(setting, value)
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(SETTINGS_FILE, json.dumps(current))
    except OSError as exc:
        logger.warning(f"wait settings: not saved ({exc})")
