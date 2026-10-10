"""Several game accounts on one install (GitHub issue #4, Leo 2026-10-09).

A player with a main and a second account ran 跑图 on the first, then the
tool thought the second one had finished the week too: every record lived in
one file per install.  Now each account keeps its own records (跑图/跑商
progress, what was done today and this week, 女神像 wishes, ...) and its own
run ticks; settings, hotkeys, colours and language stay shared.

Account ``1`` keeps the files where they always were (``configs/``), so an
existing install simply becomes account 1.  Other accounts live in
``configs/accounts/<id>/``.  ``configs/accounts.json`` holds the list, the
current account and each account's ticks; it is read again whenever it
changed, so the tool in the 桌面分身 follows the outer one.

A list that cannot be read is never taken as "only account 1": runs do not
start until the player sorts it out (``unreadable``, setup_check).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.compat.safe_json import read_text_retrying, write_text_atomic

MAX_ACCOUNTS = 5  # Leo 2026-10-09
AVATAR_MAX_BYTES = 8 * 1024 * 1024  # Leo 2026-10-09: 「8mb內」
AVATAR_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
FIRST_ID = "1"
CONFIG_DIR = Path("configs")
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
ACCOUNTS_DIR = CONFIG_DIR / "accounts"


class AccountError(ValueError):
    """A request the account list cannot take (full, too large, last one...)."""


@dataclass(frozen=True)
class Account:
    id: str
    name: str  # "" = the default 「账号 N」 the UI shows in the player's language
    avatar: str  # file name inside the account's folder, "" = initial letter

    @property
    def number(self) -> int:
        try:
            return int(self.id)
        except ValueError:
            return 0


# (mtime, list, problem): problem is "" or BROKEN.
_cache: tuple[float | None, dict, str] | None = None
# The last list read fine: used while the file is held open elsewhere.
_last_good: dict | None = None
BROKEN = "broken"  # the content is not a list; a copy is kept as .corrupt
BUSY = "busy"  # held open elsewhere (an antivirus scan, the other tool)


def _file() -> Path:
    return ACCOUNTS_FILE


def _load() -> tuple[dict, str]:
    global _cache, _last_good
    path = _file()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if _cache is not None and _cache[0] == mtime and mtime is not None:
        return _cache[1], _cache[2]
    try:
        value = json.loads(read_text_retrying(path))
    except FileNotFoundError:
        return {}, ""  # a fresh install is account 1
    except OSError:
        # Not cached: read again next time.
        return dict(_last_good or {}), BUSY
    except ValueError:
        value = None
    if not isinstance(value, dict):
        try:
            shutil.copy2(path, f"{path}.corrupt")
        except OSError:
            pass
        _cache = (mtime, {}, BROKEN)
        return {}, BROKEN
    _cache = (mtime, value, "")
    _last_good = value
    return value, ""


def _read() -> dict:
    return _load()[0]


def unreadable() -> str:
    """BROKEN or BUSY when the list cannot be read, so whose records a run
    would write is unknown; "" when it is fine (or not made yet)."""
    return _load()[1]


def _write(state: dict) -> None:
    global _cache
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(state, ensure_ascii=False, indent=1))
    _cache = None


def _entries(state: dict) -> list[dict]:
    rows = state.get("accounts")
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    seen = set()
    clean = []
    for row in rows:
        account_id = str(row.get("id", ""))
        if not account_id.isdigit() or account_id in seen:
            continue
        seen.add(account_id)
        clean.append(row)
    if FIRST_ID not in seen:
        clean.insert(0, {"id": FIRST_ID})
    return clean[:MAX_ACCOUNTS]


def _account(row: dict) -> Account:
    return Account(
        id=str(row.get("id")),
        name=str(row.get("name") or "").strip(),
        avatar=str(row.get("avatar") or ""),
    )


def accounts() -> list[Account]:
    return [_account(row) for row in _entries(_read())]


def current_id() -> str:
    state = _read()
    wanted = str(state.get("current") or FIRST_ID)
    ids = {str(row.get("id")) for row in _entries(state)}
    return wanted if wanted in ids else FIRST_ID


def current() -> Account:
    wanted = current_id()
    return next(account for account in accounts() if account.id == wanted)


def has_several() -> bool:
    return len(accounts()) > 1


def data_dir(account_id: str | None = None, base: Path | None = None) -> Path:
    """The folder holding one account's records (``configs`` for account 1)."""
    account_id = current_id() if account_id is None else str(account_id)
    root = CONFIG_DIR if base is None else Path(base)
    if account_id == FIRST_ID:
        return root
    return root / "accounts" / account_id


def path(name: str, account_id: str | None = None, base: Path | None = None) -> Path:
    """Where the current (or given) account keeps the record file ``name``."""
    return data_dir(account_id, base) / name


def scoped(default: Path | str, account_id: str | None = None) -> Path | str:
    """Account 1's record file is ``default`` itself; another account keeps the
    same name in its own folder next to it (``<folder>/accounts/<id>/``).
    Keeps the type it was given (callers pass ``str`` or ``Path``)."""
    account_id = current_id() if account_id is None else str(account_id)
    if account_id == FIRST_ID:
        return default
    original = Path(default)
    moved = original.parent / "accounts" / account_id / original.name
    return str(moved) if isinstance(default, str) else moved


def avatar_path(account: Account) -> Path | None:
    if not account.avatar:
        return None
    file = ACCOUNTS_DIR / account.id / account.avatar
    return file if file.is_file() else None


# ---------------------------------------------------------------- changes


def _next_id(rows: list[dict]) -> str:
    used = {int(row["id"]) for row in rows}
    number = 2
    while number in used:
        number += 1
    return str(number)


def add(name: str = "", ticks: dict | None = None) -> Account:
    """A new account; it starts with a copy of ``ticks`` (the current ones)."""
    state = dict(_read())
    rows = _entries(state)
    if len(rows) >= MAX_ACCOUNTS:
        raise AccountError("full")
    row = {"id": _next_id(rows), "name": name.strip()}
    rows.append(row)
    state["accounts"] = rows
    all_ticks = dict(state.get("ticks") or {})
    all_ticks[row["id"]] = {str(k): bool(v) for k, v in (ticks or {}).items()}
    state["ticks"] = all_ticks
    _write(state)
    return _account(row)


def rename(account_id: str, name: str) -> None:
    state = dict(_read())
    rows = _entries(state)
    for row in rows:
        if str(row["id"]) == str(account_id):
            row["name"] = name.strip()[:20]
    state["accounts"] = rows
    _write(state)


def set_avatar(account_id: str, source: Path | str | None) -> None:
    """Copy the picked picture next to the account's records; ``None`` clears it."""
    state = dict(_read())
    rows = _entries(state)
    row = next((row for row in rows if str(row["id"]) == str(account_id)), None)
    if row is None:
        raise AccountError("missing")
    folder = ACCOUNTS_DIR / str(account_id)
    old = str(row.get("avatar") or "")
    if source is None:
        row["avatar"] = ""
    else:
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix not in AVATAR_SUFFIXES:
            raise AccountError("format")
        if source.stat().st_size > AVATAR_MAX_BYTES:
            raise AccountError("size")
        folder.mkdir(parents=True, exist_ok=True)
        # A new name each time so a cached picture of the old one never shows.
        stamp = int(source.stat().st_mtime_ns % 10**9)
        target = folder / f"avatar-{stamp}{suffix}"
        shutil.copyfile(source, target)
        row["avatar"] = target.name
    if old and old != row["avatar"]:
        try:
            (folder / old).unlink()
        except OSError:
            pass
    state["accounts"] = rows
    _write(state)


def delete(account_id: str) -> None:
    """Remove an account and its records.  Account 1 holds the original files
    and stays; the account in use cannot be deleted either."""
    account_id = str(account_id)
    if account_id == FIRST_ID:
        raise AccountError("first")
    if account_id == current_id():
        raise AccountError("current")
    state = dict(_read())
    state["accounts"] = [row for row in _entries(state) if str(row["id"]) != account_id]
    ticks = dict(state.get("ticks") or {})
    ticks.pop(account_id, None)
    state["ticks"] = ticks
    _write(state)
    shutil.rmtree(ACCOUNTS_DIR / account_id, ignore_errors=True)


def switch(account_id: str, config=None, tick_keys=()) -> bool:
    """Make ``account_id`` current.  ``config`` is the 一键日常 config: its
    ticks (``tick_keys``) are kept for the old account and the new account's
    ticks are put in.  Returns whether anything changed."""
    account_id = str(account_id)
    state = dict(_read())
    rows = _entries(state)
    if account_id not in {str(row["id"]) for row in rows}:
        raise AccountError("missing")
    old_id = current_id()
    if old_id == account_id:
        return False
    all_ticks = dict(state.get("ticks") or {})
    if config is not None:
        all_ticks[old_id] = {key: bool(config.get(key, True)) for key in tick_keys}
    state["ticks"] = all_ticks
    state["current"] = account_id
    state["accounts"] = rows
    _write(state)
    if config is not None:
        saved = all_ticks.get(account_id) or {}
        for key in tick_keys:
            if key in saved and bool(config.get(key, True)) != bool(saved[key]):
                config[key] = bool(saved[key])
    return True


def reset_cache() -> None:
    """Tests change folders between cases."""
    global _cache, _last_good
    _cache = None
    _last_good = None
