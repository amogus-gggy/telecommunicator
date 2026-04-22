from __future__ import annotations

import flet

from client.api.http_client import APIClient, AuthError, ValidationError
from client.config import API_URL
from client.locale import t, set_locale, get_locale, AVAILABLE_LOCALES
from client.state import AppState


def profile_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"
    user = state.current_user

    display_name_info = flet.Text(
        t("profile.display_name_label", name=user.display_name or t("profile.display_name_not_set") if user else ""),
        size=14,
        color="#111b21",
    )

    display_name_field = flet.TextField(
        label=t("profile.new_display_name"),
        value=user.display_name or "" if user else "",
        expand=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    display_name_error = flet.Text("", color="#ea4335", visible=False, size=12)

    async def _save_display_name(e: flet.ControlEvent) -> None:
        display_name_error.visible = False
        page.update()
        client = APIClient(base_url=API_URL, state=state)
        try:
            updated = await client.update_profile(display_name=display_name_field.value or "")
            new_dn = updated.get("display_name")
            if state.current_user is not None:
                state.current_user.display_name = new_dn
            display_name_info.value = t(
                "profile.display_name_label",
                name=new_dn or t("profile.display_name_not_set"),
            )
            page.snack_bar = flet.SnackBar(
                flet.Text(t("profile.display_name_updated"), color="#ffffff"),
                open=True, bgcolor="#008069",
            )
            page.update()
        except ValidationError:
            display_name_error.value = t("profile.display_name_error")
            display_name_error.visible = True
            page.update()
        except AuthError:
            state.token = None
            page.snack_bar = flet.SnackBar(
                flet.Text(t("profile.session_expired"), color="#ffffff"),
                open=True, bgcolor="#ea4335",
            )
            page.update()
            from client.views.login_view import login_view
            login_view(page, state)
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()
        finally:
            await client.aclose()

    current_password_field = flet.TextField(
        label=t("profile.current_password"),
        password=True,
        can_reveal_password=True,
        expand=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    new_password_field = flet.TextField(
        label=t("profile.new_password"),
        password=True,
        can_reveal_password=True,
        expand=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    password_error = flet.Text("", color="#ea4335", visible=False, size=12)

    async def _change_password(e: flet.ControlEvent) -> None:
        password_error.visible = False
        page.update()
        client = APIClient(base_url=API_URL, state=state)
        try:
            await client.change_password(
                current_password=current_password_field.value or "",
                new_password=new_password_field.value or "",
            )
            current_password_field.value = ""
            new_password_field.value = ""
            page.snack_bar = flet.SnackBar(
                flet.Text(t("profile.password_changed"), color="#ffffff"),
                open=True, bgcolor="#008069",
            )
            page.update()
        except AuthError:
            password_error.value = t("profile.password_incorrect")
            password_error.visible = True
            page.update()
        except ValidationError:
            password_error.value = t("profile.password_too_short")
            password_error.visible = True
            page.update()
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()
        finally:
            await client.aclose()

    def _go_back(e: flet.ControlEvent) -> None:
        from client.views.chat_list_view import chat_list_view
        chat_list_view(page, state)

    # --- Language setting ---
    language_dropdown = flet.Dropdown(
        value=get_locale(),
        options=[flet.dropdown.Option(key=code, text=name) for code, name in AVAILABLE_LOCALES],
        expand=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
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
    alignment_dropdown = flet.Dropdown(
        value=state.message_alignment,
        options=[flet.dropdown.Option(key=v, text=label) for label, v in _alignment_options],
        expand=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )

    def _on_alignment_change(e: flet.ControlEvent) -> None:
        import logging
        log = logging.getLogger(__name__)
        new_val = alignment_dropdown.value or "default"
        log.info("[profile_view] Dropdown changed to %r", new_val)
        state.message_alignment = new_val
        if state.secure_storage is not None:
            state.secure_storage.set("settings.message_alignment", state.message_alignment)
        page.snack_bar = flet.SnackBar(
            flet.Text(t("profile.setting_saved"), color="#ffffff"),
            open=True, bgcolor="#008069",
        )
        page.update()

    alignment_dropdown.on_change = _on_alignment_change

    def _save_alignment(e: flet.ControlEvent) -> None:
        import logging
        log = logging.getLogger(__name__)
        new_val = alignment_dropdown.value or "default"
        log.info("[profile_view] Save button clicked, value=%r", new_val)
        state.message_alignment = new_val
        if state.secure_storage is not None:
            state.secure_storage.set("settings.message_alignment", new_val)
        page.snack_bar = flet.SnackBar(
            flet.Text(t("profile.setting_saved"), color="#ffffff"),
            open=True, bgcolor="#008069",
        )
        page.update()

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                flet.Container(
                    content=flet.Row(
                        controls=[
                            flet.IconButton(
                                icon=flet.Icons.ARROW_BACK,
                                on_click=_go_back,
                                tooltip=t("profile.back"),
                                icon_color="#ffffff",
                            ),
                            flet.Text(
                                t("profile.title"),
                                size=22,
                                weight=flet.FontWeight.BOLD,
                                color="#ffffff",
                            ),
                        ],
                        vertical_alignment=flet.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#008069",
                    padding=flet.padding.symmetric(horizontal=8, vertical=8),
                ),
                flet.Container(
                    content=flet.Column(
                        controls=[
                            flet.Card(
                                content=flet.Container(
                                    content=flet.Column(
                                        controls=[
                                            flet.Text(
                                                t("profile.account_info"),
                                                size=16,
                                                weight=flet.FontWeight.W_600,
                                                color="#111b21",
                                            ),
                                            flet.Divider(height=8),
                                            flet.Row(
                                                controls=[
                                                    flet.Icon(flet.Icons.BADGE, color="#667781"),
                                                    flet.Text(
                                                        t("profile.username", username=user.username if user else ""),
                                                        size=14, color="#111b21",
                                                    ),
                                                ],
                                                spacing=12,
                                            ),
                                            flet.Row(
                                                controls=[
                                                    flet.Icon(flet.Icons.EMAIL, color="#667781"),
                                                    flet.Text(
                                                        t("profile.email", email=user.email if user else ""),
                                                        size=14, color="#111b21",
                                                    ),
                                                ],
                                                spacing=12,
                                            ),
                                            flet.Row(
                                                controls=[
                                                    flet.Icon(flet.Icons.LABEL, color="#667781"),
                                                    display_name_info,
                                                ],
                                                spacing=12,
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    padding=20,
                                ),
                                bgcolor="#ffffff",
                                elevation=1,
                            ),
                            flet.Card(
                                content=flet.Container(
                                    content=flet.Column(
                                        controls=[
                                            flet.Text(
                                                t("profile.update_display_name"),
                                                size=16,
                                                weight=flet.FontWeight.W_600,
                                                color="#111b21",
                                            ),
                                            flet.Divider(height=8),
                                            flet.Row(controls=[display_name_field]),
                                            display_name_error,
                                            flet.ElevatedButton(
                                                t("profile.save"),
                                                on_click=_save_display_name,
                                                style=flet.ButtonStyle(
                                                    bgcolor="#008069",
                                                    color="#ffffff",
                                                    shape=flet.RoundedRectangleBorder(radius=8),
                                                    padding=flet.padding.symmetric(vertical=12, horizontal=24),
                                                ),
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    padding=20,
                                ),
                                bgcolor="#ffffff",
                                elevation=1,
                            ),
                            flet.Card(
                                content=flet.Container(
                                    content=flet.Column(
                                        controls=[
                                            flet.Text(
                                                t("profile.change_password"),
                                                size=16,
                                                weight=flet.FontWeight.W_600,
                                                color="#111b21",
                                            ),
                                            flet.Divider(height=8),
                                            flet.Row(controls=[current_password_field]),
                                            flet.Row(controls=[new_password_field]),
                                            password_error,
                                            flet.ElevatedButton(
                                                t("profile.change_password"),
                                                on_click=_change_password,
                                                style=flet.ButtonStyle(
                                                    bgcolor="#008069",
                                                    color="#ffffff",
                                                    shape=flet.RoundedRectangleBorder(radius=8),
                                                    padding=flet.padding.symmetric(vertical=12, horizontal=24),
                                                ),
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    padding=20,
                                ),
                                bgcolor="#ffffff",
                                elevation=1,
                            ),
                            flet.Card(
                                content=flet.Container(
                                    content=flet.Column(
                                        controls=[
                                            flet.Text(
                                                t("language.title"),
                                                size=16,
                                                weight=flet.FontWeight.W_600,
                                                color="#111b21",
                                            ),
                                            flet.Divider(height=8),
                                            flet.Row(controls=[language_dropdown]),
                                            flet.ElevatedButton(
                                                t("language.apply"),
                                                on_click=_apply_language,
                                                style=flet.ButtonStyle(
                                                    bgcolor="#008069",
                                                    color="#ffffff",
                                                    shape=flet.RoundedRectangleBorder(radius=8),
                                                    padding=flet.padding.symmetric(vertical=12, horizontal=24),
                                                ),
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    padding=20,
                                ),
                                bgcolor="#ffffff",
                                elevation=1,
                            ),
                            flet.Card(
                                content=flet.Container(
                                    content=flet.Column(
                                        controls=[
                                            flet.Text(
                                                t("profile.message_alignment"),
                                                size=16,
                                                weight=flet.FontWeight.W_600,
                                                color="#111b21",
                                            ),
                                            flet.Divider(height=8),
                                            flet.Row(controls=[alignment_dropdown]),
                                            flet.ElevatedButton(
                                                t("profile.save"),
                                                on_click=_save_alignment,
                                                style=flet.ButtonStyle(
                                                    bgcolor="#008069",
                                                    color="#ffffff",
                                                    shape=flet.RoundedRectangleBorder(radius=8),
                                                    padding=flet.padding.symmetric(vertical=12, horizontal=24),
                                                ),
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    padding=20,
                                ),
                                bgcolor="#ffffff",
                                elevation=1,
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
