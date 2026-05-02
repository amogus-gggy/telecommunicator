"""Server deployment and management view."""

from __future__ import annotations

import logging

import flet
from deployer import SSHCredentials, ServerManager, DeploymentError
from localization import t
from state import AppState
from storage.credentials import SSHCredentialsStorage

logger = logging.getLogger(__name__)


def server_deploy_view(page: flet.Page, state: AppState) -> None:
    """View for deploying and managing self-hosted servers."""
    page.bgcolor = "#f0f2f5"
    page.padding = 20

    # SSH Connection Form
    host_field = flet.TextField(
        label=t("deploy.host"),
        hint_text="192.168.1.100 or vps.example.com",
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    port_field = flet.TextField(
        label=t("deploy.port"),
        value="22",
        width=80,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    username_field = flet.TextField(
        label=t("deploy.username"),
        value="root",
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    password_field = flet.TextField(
        label=t("deploy.password"),
        password=True,
        can_reveal_password=True,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    key_field = flet.TextField(
        label=t("deploy.ssh_key"),
        hint_text="Paste private key or leave empty to use password",
        multiline=True,
        min_lines=3,
        max_lines=5,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )

    # Server Settings
    server_port_field = flet.TextField(
        label=t("deploy.server_port"),
        value="8000",
        width=100,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    max_file_size_field = flet.TextField(
        label=f"{t('deploy.max_file_size')} (MB)",
        value="100",
        width=150,
        bgcolor="#ffffff",
        border_color="#e0e0e0",
    )
    force_reinstall_checkbox = flet.Checkbox(
        label="Force reinstall (remove existing)",
        value=False,
    )

    # Status and Progress
    status_text = flet.Text("", color="#667781", size=14)
    progress_ring = flet.ProgressRing(visible=False, width=20, height=20)
    log_output = flet.ListView(
        expand=True,
        spacing=2,
        auto_scroll=True,
    )
    log_card = flet.Card(
        content=flet.Container(
            content=log_output,
            padding=10,
            height=200,
            bgcolor="#1e1e1e",
        ),
        visible=False,
    )

    # Action Buttons
    connect_btn = flet.Button(
        t("deploy.connect"),
        bgcolor="#008069",
        color="#ffffff",
    )
    deploy_btn = flet.Button(
        t("deploy.deploy"),
        bgcolor="#008069",
        color="#ffffff",
        visible=False,
    )
    start_btn = flet.Button(
        t("deploy.start"),
        bgcolor="#00a884",
        color="#ffffff",
        visible=False,
    )
    stop_btn = flet.Button(
        t("deploy.stop"),
        bgcolor="#ea4335",
        color="#ffffff",
        visible=False,
    )
    back_btn = flet.TextButton(
        t("deploy.back"),
        on_click=lambda e: _go_back(),
        style=flet.ButtonStyle(color="#667781"),
    )

    # Server manager instance
    manager: ServerManager | None = None
    is_connected = False
    is_installed = False

    # SSH credentials storage
    ssh_storage = SSHCredentialsStorage(state.secure_storage) if state.secure_storage else None

    def log(message: str) -> None:
        """Add log message to output."""
        log_output.controls.append(
            flet.Text(message, color="#d4d4d4", size=12, font_family="Consolas")
        )
        page.update()

    def update_status(message: str, color: str = "#667781") -> None:
        """Update status text."""
        status_text.value = message
        status_text.color = color
        page.update()

    def set_buttons(connected: bool = False, installed: bool = False) -> None:
        """Update button states."""
        nonlocal is_connected, is_installed
        is_connected = connected
        is_installed = installed

        connect_btn.visible = not connected
        deploy_btn.visible = connected and not installed
        start_btn.visible = connected and installed
        stop_btn.visible = connected and installed
        force_reinstall_checkbox.visible = connected
        page.update()

    # Load saved SSH credentials
    def load_saved_ssh_creds() -> None:
        if not ssh_storage:
            return
        saved = ssh_storage.get_ssh_credentials()
        if saved:
            host_field.value = saved.host
            port_field.value = str(saved.port)
            username_field.value = saved.username
            # Password and key are not loaded for security
            page.update()

    # Save SSH credentials
    def save_ssh_creds() -> None:
        if not ssh_storage:
            return
        ssh_storage.save_ssh_credentials(
            host=host_field.value or "",
            port=int(port_field.value or 22),
            username=username_field.value or "root",
            password=password_field.value or None,
            private_key=key_field.value or None,
        )

    async def do_connect(e: flet.ControlEvent | None = None) -> None:
        """Connect to SSH server."""
        nonlocal manager
        logger.info("[do_connect] Starting connection...")

        progress_ring.visible = True
        connect_btn.disabled = True
        update_status(t("deploy.connecting"))
        page.update()

        try:
            creds = SSHCredentials(
                host=host_field.value or "",
                username=username_field.value or "root",
                password=password_field.value or None,
                private_key=key_field.value or None,
                port=int(port_field.value or 22),
            )

            manager = ServerManager(creds)
            manager.connect()

            # Save credentials on successful connection
            save_ssh_creds()
            logger.info("[do_connect] Credentials saved, checking status...")

            # Check server status
            status = manager.check_server_status()
            logger.info(f"[do_connect] Server status: {status}")

            if status["installed"]:
                update_status(
                    t("deploy.status_installed", port=status.get("port", "?")),
                    "#00a884"
                )
                set_buttons(connected=True, installed=True)
            else:
                update_status(t("deploy.status_not_installed"), "#ff9800")
                set_buttons(connected=True, installed=False)

            log_card.visible = True

        except DeploymentError as ex:
            update_status(str(ex), "#ea4335")
            set_buttons(connected=False)
        except Exception as ex:
            update_status(f"{t('deploy.error')}: {ex}", "#ea4335")
            set_buttons(connected=False)
        finally:
            progress_ring.visible = False
            page.update()

    async def do_deploy(e: flet.ControlEvent | None = None) -> None:
        """Deploy server to remote host."""
        logger.info("[do_deploy] Button clicked, starting deployment...")

        if not manager:
            logger.error("[do_deploy] No manager available")
            update_status("Not connected", "#ea4335")
            return

        progress_ring.visible = True
        deploy_btn.disabled = True
        update_status(t("deploy.deploying"))
        page.update()
        logger.info("[do_deploy] UI updated, starting deploy...")

        try:
            config = {
                "server_name": "Self-Hosted Telecommunicator",
                "limits": {
                    "file_upload": {
                        "max_file_size_mb": int(max_file_size_field.value or 100)
                    }
                }
            }

            success = manager.deploy(
                port=int(server_port_field.value or 8000),
                config=config,
                progress_callback=log,
                force_reinstall=force_reinstall_checkbox.value,
            )

            if success:
                update_status(t("deploy.success"), "#00a884")
                set_buttons(connected=True, installed=True)
            else:
                update_status(t("deploy.failed"), "#ea4335")

        except DeploymentError as ex:
            log(f"ERROR: {ex}")
            update_status(str(ex), "#ea4335")
        except Exception as ex:
            log(f"ERROR: {ex}")
            update_status(f"{t('deploy.error')}: {ex}", "#ea4335")
        finally:
            progress_ring.visible = False
            page.update()

    async def do_start(e: flet.ControlEvent) -> None:
        """Start server service."""
        if not manager:
            return

        progress_ring.visible = True
        page.update()

        try:
            if manager.start_server():
                update_status(t("deploy.started"), "#00a884")
            else:
                update_status(t("deploy.start_failed"), "#ea4335")
        except Exception as ex:
            update_status(str(ex), "#ea4335")
        finally:
            progress_ring.visible = False
            page.update()

    async def do_stop(e: flet.ControlEvent) -> None:
        """Stop server service."""
        if not manager:
            return

        progress_ring.visible = True
        page.update()

        try:
            if manager.stop_server():
                update_status(t("deploy.stopped"), "#ff9800")
            else:
                update_status(t("deploy.stop_failed"), "#ea4335")
        except Exception as ex:
            update_status(str(ex), "#ea4335")
        finally:
            progress_ring.visible = False
            page.update()

    def _go_back() -> None:
        """Return to login view."""
        if manager:
            try:
                manager.disconnect()
            except Exception:
                pass
        from views.login_view import login_view
        login_view(page, state)

    # Wire up events
    connect_btn.on_click = do_connect
    deploy_btn.on_click = do_deploy
    start_btn.on_click = do_start
    stop_btn.on_click = do_stop

    # Load saved SSH credentials
    load_saved_ssh_creds()

    # Build UI - wrapped in scrollable container
    page.controls.clear()
    page.add(
        flet.ListView(
            controls=[
                flet.Column(
                    controls=[
                        # Header
                        flet.Row(
                            controls=[
                                flet.Icon(flet.Icons.CLOUD_UPLOAD, size=32, color="#008069"),
                                flet.Text(
                                    t("deploy.title"),
                                    size=24,
                                    weight=flet.FontWeight.BOLD,
                                    color="#111b21",
                                ),
                            ],
                            alignment=flet.MainAxisAlignment.START,
                        ),
                        flet.Text(t("deploy.subtitle"), color="#667781", size=14),
                        flet.Divider(),

                        # Connection Form
                        flet.Card(
                            content=flet.Container(
                                content=flet.Column(
                                    controls=[
                                        flet.Text(
                                            t("deploy.connection"),
                                            weight=flet.FontWeight.BOLD,
                                            color="#111b21",
                                        ),
                                        flet.Row(
                                            controls=[
                                                host_field,
                                                port_field,
                                            ],
                                        ),
                                        username_field,
                                        password_field,
                                        flet.Text(
                                            t("deploy.or_key"),
                                            color="#667781",
                                            size=12,
                                        ),
                                        key_field,
                                    ],
                                    spacing=12,
                                ),
                                padding=20,
                            ),
                            elevation=1,
                        ),

                        # Server Settings
                        flet.Card(
                            content=flet.Container(
                                content=flet.Column(
                                    controls=[
                                        flet.Text(
                                            t("deploy.server_settings"),
                                            weight=flet.FontWeight.BOLD,
                                            color="#111b21",
                                        ),
                                        flet.Row(
                                            controls=[
                                                server_port_field,
                                                max_file_size_field,
                                            ],
                                        ),
                                        force_reinstall_checkbox,
                                    ],
                                    spacing=12,
                                ),
                                padding=20,
                            ),
                            elevation=1,
                        ),

                        # Action Buttons
                        flet.Row(
                            controls=[
                                connect_btn,
                                deploy_btn,
                                start_btn,
                                stop_btn,
                                progress_ring,
                                status_text,
                                force_reinstall_checkbox,
                            ],
                            alignment=flet.MainAxisAlignment.START,
                            spacing=10,
                        ),

                        # Log Output
                        log_card,

                        # Back Button
                        back_btn,
                    ],
                    spacing=16,
                    horizontal_alignment=flet.CrossAxisAlignment.STRETCH,
                )
            ],
            expand=True,
        )
    )
    page.update()
