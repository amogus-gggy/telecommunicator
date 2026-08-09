from __future__ import annotations

import os
import logging
import sys

import flet

from localization import set_locale
from state import AppState
from storage.settings import LocalStorage
from ui.theme import apply_theme

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

    try:
        try:
            settings_dir = await flet.StoragePaths().get_application_support_directory()
        except Exception:
            settings_dir = None
        if not settings_dir:
            settings_dir = _SETTINGS_DIR_FALLBACK
        logger.info("[main] settings dir: %s", settings_dir)

        storage = LocalStorage(settings_dir)

        stored_theme = storage.get("settings.theme_mode") or "system"
        apply_theme(page, stored_theme)

        # Show a loading indicator immediately so the splash screen dismisses
        page.add(
            flet.Column(
                controls=[
                    flet.ProgressRing(color=flet.Colors.PRIMARY),
                    flet.Text(
                        "Загрузка...", color=flet.Colors.ON_SURFACE_VARIANT, size=14
                    ),
                ],
                alignment=flet.MainAxisAlignment.CENTER,
                horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                expand=True,
            )
        )
        page.update()

        stored_api_url = storage.get("settings.api_url")
        stored_ws_url = storage.get("settings.ws_url")
        state = AppState(
            secure_storage=storage,
            api_url=stored_api_url or "",
            ws_url=stored_ws_url or "",
            theme_mode=stored_theme,
        )

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
                    flet.Icon(flet.Icons.ERROR_OUTLINE, color=flet.Colors.ERROR, size=48),
                    flet.Text(
                        "Ошибка запуска",
                        size=18,
                        weight=flet.FontWeight.BOLD,
                        color=flet.Colors.ON_SURFACE,
                    ),
                    flet.Text(
                        str(exc),
                        size=12,
                        color=flet.Colors.ON_SURFACE_VARIANT,
                        selectable=True,
                    ),
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
