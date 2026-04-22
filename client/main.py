from __future__ import annotations

import sys
import os

# Ensure the project root is on sys.path so `client.*` imports work
# regardless of how this file is launched (e.g. `flet run client/main.py`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet

from client.locale import set_locale
from client.state import AppState
from client.storage.settings import LocalStorage

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_SETTINGS_DIR_FALLBACK = os.path.join(os.path.dirname(__file__), "storage", "data")


async def main(page: flet.Page) -> None:
    page.title = "Мессенджер"
    page.theme_mode = flet.ThemeMode.LIGHT
    page.fonts = {"RobotoFlex": "fonts/RobotoFlex.ttf"}
    page.theme = flet.Theme(color_scheme_seed="#008069", font_family="RobotoFlex")
    page.padding = 0

    try:
        settings_dir = await flet.StoragePaths().get_application_support_directory()
    except Exception:
        settings_dir = None
    if not settings_dir:
        settings_dir = _SETTINGS_DIR_FALLBACK
    logger.info("[main] settings dir: %s", settings_dir)

    storage = LocalStorage(settings_dir)
    state = AppState(secure_storage=storage)

    stored_locale = storage.get("settings.locale") or "ru"
    set_locale(stored_locale)
    logger.info("[main] locale: %r", stored_locale)

    stored_alignment = storage.get("settings.message_alignment")
    logger.info("[main] stored_alignment from file: %r", stored_alignment)
    if stored_alignment in ("default", "left", "right"):
        state.message_alignment = stored_alignment
        logger.info("[main] Applied stored alignment: %r", stored_alignment)

    from client.views.login_view import login_view
    login_view(page, state)


if __name__ == "__main__":
    flet.app(
        target=main,
        view=flet.AppView.FLET_APP,
        assets_dir=os.path.join(os.path.dirname(__file__), "assets"),
    )
