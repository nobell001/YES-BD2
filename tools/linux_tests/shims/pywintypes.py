"""Linux test runs only (tools/linux_tests): stand-in so Windows-only imports load."""

import zlib
from unittest.mock import MagicMock

_made = {}


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    if name.isupper():
        # distinct single-bit values, so flags and keys stay tellable apart
        return 1 << (zlib.crc32(name.encode()) % 31)
    return _made.setdefault(name, MagicMock(name=name))
