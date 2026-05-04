"""Server deployment and management view."""

from __future__ import annotations

import logging
from datetime import datetime

import flet
from deployer import SSHCredentials, ServerManager, DeploymentError
from localization import t
from state import AppState
from storage.credentials import SSHCredentialsStorage

logger = logging.getLogger(__name__)


# ── Color Tokens ──────────────────────────────────────────────────────────────
class _C:
    """Design-system color tokens (light theme)."""
    BG_PAGE       = "#f0f2f5"
    BG_CARD       = "#f8f9fa"
    BG_INPUT      = "#ffffff"
    BG_LOG        = "#f5f6f8"
    BORDER_INPUT  = "#d1d7db"
    BORDER_FOCUS  = "#00a884"
    BORDER_HOVER  = "#b0b5b9"
    TEXT_PRIMARY  = "#111b21"
    TEXT_SECONDARY= "#667781"
    TEXT_MUTED    = "#8696a0"
    ACCENT        = "#00a884"
    ACCENT_HOVER  = "#008f6f"
    ACCENT_LIGHT  = "#d9f5ed"
    DANGER        = "#ea4335"
    DANGER_BG     = "#fce8e6"
    DANGER_HOVER  = "#d33b28"
    WARNING       = "#f9ab00"
    SUCCESS       = "#34a853"
    INFO          = "#4285f4"
    DIVIDER       = "#e9edef"


# ── Reusable Components ───────────────────────────────────────────────────────
def _input(
    label: str,
    *,
    value: str = "",
    hint: str = "",
    password: bool = False,
    multiline: bool = False,
    min_lines: int = 1,
    max_lines: int = 1,
    width: int | None = None,
    prefix_icon: flet.Icons | None = None,
    suffix: flet.Control | None = None,
) -> flet.TextField:
    """Styled text input with consistent theming."""
    return flet.TextField(
        label=label,
        value=value,
        hint_text=hint,
        password=password,
        can_reveal_password=password,
        multiline=multiline,
        min_lines=min_lines,
        max_lines=max_lines,
        width=width,
        prefix_icon=prefix_icon,
        suffix=suffix,
        bgcolor=_C.BG_INPUT,
        border_color=_C.BORDER_INPUT,
        focused_border_color=_C.BORDER_FOCUS,
        border_radius=8,
        color=_C.TEXT_PRIMARY,
        cursor_color=_C.ACCENT,
        label_style=flet.TextStyle(color=_C.TEXT_SECONDARY, size=13),
        hint_style=flet.TextStyle(color=_C.TEXT_MUTED, size=13),
        text_style=flet.TextStyle(color=_C.TEXT_PRIMARY, size=14),
    )


def _card(title: str, icon: flet.Icons, *controls: flet.Control) -> flet.Card:
    """Styled card with header."""
    return flet.Card(
        content=flet.Container(
            content=flet.Column(
                controls=[
                    flet.Row(
                        controls=[
                            flet.Icon(icon, size=18, color=_C.ACCENT),
                            flet.Text(
                                title,
                                size=15,
                                weight=flet.FontWeight.W_600,
                                color=_C.TEXT_PRIMARY,
                            ),
                        ],
                        spacing=8,
                        alignment=flet.MainAxisAlignment.START,
                    ),
                    flet.Divider(color=_C.DIVIDER, height=1),
                    *controls,
                ],
                spacing=14,
            ),
            padding=20,
        ),
        elevation=2,


    )


def _status_badge(text: str, color: str, icon: flet.Icons | None = None) -> flet.Container:
    """Pill-shaped status indicator."""
    row_controls: list[flet.Control] = []
    if icon:
        row_controls.append(flet.Icon(icon, size=14, color=color))
    row_controls.append(flet.Text(text, size=12, weight=flet.FontWeight.W_500, color=color))

    return flet.Container(
        content=flet.Row(controls=row_controls, spacing=6),
        bgcolor=f"{color}15",
        padding=flet.padding.symmetric(horizontal=12, vertical=6),
        border_radius=20,
    )


def _action_btn(
    text: str,
    *,
    icon: flet.Icons | None = None,
    bgcolor: str = _C.ACCENT,
    color: str = "#ffffff",
    visible: bool = True,
    disabled: bool = False,
) -> flet.ElevatedButton:
    """Primary action button."""
    return flet.ElevatedButton(
        text,
        icon=icon,
        bgcolor=bgcolor,
        color=color,
        visible=visible,
        disabled=disabled,
        style=flet.ButtonStyle(
            shape=flet.RoundedRectangleBorder(radius=8),
            padding=flet.padding.symmetric(horizontal=20, vertical=14),
            elevation=0,
            overlay_color=flet.Colors.with_opacity(0.15, "#ffffff"),
        ),
    )


def _ghost_btn(text: str, icon: flet.Icons | None = None) -> flet.TextButton:
    """Low-emphasis button."""
    return flet.TextButton(
        text,
        icon=icon,
        style=flet.ButtonStyle(
            color=_C.TEXT_SECONDARY,
            shape=flet.RoundedRectangleBorder(radius=8),
            padding=flet.padding.symmetric(horizontal=16, vertical=12),
            overlay_color=flet.Colors.with_opacity(0.08, "#ffffff"),
        ),
    )


# ── Main View ─────────────────────────────────────────────────────────────────
def server_deploy_view(page: flet.Page, state: AppState) -> None:
    """View for deploying and managing self-hosted servers."""
    page.bgcolor = _C.BG_PAGE
    page.padding = 0

    # ═══════════════════════════════════════════════════════════════════════════
    #  State
    # ═══════════════════════════════════════════════════════════════════════════
    manager: ServerManager | None = None
    is_connected = False
    is_installed = False
    ssh_storage = SSHCredentialsStorage(state.secure_storage) if state.secure_storage else None

    # ═══════════════════════════════════════════════════════════════════════════
    #  Inputs
    # ═══════════════════════════════════════════════════════════════════════════
    host_field = _input(
        t("deploy.host"),
        hint="192.168.1.100 or vps.example.com",
        prefix_icon=flet.Icons.DNS_OUTLINED,
    )
    port_field = _input(t("deploy.port"), value="22", width=100, prefix_icon=flet.Icons.NUMBERS)
    username_field = _input(t("deploy.username"), value="root", prefix_icon=flet.Icons.PERSON_OUTLINE)
    password_field = _input(
        t("deploy.password"),
        password=True,
        prefix_icon=flet.Icons.LOCK_OUTLINE,
    )
    key_field = _input(
        t("deploy.ssh_key"),
        hint="Paste private key or leave empty to use password",
        multiline=True,
        min_lines=4,
        max_lines=6,
        prefix_icon=flet.Icons.KEY_OUTLINED,
    )

    server_port_field = _input(t("deploy.server_port"), value="8000", width=120, prefix_icon=flet.Icons.SETTINGS_ETHERNET)
    max_file_size_field = _input(f"{t('deploy.max_file_size')} (MB)", value="100", width=160, prefix_icon=flet.Icons.FOLDER_OPEN_OUTLINED)

    force_reinstall_checkbox = flet.Checkbox(
        label="Force reinstall (remove existing)",
        value=False,
        label_style=flet.TextStyle(color=_C.TEXT_SECONDARY, size=13),
        fill_color=_C.ACCENT,
        check_color="#ffffff",
        visible=False,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    #  Status & Log
    # ═══════════════════════════════════════════════════════════════════════════
    status_badge = _status_badge("Idle", _C.TEXT_MUTED)
    progress_ring = flet.ProgressRing(
        width=18,
        height=18,
        stroke_width=2.5,
        color=_C.ACCENT,
        visible=False,
    )

    log_output = flet.ListView(expand=True, spacing=3, auto_scroll=True)
    log_card = flet.Container(
        content=flet.Column(
            controls=[
                flet.Row(
                    controls=[
                        flet.Icon(flet.Icons.TERMINAL, size=14, color=_C.TEXT_MUTED),
                        flet.Text("Deployment Log", size=12, weight=flet.FontWeight.W_500, color=_C.TEXT_MUTED),
                        flet.Container(expand=True),
                        flet.IconButton(
                            icon=flet.Icons.CLEAR_ALL,
                            icon_color=_C.TEXT_MUTED,
                            icon_size=16,
                            tooltip="Clear log",
                            on_click=lambda _: (log_output.controls.clear(), page.update()),
                        ),
                    ],
                    spacing=8,
                ),
                flet.Divider(color=_C.DIVIDER, height=1),
                flet.Container(content=log_output, expand=True, padding=flet.padding.only(top=4)),
            ],
            spacing=8,
        ),
        padding=16,
        height=220,
        bgcolor=_C.BG_LOG,
        border_radius=12,
        border=flet.border.all(1, _C.DIVIDER),
        visible=False,
        animate_opacity=300,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    #  Action Buttons
    # ═══════════════════════════════════════════════════════════════════════════
    connect_btn = _action_btn(
        t("deploy.connect"),
        icon=flet.Icons.LINK,
        bgcolor=_C.ACCENT,
    )
    deploy_btn = _action_btn(
        t("deploy.deploy"),
        icon=flet.Icons.ROCKET_LAUNCH,
        bgcolor=_C.ACCENT,
        visible=False,
    )
    start_btn = _action_btn(
        t("deploy.start"),
        icon=flet.Icons.PLAY_ARROW,
        bgcolor="#2d5a3d",
        color=_C.SUCCESS,
        visible=False,
    )
    stop_btn = _action_btn(
        t("deploy.stop"),
        icon=flet.Icons.STOP,
        bgcolor=_C.DANGER_BG,
        color=_C.DANGER,
        visible=False,
    )
    back_btn = _ghost_btn(t("deploy.back"), flet.Icons.ARROW_BACK)

    # ═══════════════════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════════════════
    def log(message: str, level: str = "info") -> None:
        """Add styled log message."""
        color_map = {
            "info": _C.TEXT_SECONDARY,
            "success": _C.SUCCESS,
            "warning": _C.WARNING,
            "error": _C.DANGER,
            "cmd": _C.INFO,
        }
        timestamp = flet.Text(
            datetime.now().strftime("%H:%M:%S"),
            color=_C.TEXT_MUTED,
            size=11,
            font_family="JetBrains Mono",
            width=60,
        )
        msg = flet.Text(
            message,
            color=color_map.get(level, _C.TEXT_SECONDARY),
            size=12,
            font_family="JetBrains Mono",
            selectable=True,
        )
        log_output.controls.append(
            flet.Row(controls=[timestamp, msg], spacing=8, tight=True)
        )
        page.update()

    def update_status(message: str, state_type: str = "idle") -> None:
        """Update status badge."""
        color_map = {
            "idle": _C.TEXT_MUTED,
            "working": _C.INFO,
            "success": _C.SUCCESS,
            "warning": _C.WARNING,
            "error": _C.DANGER,
        }
        icon_map = {
            "idle": flet.Icons.RADIO_BUTTON_UNCHECKED,
            "working": flet.Icons.SYNC,
            "success": flet.Icons.CHECK_CIRCLE,
            "warning": flet.Icons.WARNING_AMBER,
            "error": flet.Icons.ERROR_OUTLINE,
        }
        controls = status_badge.content.controls
        has_icon = len(controls) > 1
        if has_icon:
            controls[0].icon = icon_map.get(state_type)
            controls[0].color = color_map.get(state_type, _C.TEXT_MUTED)
            text_control = controls[1]
        else:
            text_control = controls[0]
        text_control.value = message
        text_control.color = color_map.get(state_type, _C.TEXT_MUTED)
        status_badge.bgcolor = f"{color_map.get(state_type, _C.TEXT_MUTED)}15"
        page.update()

    def set_buttons(connected: bool = False, installed: bool = False) -> None:
        """Update button states with animation."""
        nonlocal is_connected, is_installed
        is_connected = connected
        is_installed = installed

        connect_btn.visible = not connected
        deploy_btn.visible = connected and not installed
        start_btn.visible = connected and installed
        stop_btn.visible = connected and installed
        force_reinstall_checkbox.visible = connected

        # Animate visibility changes
        for btn in (connect_btn, deploy_btn, start_btn, stop_btn):
            btn.animate_opacity = 200
        page.update()

    def load_saved_ssh_creds() -> None:
        if not ssh_storage:
            return
        saved = ssh_storage.get_ssh_credentials()
        if saved:
            host_field.value = saved.host
            port_field.value = str(saved.port)
            username_field.value = saved.username
            page.update()

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

    # ═══════════════════════════════════════════════════════════════════════════
    #  Actions
    # ═══════════════════════════════════════════════════════════════════════════
    async def do_connect(e: flet.ControlEvent | None = None) -> None:
        nonlocal manager
        logger.info("[do_connect] Starting connection...")

        progress_ring.visible = True
        connect_btn.disabled = True
        update_status("Connecting...", "working")
        log_card.visible = True
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
            save_ssh_creds()
            logger.info("[do_connect] Credentials saved, checking status...")

            status = manager.check_server_status()
            logger.info(f"[do_connect] Server status: {status}")

            if status["installed"]:
                port = status.get("port", "?")
                update_status(f"Installed · Port {port}", "success")
                log(f"Server detected on port {port}", "success")
                set_buttons(connected=True, installed=True)
            else:
                update_status("Not installed", "warning")
                log("Server not detected on remote host", "warning")
                set_buttons(connected=True, installed=False)

        except DeploymentError as ex:
            update_status(str(ex), "error")
            log(str(ex), "error")
            set_buttons(connected=False)
        except Exception as ex:
            update_status(f"{t('deploy.error')}: {ex}", "error")
            log(f"ERROR: {ex}", "error")
            set_buttons(connected=False)
        finally:
            progress_ring.visible = False
            connect_btn.disabled = False
            page.update()

    async def do_deploy(e: flet.ControlEvent | None = None) -> None:
        logger.info("[do_deploy] Button clicked, starting deployment...")

        if not manager:
            logger.error("[do_deploy] No manager available")
            update_status("Not connected", "error")
            return

        progress_ring.visible = True
        deploy_btn.disabled = True
        update_status("Deploying...", "working")
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

            success = manager.deploy_from_assets(
                port=int(server_port_field.value or 8000),
                config=config,
                progress_callback=lambda m: log(m, "cmd"),
                force_reinstall=force_reinstall_checkbox.value,
            )

            if success:
                update_status("Deployment successful", "success")
                log("Deployment completed successfully", "success")
                set_buttons(connected=True, installed=True)
            else:
                update_status("Deployment failed", "error")
                log("Deployment returned failure status", "error")

        except DeploymentError as ex:
            log(f"ERROR: {ex}", "error")
            update_status(str(ex), "error")
        except Exception as ex:
            log(f"ERROR: {ex}", "error")
            update_status(f"{t('deploy.error')}: {ex}", "error")
        finally:
            progress_ring.visible = False
            deploy_btn.disabled = False
            page.update()

    async def do_start(e: flet.ControlEvent) -> None:
        if not manager:
            return
        progress_ring.visible = True
        update_status("Starting...", "working")
        page.update()
        try:
            if manager.start_server():
                update_status("Running", "success")
                log("Server started successfully", "success")
            else:
                update_status("Start failed", "error")
                log("Failed to start server", "error")
        except Exception as ex:
            update_status(str(ex), "error")
            log(f"ERROR: {ex}", "error")
        finally:
            progress_ring.visible = False
            page.update()

    async def do_stop(e: flet.ControlEvent) -> None:
        if not manager:
            return
        progress_ring.visible = True
        update_status("Stopping...", "working")
        page.update()
        try:
            if manager.stop_server():
                update_status("Stopped", "warning")
                log("Server stopped", "warning")
            else:
                update_status("Stop failed", "error")
                log("Failed to stop server", "error")
        except Exception as ex:
            update_status(str(ex), "error")
            log(f"ERROR: {ex}", "error")
        finally:
            progress_ring.visible = False
            page.update()

    def _go_back() -> None:
        if manager:
            try:
                manager.disconnect()
            except Exception:
                pass
        from views.login_view import login_view
        login_view(page, state)

    # Wire events
    connect_btn.on_click = do_connect
    deploy_btn.on_click = do_deploy
    start_btn.on_click = do_start
    stop_btn.on_click = do_stop
    back_btn.on_click = lambda _: _go_back()

    load_saved_ssh_creds()

    # ═══════════════════════════════════════════════════════════════════════════
    #  Layout
    # ═══════════════════════════════════════════════════════════════════════════
    page.controls.clear()
    page.add(
        flet.Container(
            content=flet.Row(
                controls=[
                    # ── Sidebar ──────────────────────────────────────────────
                    flet.Container(
                        content=flet.Column(
                            controls=[
                                flet.Row(
                                    controls=[
                                        flet.Icon(flet.Icons.CLOUD_UPLOAD, size=28, color=_C.ACCENT),
                                        flet.Text(
                                            t("deploy.title"),
                                            size=20,
                                            weight=flet.FontWeight.W_700,
                                            color=_C.TEXT_PRIMARY,
                                        ),
                                    ],
                                    spacing=10,
                                ),
                                flet.Text(
                                    t("deploy.subtitle"),
                                    color=_C.TEXT_MUTED,
                                    size=13,
                                ),
                                flet.Divider(color=_C.DIVIDER, height=24),

                                # Status panel
                                flet.Text("STATUS", size=10, weight=flet.FontWeight.W_700, color=_C.TEXT_MUTED),
                                status_badge,
                                flet.Divider(color=_C.DIVIDER, height=24),

                                # Quick actions
                                flet.Text("ACTIONS", size=10, weight=flet.FontWeight.W_700, color=_C.TEXT_MUTED),
                                flet.Column(
                                    controls=[
                                        connect_btn,
                                        deploy_btn,
                                        start_btn,
                                        stop_btn,
                                    ],
                                    spacing=8,
                                ),
                                flet.Container(expand=True),
                                back_btn,
                            ],
                            spacing=12,
                            horizontal_alignment=flet.CrossAxisAlignment.START,
                        ),
                        width=260,
                        padding=24,
                        bgcolor=_C.BG_CARD,
                        border_radius=flet.border_radius.only(16),
                    ),

                    # ── Main Content ─────────────────────────────────────────
                    flet.Container(
                        content=flet.Column(
                            controls=[
                                # Top bar
                                flet.Row(
                                    controls=[
                                        flet.Text(
                                            "Server Configuration",
                                            size=18,
                                            weight=flet.FontWeight.W_600,
                                            color=_C.TEXT_PRIMARY,
                                        ),
                                        flet.Container(expand=True),
                                        flet.Row(
                                            controls=[
                                                progress_ring,
                                                force_reinstall_checkbox,
                                            ],
                                            spacing=12,
                                            alignment=flet.MainAxisAlignment.END,
                                        ),
                                    ],
                                    alignment=flet.MainAxisAlignment.SPACE_BETWEEN,
                                ),

                                flet.Divider(color=_C.DIVIDER, height=1),

                                # Scrollable content
                                flet.ListView(
                                    controls=[
                                        flet.Column(
                                            controls=[
                                                # Connection Card
                                                _card(
                                                    t("deploy.connection"),
                                                    flet.Icons.LINK,
                                                    flet.Row(
                                                        controls=[
                                                            flet.Container(content=host_field, expand=True),
                                                            port_field,
                                                        ],
                                                        spacing=12,
                                                    ),
                                                    username_field,
                                                    password_field,
                                                    flet.Row(
                                                        controls=[
                                                            flet.Icon(flet.Icons.HORIZONTAL_RULE, size=16, color=_C.TEXT_MUTED),
                                                            flet.Text("OR", size=11, color=_C.TEXT_MUTED, weight=flet.FontWeight.W_500),
                                                            flet.Icon(flet.Icons.HORIZONTAL_RULE, size=16, color=_C.TEXT_MUTED),
                                                        ],
                                                        spacing=8,
                                                        alignment=flet.MainAxisAlignment.CENTER,
                                                    ),
                                                    key_field,
                                                ),

                                                # Server Settings Card
                                                _card(
                                                    t("deploy.server_settings"),
                                                    flet.Icons.SETTINGS_SUGGEST_OUTLINED,
                                                    flet.Row(
                                                        controls=[
                                                            server_port_field,
                                                            max_file_size_field,
                                                        ],
                                                        spacing=12,
                                                    ),
                                                ),

                                                # Log Output
                                                log_card,
                                            ],
                                            spacing=16,
                                            horizontal_alignment=flet.CrossAxisAlignment.STRETCH,
                                        ),
                                    ],
                                    expand=True,
                                    spacing=0,
                                ),
                            ],
                            spacing=16,
                            expand=True,
                        ),
                        expand=True,
                        padding=24,
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )
    )
    page.update()
