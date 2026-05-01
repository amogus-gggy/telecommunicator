from __future__ import annotations

import flet

from api.http_client import APIClient, ConflictError, ValidationError
from localization import t
from state import AppState, UserDTO


def _generate_keypairs():
    """Run in a thread pool — generates both keypairs synchronously."""
    from crypto.key_generator import KeyGenerator

    ed25519_priv, ed25519_pub = KeyGenerator.generate_identity_keypair()
    x25519_priv, x25519_pub = KeyGenerator.generate_prekey_keypair()
    return ed25519_priv, ed25519_pub, x25519_priv, x25519_pub


def register_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"
    page.overlay.clear()

    username_field = flet.TextField(
        label=t("register.username"),
        autofocus=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
    )
    email_field = flet.TextField(
        label=t("register.email"),
        bgcolor="#ffffff",
        border_color="#e0e0e0",
        color="#111b21",
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

        client = APIClient(state=state)
        try:
            import asyncio
            import base64
            import logging
            from crypto.key_generator import KeyGenerator
            from crypto.key_backup import KeyBackupManager

            logging.info("[Registration] Generating keypairs (thread pool)...")
            # Run blocking key generation off the event loop
            (
                ed25519_priv,
                ed25519_pub,
                x25519_priv,
                x25519_pub,
            ) = await asyncio.to_thread(_generate_keypairs)

            # Serialize public keys
            ed25519_pub_bytes = KeyGenerator.serialize_public_key(ed25519_pub)
            x25519_pub_bytes = KeyGenerator.serialize_public_key(x25519_pub)

            # Create encrypted backup — PBKDF2 runs in thread pool
            logging.info("[Registration] Creating encrypted backup (thread pool)...")
            encrypted_backup = await KeyBackupManager.encrypt_backup_async(
                ed25519_priv,
                x25519_priv,
                password_field.value or "",
            )

            # Base64-encode for transmission
            ed25519_pub_b64 = base64.b64encode(ed25519_pub_bytes).decode("utf-8")
            x25519_pub_b64 = base64.b64encode(x25519_pub_bytes).decode("utf-8")
            encrypted_backup_b64 = base64.b64encode(encrypted_backup).decode("utf-8")

            logging.info("[Registration] Registering user with server...")
            await client.register(
                username=username_field.value or "",
                email=email_field.value or "",
                password=password_field.value or "",
                identity_pub_ed25519=ed25519_pub_b64,
                identity_pub_x25519=x25519_pub_b64,
                encrypted_backup=encrypted_backup_b64,
            )

            # Store private keys in state
            state.ed25519_private = ed25519_priv
            state.x25519_private = x25519_priv
            logging.info("[Registration] Keys stored in state")

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
            from views.chat_list_view import chat_list_view

            chat_list_view(page, state)
        except Exception as exc:
            # Handle key generation errors
            import logging

            logging.error(f"[Registration] Error: {exc}", exc_info=True)

            msg = str(exc).lower()
            if "cryptographic" in msg or "key generation" in msg:
                general_error.value = t("register.error_crypto", exc=exc)
                general_error.visible = True
            elif isinstance(exc, ConflictError):
                if "username" in msg:
                    username_error.value = exc.message
                    username_error.visible = True
                elif "email" in msg:
                    email_error.value = exc.message
                    email_error.visible = True
                else:
                    general_error.value = exc.message
                    general_error.visible = True
            elif isinstance(exc, ValidationError):
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
            else:
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
        from views.login_view import login_view

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
                                flet.Text(
                                    t("register.subtitle"), size=14, color="#667781"
                                ),
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
