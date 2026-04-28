from __future__ import annotations

import os
import logging
import sys

import flet

from localization import set_locale
from state import AppState
from storage.settings import LocalStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

_SETTINGS_DIR_FALLBACK = os.path.join(os.path.dirname(__file__), "storage", "data")

# needed for tests and sometimes android support
_client_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_client_dir))  # workspace root
sys.path.insert(
    0, _client_dir
)  # client/ itself — needed for `crypto.*` imports on Android


async def main(page: flet.Page) -> None:
    page.title = "Мессенджер"
    page.theme_mode = flet.ThemeMode.LIGHT
    page.fonts = {"RobotoFlex": "fonts/RobotoFlex.ttf"}
    page.theme = flet.Theme(color_scheme_seed="#008069", font_family="RobotoFlex")
    page.padding = 0

    # Show a loading indicator immediately so the splash screen dismisses
    loading = flet.Column(
        controls=[
            flet.ProgressRing(color="#008069"),
            flet.Text("Загрузка...", color="#667781", size=14),
        ],
        alignment=flet.MainAxisAlignment.CENTER,
        horizontal_alignment=flet.CrossAxisAlignment.CENTER,
        expand=True,
    )
    page.add(loading)
    page.update()

    try:
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
        if stored_alignment in ("default", "left", "right"):
            state.message_alignment = stored_alignment

        from views.login_view import login_view

        login_view(page, state)

    except Exception as exc:
        logger.exception("[main] startup error: %s", exc)
        page.controls.clear()
        page.add(
            flet.Column(
                controls=[
                    flet.Icon(flet.Icons.ERROR_OUTLINE, color="#ea4335", size=48),
                    flet.Text(
                        "Ошибка запуска",
                        size=18,
                        weight=flet.FontWeight.BOLD,
                        color="#111b21",
                    ),
                    flet.Text(str(exc), size=12, color="#667781", selectable=True),
                ],
                alignment=flet.MainAxisAlignment.CENTER,
                horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                expand=True,
            )
        )
        page.update()


async def _preload_views() -> None:
    """Pre-import all view modules so lazy imports don't block on Android."""
    print("[main] preloading view modules...")
    import views.login_view  # noqa: F401
    import views.register_view  # noqa: F401
    import views.chat_list_view  # noqa: F401
    import views.room_view  # noqa: F401
    import views.profile_view  # noqa: F401
    import views.room_settings_view  # noqa: F401
    import views.room_list_view  # noqa: F401
    import views.widgets.markdown_viewer  # noqa: F401
    import views.widgets.emoji_picker  # noqa: F401
    import views.widgets.formatting_toolbar  # noqa: F401

    print("[main] preloading done")


if __name__ == "__main__":
    flet.app(
        target=main,
        view=flet.AppView.FLET_APP,
        assets_dir=os.path.join(os.path.dirname(__file__), "assets"),
    )
