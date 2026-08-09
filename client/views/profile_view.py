from __future__ import annotations

import sys

import flet

from api.http_client import APIClient, AuthError, ValidationError
from localization import t, set_locale, get_locale, AVAILABLE_LOCALES
from state import AppState
from ui.theme import (
    initials_avatar,
    primary_button,
    set_theme_mode,
    snack,
    surface_app_bar,
    themed_field,
)


def _section_card(controls: list) -> flet.Container:
    return flet.Container(
        content=flet.Column(controls=controls, spacing=12),
        padding=20,
        bgcolor=flet.Colors.SURFACE,
        border_radius=16,
        border=flet.border.all(1, flet.Colors.OUTLINE_VARIANT),
    )


def _section_title(text: str) -> flet.Text:
    return flet.Text(
        text, size=16, weight=flet.FontWeight.W_600, color=flet.Colors.ON_SURFACE
    )


def _section_divider() -> flet.Divider:
    return flet.Divider(height=8, color=flet.Colors.OUTLINE_VARIANT)


def _themed_dropdown(**kwargs) -> flet.Dropdown:
    defaults = dict(
        filled=True,
        bgcolor=flet.Colors.SURFACE_CONTAINER_LOW,
        border_radius=12,
        border_color=flet.Colors.TRANSPARENT,
        focused_border_color=flet.Colors.PRIMARY,
        color=flet.Colors.ON_SURFACE,
        text_size=15,
        content_padding=flet.padding.symmetric(horizontal=16, vertical=12),
    )
    defaults.update(kwargs)
    return flet.Dropdown(**defaults)


def profile_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = flet.Colors.SURFACE_CONTAINER
    page.overlay.clear()
    user = state.current_user

    display_name_info = flet.Text(
        t(
            "profile.display_name_label",
            name=user.display_name or t("profile.display_name_not_set") if user else "",
        ),
        size=14,
        color=flet.Colors.ON_SURFACE,
    )

    display_name_field = themed_field(
        label=t("profile.new_display_name"),
        value=user.display_name or "" if user else "",
        expand=True,
    )
    display_name_error = flet.Text("", color=flet.Colors.ERROR, visible=False, size=12)

    async def _save_display_name(e: flet.ControlEvent) -> None:
        display_name_error.visible = False
        page.update()
        client = APIClient(state=state)
        try:
            updated = await client.update_profile(
                display_name=display_name_field.value or ""
            )
            new_dn = updated.get("display_name")
            if state.current_user is not None:
                state.current_user.display_name = new_dn
            display_name_info.value = t(
                "profile.display_name_label",
                name=new_dn or t("profile.display_name_not_set"),
            )
            snack(page, t("profile.display_name_updated"))
        except ValidationError:
            display_name_error.value = t("profile.display_name_error")
            display_name_error.visible = True
            page.update()
        except AuthError:
            state.token = None
            snack(page, t("profile.session_expired"), ok=False)
            from views.login_view import login_view

            login_view(page, state)
        except Exception as exc:
            snack(page, str(exc), ok=False)
        finally:
            await client.aclose()

    current_password_field = themed_field(
        label=t("profile.current_password"),
        password=True,
        can_reveal_password=True,
        expand=True,
    )
    new_password_field = themed_field(
        label=t("profile.new_password"),
        password=True,
        can_reveal_password=True,
        expand=True,
    )
    password_error = flet.Text("", color=flet.Colors.ERROR, visible=False, size=12)

    async def _change_password(e: flet.ControlEvent) -> None:
        password_error.visible = False
        page.update()
        client = APIClient(state=state)
        try:
            await client.change_password(
                current_password=current_password_field.value or "",
                new_password=new_password_field.value or "",
            )
            current_password_field.value = ""
            new_password_field.value = ""
            snack(page, t("profile.password_changed"))
        except AuthError:
            password_error.value = t("profile.password_incorrect")
            password_error.visible = True
            page.update()
        except ValidationError:
            password_error.value = t("profile.password_too_short")
            password_error.visible = True
            page.update()
        except Exception as exc:
            snack(page, str(exc), ok=False)
        finally:
            await client.aclose()

    def _go_back(e: flet.ControlEvent) -> None:
        from views.chat_list_view import chat_list_view

        chat_list_view(page, state)

    # --- Language setting ---
    language_dropdown = _themed_dropdown(
        value=get_locale(),
        options=[
            flet.dropdown.Option(key=code, text=name)
            for code, name in AVAILABLE_LOCALES
        ],
        expand=True,
    )

    def _apply_language(e: flet.ControlEvent) -> None:
        new_locale = language_dropdown.value or "ru"
        if new_locale == get_locale():
            return
        set_locale(new_locale)
        if state.secure_storage is not None:
            state.secure_storage.set("settings.locale", new_locale)
        # Reload the profile page so all strings re-render in the new language
        profile_view(page, state)

    _alignment_options = [
        (t("profile.alignment_default"), "default"),
        (t("profile.alignment_left"), "left"),
        (t("profile.alignment_right"), "right"),
    ]
    alignment_dropdown = _themed_dropdown(
        value=state.message_alignment,
        options=[
            flet.dropdown.Option(key=v, text=label) for label, v in _alignment_options
        ],
        expand=True,
    )

    def _on_alignment_change(e: flet.ControlEvent) -> None:
        import logging

        log = logging.getLogger(__name__)
        new_val = alignment_dropdown.value or "default"
        log.info("[profile_view] Dropdown changed to %r", new_val)
        state.message_alignment = new_val
        if state.secure_storage is not None:
            state.secure_storage.set(
                "settings.message_alignment", state.message_alignment
            )
        snack(page, t("profile.setting_saved"))

    alignment_dropdown.on_change = _on_alignment_change

    def _save_alignment(e: flet.ControlEvent) -> None:
        import logging

        log = logging.getLogger(__name__)
        new_val = alignment_dropdown.value or "default"
        log.info("[profile_view] Save button clicked, value=%r", new_val)
        state.message_alignment = new_val
        if state.secure_storage is not None:
            state.secure_storage.set("settings.message_alignment", new_val)
        snack(page, t("profile.setting_saved"))

    # --- Theme setting ---
    theme_options = [
        ("system", t("theme.system")),
        ("light", t("theme.light")),
        ("dark", t("theme.dark")),
    ]
    theme_dropdown = _themed_dropdown(
        value=state.theme_mode,
        options=[
            flet.dropdown.Option(key=value, text=label) for value, label in theme_options
        ],
        expand=True,
    )

    def _save_theme(e: flet.ControlEvent) -> None:
        new_mode = theme_dropdown.value or "system"
        state.theme_mode = new_mode
        if state.secure_storage is not None:
            state.secure_storage.set("settings.theme_mode", new_mode)
        set_theme_mode(page, new_mode)
        snack(page, t("profile.setting_saved"))

    # --- Server setting ---
    server_url_field = themed_field(
        label=t("profile.server_url"),
        value=state.api_url,
        expand=True,
    )

    async def _save_server_url(e: flet.ControlEvent) -> None:
        new_url = server_url_field.value.rstrip("/")
        if new_url == state.api_url:
            return

        state.api_url = new_url
        if "://" in new_url:
            proto, rest = new_url.split("://", 1)
            ws_proto = "ws" if proto == "http" else "wss"
            state.ws_url = f"{ws_proto}://{rest}/ws"
        else:
            state.ws_url = f"ws://{new_url}/ws"

        if state.secure_storage:
            state.secure_storage.set("settings.api_url", state.api_url)
            state.secure_storage.set("settings.ws_url", state.ws_url)

        # Logout and redirect to login as switching server kills current session
        await state.logout()
        from views.login_view import login_view
        login_view(page, state)

    def _info_row(icon: str, text: flet.Control | str) -> flet.Row:
        return flet.Row(
            controls=[
                flet.Icon(icon, color=flet.Colors.ON_SURFACE_VARIANT, size=20),
                text
                if isinstance(text, flet.Control)
                else flet.Text(text, size=14, color=flet.Colors.ON_SURFACE),
            ],
            spacing=12,
        )

    avatar_name = (
        (user.display_name or user.username) if user else "?"
    )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                surface_app_bar(t("profile.title"), on_back=_go_back),
                flet.Container(
                    content=flet.Column(
                        controls=[
                            _section_card(
                                [
                                    flet.Row(
                                        controls=[
                                            initials_avatar(avatar_name, size=64),
                                            flet.Column(
                                                controls=[
                                                    _info_row(
                                                        flet.Icons.BADGE,
                                                        t(
                                                            "profile.username",
                                                            username=user.username
                                                            if user
                                                            else "",
                                                        ),
                                                    ),
                                                    _info_row(
                                                        flet.Icons.EMAIL,
                                                        t(
                                                            "profile.email",
                                                            email=user.email
                                                            if user
                                                            else "",
                                                        ),
                                                    ),
                                                    _info_row(
                                                        flet.Icons.LABEL,
                                                        display_name_info,
                                                    ),
                                                ],
                                                spacing=8,
                                                expand=True,
                                            ),
                                        ],
                                        spacing=16,
                                        vertical_alignment=flet.CrossAxisAlignment.CENTER,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("profile.update_display_name")),
                                    _section_divider(),
                                    display_name_field,
                                    display_name_error,
                                    primary_button(
                                        t("profile.save"),
                                        on_click=_save_display_name,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("profile.change_password")),
                                    _section_divider(),
                                    current_password_field,
                                    new_password_field,
                                    password_error,
                                    primary_button(
                                        t("profile.change_password"),
                                        on_click=_change_password,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("language.title")),
                                    _section_divider(),
                                    language_dropdown,
                                    primary_button(
                                        t("language.apply"),
                                        on_click=_apply_language,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("profile.message_alignment")),
                                    _section_divider(),
                                    alignment_dropdown,
                                    primary_button(
                                        t("profile.save"),
                                        on_click=_save_alignment,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("theme.title")),
                                    _section_divider(),
                                    theme_dropdown,
                                    primary_button(
                                        t("profile.save"),
                                        on_click=_save_theme,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    _section_title(t("profile.server_settings")),
                                    _section_divider(),
                                    server_url_field,
                                    primary_button(
                                        t("profile.save"),
                                        on_click=_save_server_url,
                                    ),
                                ]
                            ),
                            _section_card(
                                [
                                    flet.Text(
                                        "Dev",
                                        size=16,
                                        weight=flet.FontWeight.W_600,
                                        color=flet.Colors.ERROR,
                                    ),
                                    _section_divider(),
                                    flet.ElevatedButton(
                                        "Exit (show logs)",
                                        icon=flet.Icons.BUG_REPORT,
                                        on_click=lambda _: sys.exit(100),
                                        style=flet.ButtonStyle(
                                            bgcolor=flet.Colors.ERROR,
                                            color=flet.Colors.ON_ERROR,
                                            shape=flet.RoundedRectangleBorder(
                                                radius=12
                                            ),
                                            padding=flet.padding.symmetric(
                                                vertical=14
                                            ),
                                        ),
                                    ),
                                ]
                            ),
                        ],
                        spacing=12,
                        scroll=flet.ScrollMode.AUTO,
                    ),
                    padding=16,
                    expand=True,
                ),
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()
