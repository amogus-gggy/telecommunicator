from __future__ import annotations

import flet
import httpx

from api.http_client import APIClient, AuthError
from localization import t
from server_addr import build_api_urls, parse_handle
from state import AppState, UserDTO
from ui.theme import initials_avatar, primary_button, themed_field


def login_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = flet.Colors.SURFACE_CONTAINER
    page.overlay.clear()

    username_field = themed_field(
        label=t("login.username"),
        hint_text=t("login.username_hint"),
        autofocus=True,
    )
    password_field = themed_field(
        label=t("login.password"),
        password=True,
        can_reveal_password=True,
    )
    error_text = flet.Text("", color=flet.Colors.ERROR, visible=False, size=13)
    submit_btn = primary_button(t("login.submit"), expand=True)
    loading = flet.ProgressRing(
        visible=False, width=20, height=20, color=flet.Colors.PRIMARY
    )

    async def do_login(e: flet.ControlEvent) -> None:
        error_text.visible = False
        submit_btn.disabled = True
        loading.visible = True
        page.update()

        handle = username_field.value or ""
        username, server = parse_handle(handle)
        if "@" in handle and not server:
            error_text.value = t("login.error_handle_format")
            error_text.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
            return

        # Update API URLs if the server was specified in the handle
        if server:
            try:
                new_api_url, new_ws_url = build_api_urls(server)
            except ValueError:
                error_text.value = t("login.error_handle_format")
                error_text.visible = True
                submit_btn.disabled = False
                loading.visible = False
                page.update()
                return
            if new_api_url != state.api_url:
                state.api_url = new_api_url
                state.ws_url = new_ws_url
                if state.secure_storage:
                    state.secure_storage.set("settings.api_url", state.api_url)
                    state.secure_storage.set("settings.ws_url", state.ws_url)

                # Close existing clients to pick up new URL
                from api.http_client import close_shared_clients
                await close_shared_clients()

        client = APIClient(state=state)
        try:
            token_data = await client.login(
                username, password_field.value or ""
            )
            state.token = token_data["access_token"]

            encrypted_backup_b64 = token_data.get("encrypted_backup")
            if encrypted_backup_b64:
                try:
                    import base64
                    import logging
                    from crypto.key_backup import KeyBackupManager
                    from cryptography.exceptions import InvalidTag

                    logging.info("[Login] Decrypting backup (thread pool)...")
                    encrypted_backup = base64.b64decode(encrypted_backup_b64)
                    # PBKDF2 runs in thread pool — UI stays responsive
                    (
                        ed25519_priv,
                        x25519_priv,
                    ) = await KeyBackupManager.decrypt_backup_async(
                        encrypted_backup,
                        password_field.value or "",
                    )

                    # Store recovered keys in state
                    state.ed25519_private = ed25519_priv
                    state.x25519_private = x25519_priv
                    logging.info("[Login] Keys recovered and stored in state")
                except InvalidTag:
                    error_text.value = t("login.error_backup_decrypt")
                    error_text.visible = True
                    submit_btn.disabled = False
                    loading.visible = False
                    page.update()
                    return
                except Exception as backup_exc:
                    logging.error(
                        f"[Login] Backup decryption error: {backup_exc}", exc_info=True
                    )
                    error_text.value = t("login.error_backup_corrupted", exc=backup_exc)
                    error_text.visible = True
                    submit_btn.disabled = False
                    loading.visible = False
                    page.update()
                    return

            me = await client.get_me()
            state.current_user = UserDTO(
                id=me["id"],
                username=me["username"],
                email=me["email"],
                display_name=me.get("display_name"),
                server_name=me.get("server_name") or "",
            )
            from views.chat_list_view import chat_list_view

            chat_list_view(page, state)
        except AuthError:
            error_text.value = t("login.error_invalid")
            error_text.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        except (httpx.ConnectError, httpx.TimeoutException):
            error_text.value = t("login.error_connect")
            error_text.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        except Exception as exc:
            error_text.value = (
                t("login.error_server", exc=exc)
                if str(exc)
                else t("login.error_unknown")
            )
            error_text.visible = True
            submit_btn.disabled = False
            loading.visible = False
            page.update()
        finally:
            await client.aclose()

    submit_btn.on_click = do_login
    password_field.on_submit = do_login

    def go_register(e: flet.ControlEvent) -> None:
        from views.register_view import register_view

        register_view(page, state)

    async def do_logout(e: flet.ControlEvent) -> None:
        await state.logout()
        login_view(page, state)

    logout_btn = flet.TextButton(
        t("login.logout"),
        on_click=do_logout,
        visible=state.token is not None,
        style=flet.ButtonStyle(color=flet.Colors.PRIMARY),
    )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                flet.Container(expand=True),
                flet.Container(
                    content=flet.Column(
                        controls=[
                            initials_avatar("Telecommunicator", size=72),
                            flet.Text(
                                "Telecommunicator",
                                size=26,
                                weight=flet.FontWeight.BOLD,
                                color=flet.Colors.ON_SURFACE,
                            ),
                            flet.Text(
                                t("login.subtitle"),
                                size=14,
                                color=flet.Colors.ON_SURFACE_VARIANT,
                            ),
                            flet.Divider(height=24, color=flet.Colors.TRANSPARENT),
                            username_field,
                            password_field,
                            error_text,
                            flet.Row(
                                controls=[submit_btn, loading],
                                alignment=flet.MainAxisAlignment.CENTER,
                                vertical_alignment=flet.CrossAxisAlignment.CENTER,
                            ),
                            flet.TextButton(
                                t("login.no_account"),
                                on_click=go_register,
                                style=flet.ButtonStyle(color=flet.Colors.PRIMARY),
                            ),
                            logout_btn,
                        ],
                        alignment=flet.MainAxisAlignment.CENTER,
                        horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                        width=340,
                        spacing=12,
                    ),
                    padding=32,
                    border_radius=20,
                    bgcolor=flet.Colors.SURFACE,
                    border=flet.border.all(1, flet.Colors.OUTLINE_VARIANT),
                    shadow=flet.BoxShadow(
                        blur_radius=24,
                        spread_radius=-4,
                        color="#1A000000",
                        offset=flet.Offset(0, 8),
                    ),
                ),
                flet.Container(expand=True),
            ],
            alignment=flet.MainAxisAlignment.CENTER,
            horizontal_alignment=flet.CrossAxisAlignment.CENTER,
            expand=True,
        )
    )
    page.update()
