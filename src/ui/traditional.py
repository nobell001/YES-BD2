"""Traditional Chinese display for the whole tool.

The project's texts (task names, settings, descriptions, the custom cards
and buttons) are written in Simplified Chinese and there is no zh_TW
catalog.  With the app set to Traditional Chinese, any text the catalogs
do not translate is converted with OpenCC's Taiwan profile (s2twp: 设置 ->
設定, 鼠标 -> 滑鼠).  Stored settings keep their Simplified keys; only the
display changes (user, 2026-09-27).
"""

from __future__ import annotations

from functools import lru_cache

TRADITIONAL_LOCALES = frozenset({"zh_TW", "zh_HK", "zh_MO"})


def is_traditional(locale_name: str) -> bool:
    return str(locale_name).replace("-", "_") in TRADITIONAL_LOCALES


@lru_cache(maxsize=1)
def _converter():
    try:
        import opencc
    except ImportError:  # pragma: no cover - opencc is a project dependency
        return None
    return opencc.OpenCC("s2twp")


# Taiwan words OpenCC's s2twp gets wrong (GitHub issue #4's 账号 came out as
# 賬號, live 2026-10-09).
TAIWAN_FIXES = (("賬號", "帳號"), ("賬戶", "帳戶"))


@lru_cache(maxsize=4096)
def to_traditional(text: str) -> str:
    converter = _converter()
    if converter is None:
        return text
    converted = converter.convert(text)
    for wrong, right in TAIWAN_FIXES:
        converted = converted.replace(wrong, right)
    return converted


def _locale_name(app) -> str:
    locale = getattr(app, "locale", None)
    name = getattr(locale, "name", None)
    try:
        return str(name() if callable(name) else locale or "")
    except Exception:
        return ""


def wrap_tr(original):
    """A ``tr`` that converts untranslated text on a Traditional locale."""

    def tr(self, key, *args, **kwargs):
        result = original(self, key, *args, **kwargs)
        if isinstance(key, str) and key and result == key and is_traditional(_locale_name(self)):
            return to_traditional(key)
        return result

    tr._bd2_traditional = True
    return tr


def install_traditional_fallback() -> bool:
    """Patch ok's App/HeadlessApp ``tr`` once; returns whether it patched."""

    import ok

    patched = False
    for name in ("App", "HeadlessApp"):
        cls = getattr(ok, name, None)
        original = getattr(cls, "tr", None)
        if original is None or getattr(original, "_bd2_traditional", False):
            continue
        cls.tr = wrap_tr(original)
        patched = True
    return patched


def ui_text(text: str) -> str:
    """Translate a label of the project's own widgets (identity without an app)."""

    try:
        from ok import og

        app = getattr(og, "app", None)
    except Exception:
        app = None
    translate = getattr(app, "tr", None)
    if translate is None:
        return text
    try:
        return translate(text)
    except Exception:
        return text
