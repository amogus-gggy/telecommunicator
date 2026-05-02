from __future__ import annotations

import flet
import httpx

from api.http_client import APIClient, AuthError
from localization import t
from state import AppState, UserDTO
from storage.credentials import CredentialsStorage


def login_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"
    page.overlay.clear()

    server_url_field = flet.TextField(
        label=t("login.server_url"),
        value=state.api_url,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
    )
    username_field = flet.TextField(
        label=t("login.username"),
        autofocus=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
    )
    password_field = flet.TextField(
        label=t("login.password"),
        password=True,
        can_reveal_password=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
    )
    error_text = flet.Text("", color="#ea4335", visible=False, size=13)
    submit_btn = flet.ElevatedButton(
        t("login.submit"),
        width=300,
        style=flet.ButtonStyle(
            bgcolor="#008069",
            color="#ffffff",
            shape=flet.RoundedRectangleBorder(radius=8),
            padding=flet.padding.symmetric(vertical=16),
        ),
    )
    loading = flet.ProgressRing(visible=False, width=20, height=20, color="#008069")

    # Auto-login checkbox
    auto_login_checkbox = flet.Checkbox(
        label=t("login.auto_login"),
        value=False,
        visible=True,
    )

    # Initialize credentials storage
    creds_storage = None
    if state.secure_storage:
        creds_storage = CredentialsStorage(state.secure_storage)

    async def do_login(e: flet.ControlEvent | None = None) -> None:
        error_text.visible = False
        submit_btn.disabled = True
        loading.visible = True
        page.update()

        # Update API URLs if changed
        new_api_url = server_url_field.value.rstrip("/")
        if new_api_url != state.api_url:
            state.api_url = new_api_url
            # Derive WS URL: replace http with ws, keep host:port, append /ws
            if "://" in new_api_url:
                proto, rest = new_api_url.split("://", 1)
                ws_proto = "ws" if proto == "http" else "wss"
                state.ws_url = f"{ws_proto}://{rest}/ws"
            else:
                state.ws_url = f"ws://{new_api_url}/ws"
            
            if state.secure_storage:
                state.secure_storage.set("settings.api_url", state.api_url)
                state.secure_storage.set("settings.ws_url", state.ws_url)

            # Close existing clients to pick up new URL
            from api.http_client import close_shared_clients
            await close_shared_clients()

        client = APIClient(state=state)
        try:
            token_data = await client.login(
                username_field.value or "", password_field.value or ""
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

            # Save credentials for auto-login if checkbox is checked
            if creds_storage and auto_login_checkbox.value:
                creds_storage.save_credentials(
                    server_url=state.api_url,
                    username=username_field.value or "",
                    password=password_field.value or "",
                    auto_login=True,
                )

            me = await client.get_me()
            state.current_user = UserDTO(
                id=me["id"],
                username=me["username"],
                email=me["email"],
                display_name=me.get("display_name"),
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

    # Try auto-login if credentials exist
    async def try_auto_login() -> None:
        if not creds_storage:
            return

        stored_creds = creds_storage.get_credentials()
        if not stored_creds or not stored_creds.auto_login_enabled:
            return

        # Pre-fill the fields
        server_url_field.value = stored_creds.server_url
        username_field.value = stored_creds.username
        auto_login_checkbox.value = True

        # Get stored password
        stored_password = creds_storage.get_password()
        if stored_password:
            password_field.value = stored_password
            page.update()

            # Trigger auto-login
            await do_login()

    # Schedule auto-login attempt
    page.run_task(try_auto_login)

    def go_register(e: flet.ControlEvent) -> None:
        from views.register_view import register_view

        register_view(page, state)

    def go_deploy(e: flet.ControlEvent) -> None:
        from views.server_deploy_view import server_deploy_view

        server_deploy_view(page, state)

    async def do_logout(e: flet.ControlEvent) -> None:
        # Clear credentials on explicit logout
        await state.logout(clear_credentials=True)
        login_view(page, state)

    logout_btn = flet.TextButton(
        t("login.logout"),
        on_click=do_logout,
        visible=state.token is not None,
        style=flet.ButtonStyle(color="#008069"),
    )

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
                                flet.Text(
                                    t("login.subtitle"), size=14, color="#667781"
                                ),
                                flet.Divider(height=20, color=flet.Colors.TRANSPARENT),
                                server_url_field,
                                username_field,
                                password_field,
                                auto_login_checkbox,
                                error_text,
                                flet.Row(
                                    controls=[submit_btn, loading],
                                    alignment=flet.MainAxisAlignment.CENTER,
                                    vertical_alignment=flet.CrossAxisAlignment.CENTER,
                                ),
                                flet.TextButton(
                                    t("login.no_account"),
                                    on_click=go_register,
                                    style=flet.ButtonStyle(color="#008069"),
                                ),
                                flet.Divider(height=8, color=flet.Colors.TRANSPARENT),
                                flet.TextButton(
                                    t("login.deploy_server"),
                                    icon=flet.Icons.CLOUD_UPLOAD,
                                    on_click=go_deploy,
                                    style=flet.ButtonStyle(color="#667781"),
                                ),
                                logout_btn,
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
