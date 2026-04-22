"""Localization module for the Telecommunicator client.

Usage:
    from client.i18n import t, set_locale

    set_locale("ru")
    t("login.submit")          # -> "Войти"
    t("profile.username", username="alice")  # -> "Имя пользователя: alice"
"""
from __future__ import annotations

import os
import i18n

_LOCALES_DIR = os.path.join(os.path.dirname(__file__), "locales")

i18n.set("load_path", [_LOCALES_DIR])
i18n.set("file_format", "yml")
i18n.set("filename_format", "{locale}.{format}")
i18n.set("fallback", "ru")
i18n.set("error_on_missing_translation", False)

_current_locale: str = "ru"


def set_locale(locale: str) -> None:
    """Set the active locale (e.g. 'ru', 'en')."""
    global _current_locale
    _current_locale = locale
    i18n.set("locale", locale)


def get_locale() -> str:
    return _current_locale


# Human-readable names for available locales
AVAILABLE_LOCALES: list[tuple[str, str]] = [
    ("ru", "Русский"),
    ("en", "English"),
]


def t(key: str, **kwargs: object) -> str:
    """Translate a dot-separated key with optional interpolation variables."""
    return i18n.t(key, locale=_current_locale, **kwargs)


# Apply default locale on import
set_locale(_current_locale)
