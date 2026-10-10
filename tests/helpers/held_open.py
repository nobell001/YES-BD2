"""A record file held open elsewhere, as Windows reports it (a reader blocks
the swap-in, an antivirus scan blocks the read): PermissionError.

Only the given file is refused, however the code under test opens it."""

import builtins
import io
import os
from contextlib import ExitStack, contextmanager
from unittest import mock


def _same(file, path) -> bool:
    try:
        return os.path.abspath(os.fspath(file)) == os.path.abspath(os.fspath(path))
    except TypeError:  # a file descriptor
        return False


def _refusals(times):
    left = [times]

    def refuse() -> bool:
        if left[0] is None:
            return True
        if left[0] > 0:
            left[0] -= 1
            return True
        return False

    return refuse


def replace_refused(path, times: int | None = None):
    """Swapping a file in over ``path`` fails ``times`` times (None: always)."""
    real = os.replace
    refuse = _refusals(times)

    def replace(source, target, *args, **kwargs):
        if _same(target, path) and refuse():
            raise PermissionError(13, "held open elsewhere", os.fspath(target))
        return real(source, target, *args, **kwargs)

    return mock.patch.object(os, "replace", replace)


@contextmanager
def read_refused(path, times: int | None = None):
    """Opening ``path`` to read fails ``times`` times (None: always)."""
    real = io.open
    refuse = _refusals(times)

    def fake_open(file, mode="r", *args, **kwargs):
        if "r" in mode and _same(file, path) and refuse():
            raise PermissionError(13, "held open elsewhere", os.fspath(file))
        return real(file, mode, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(builtins, "open", fake_open))
        stack.enter_context(mock.patch.object(io, "open", fake_open))
        yield


def no_wait():
    return mock.patch("time.sleep")
