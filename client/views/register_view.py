from __future__ import annotations

import flet

from client.api.http_client import APIClient, ConflictError, ValidationError
from client.config import API_URL
from client.locale import t
from client.state import AppState, UserDTO


def register_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"

    username_field = flet.TextField(
        label=t("register.username"), autofocus=True, bgcolor="#ffffff", border_color="#e0e0e0", color="#111b21",
    )
    email_field = flet.TextField(
        label=t("register.email"), bgcolor="#ffffff", border_color="#e0e0e0", color="#111b21",
    )
    password_field = flet.TextField(
        label=t("register.password"),
        password=True,
        can_reveal_password=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
    )

    username_error = flet.Text("", color="#ea4335", visible=False, size=12)
    email_error = flet.Text("", color="#ea4335", visible=False, size=12)
    password_error = flet.Text("", color="#ea4335", visible=False, size=12)
    general_error = flet.Text("", color="#ea4335", visible=False)

    submit_btn = flet.ElevatedButton(
        t("register.submit"),
        width=300,
        style=flet.ButtonStyle(
            bgcolor="#008069",
            color="#ffffff",
            shape=flet.RoundedRectangleBorder(radius=8),
            padding=flet.padding.symmetric(vertical=16),
        ),
    )
    loading = flet.ProgressRing(visible=False, width=20, height=20, color="#008069")

    def _clear_errors() -> None:
        for txt in (username_error, email_error, password_error, general_error):
            txt.value = ""
            txt.visible = False

    async def do_register(e: flet.ControlEvent) -> None:
        _clear_errors()
        submit_btn.disabled = True
        loading.visible = True
        page.update()

        client = APIClient(base_url=API_URL, state=state)
        try:
            await client.register(
                username=username_field.value or "",
                email=email_field.value or "",
                password=password_field.value or "",
            )
            token_data = await client.login(
                username=username_field.value or "",
                password=password_field.value or "",
            )
            state.token = token_data["access_token"]
            me = await client.get_me()
            state.current_user = UserDTO(
                id=me["id"],
                username=me["username"],
                email=me["email"],
                display_name=me.get("display_name"),
            )
            from client.views.chat_list_view import chat_list_view
            chat_list_view(page, state)
        except ConflictError as exc:
            msg = exc.message.lower()
            if "username" in msg:
                username_error.value = exc.message
                username_error.visible = True
            elif "email" in msg:
                email_error.value = exc.message
                email_error.visible = True
            else:
                general_error.value = exc.message
                general_error.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        except ValidationError as exc:
            msg = exc.message.lower()
            if "password" in msg:
                password_error.value = exc.message
                password_error.visible = True
            elif "email" in msg:
                email_error.value = exc.message
                email_error.visible = True
            elif "username" in msg:
                username_error.value = exc.message
                username_error.visible = True
            else:
                general_error.value = exc.message
                general_error.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        except Exception as exc:
            general_error.value = t("register.error_server", exc=exc)
            general_error.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        finally:
            await client.aclose()

    submit_btn.on_click = do_register
    password_field.on_submit = do_register

    def go_login(e: flet.ControlEvent) -> None:
        from client.views.login_view import login_view
        login_view(page, state)

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                flet.Container(expand=True),
                flet.Card(
                    content=flet.Container(
                        content=flet.Column(
                            controls=[
                                flet.Icon(flet.Icons.CHAT, size=56, color="#008069"),
                                flet.Text(
                                    "Telecommunicator",
                                    size=28,
                                    weight=flet.FontWeight.BOLD,
                                    color="#111b21",
                                ),
                                flet.Text(t("register.subtitle"), size=14, color="#667781"),
                                flet.Divider(height=20, color=flet.Colors.TRANSPARENT),
                                username_field,
                                username_error,
                                email_field,
                                email_error,
                                password_field,
                                password_error,
                                general_error,
                                flet.Row(
                                    controls=[submit_btn, loading],
                                    alignment=flet.MainAxisAlignment.CENTER,
                                    vertical_alignment=flet.CrossAxisAlignment.CENTER,
                                ),
                                flet.TextButton(
                                    t("register.have_account"),
                                    on_click=go_login,
                                    style=flet.ButtonStyle(color="#008069"),
                                ),
                            ],
                            alignment=flet.MainAxisAlignment.CENTER,
                            horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                            width=320,
                            spacing=12,
                        ),
                        padding=32,
                    ),
                    elevation=2,
                    bgcolor="#ffffff",
                ),
                flet.Container(expand=True),
            ],
            alignment=flet.MainAxisAlignment.CENTER,
            horizontal_alignment=flet.CrossAxisAlignment.CENTER,
            expand=True,
        )
    )
    page.update()
