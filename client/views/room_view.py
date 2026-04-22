from __future__ import annotations

import flet

from client.api.http_client import APIClient, AuthError
from client.api.ws_client import WsClient
from client.config import API_URL
from client.locale import t
from client.state import AppState


def room_view(page: flet.Page, state: AppState) -> None:
    room = state.active_room
    if room is None:
        return

    page.bgcolor = "#efeae2"

    messages_list = flet.ListView(
        expand=True,
        spacing=6,
        auto_scroll=False,
    )

    message_input = flet.TextField(
        label=t("room.message_hint"),
        expand=True,
        multiline=True,
        on_submit=lambda e: page.run_task(_send_message),
        bgcolor="#ffffff",
        filled=True,
        border_color=flet.Colors.TRANSPARENT,
        color=flet.Colors.BLACK
    )

    reconnecting_banner = flet.Container(
        content=flet.Text(
            t("room.reconnecting"),
            color="#ffffff",
            size=13,
            weight=flet.FontWeight.W_500,
        ),
        bgcolor="#f57c00",
        padding=flet.padding.symmetric(horizontal=12, vertical=6),
        visible=False,
        border_radius=4,
        alignment=flet.alignment.Alignment(0, 0),
    )

    _state: dict = {"min_id": None, "loading_older": False, "ws_client": None, "user_at_bottom": True, "messages_data": []}

    # User profile bottom sheet
    _profile_sheet_content = flet.Column(tight=True, spacing=8, width=320)
    _profile_sheet = flet.BottomSheet(
        content=flet.Container(
            content=_profile_sheet_content,
            padding=flet.padding.all(20),
        ),
        open=False,
    )
    page.overlay.append(_profile_sheet)

    async def _show_user_profile(username: str) -> None:
        _profile_sheet_content.controls.clear()
        _profile_sheet_content.controls.append(
            flet.Text(t("room.loading"), size=14, color="#667781")
        )
        _profile_sheet.open = True
        page.update()

        client = APIClient(base_url=API_URL, state=state)
        try:
            data = await client.get_user(username)
            dn = data.get("display_name") or ""
            _profile_sheet_content.controls.clear()
            _profile_sheet_content.controls += [
                flet.Row(
                    controls=[
                        flet.Icon(
                            flet.Icons.ACCOUNT_CIRCLE, size=48, color="#008069"
                        ),
                        flet.Column(
                            controls=[
                                flet.Text(
                                    data.get("username", ""),
                                    size=18,
                                    weight=flet.FontWeight.BOLD,
                                    color="#111b21",
                                ),
                                flet.Text(
                                    dn, size=14, color="#667781"
                                )
                                if dn
                                else flet.Text(
                                    t("room.no_display_name"),
                                    size=14,
                                    color="#667781",
                                    italic=True,
                                ),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=flet.CrossAxisAlignment.CENTER,
                ),
                flet.Divider(height=8),
                flet.Row(
                    controls=[
                        flet.Icon(flet.Icons.BADGE, size=18, color="#667781"),
                        flet.Text(
                            t("room.username_label", username=data.get('username', '')),
                            size=14,
                            color="#111b21",
                        ),
                    ],
                    spacing=8,
                ),
                flet.Row(
                    controls=[
                        flet.Icon(flet.Icons.LABEL, size=18, color="#667781"),
                        flet.Text(
                            t("room.display_name_label", name=dn or "—"), size=14, color="#111b21"
                        ),
                    ],
                    spacing=8,
                ),
                flet.TextButton(
                    t("room.close"),
                    on_click=lambda e: _close_profile_sheet(),
                    style=flet.ButtonStyle(color="#008069"),
                ),
            ]
            page.update()
        except Exception as exc:
            _profile_sheet_content.controls.clear()
            _profile_sheet_content.controls.append(
                flet.Text(str(exc), color="#ea4335")
            )
            page.update()
        finally:
            await client.aclose()

    def _close_profile_sheet() -> None:
        _profile_sheet.open = False
        page.update()

    def _build_message_tile(msg: dict) -> flet.Control:
        author = msg.get("author_username", "?")
        display_name = msg.get("author_display_name") or author
        body = msg.get("body", "")
        ts_raw = msg.get("created_at", "")
        ts = ts_raw
        if isinstance(ts_raw, str) and "T" in ts_raw:
            ts = ts_raw.split("T")[1][:5]

        is_me = (
            state.current_user is not None
            and author == state.current_user.username
        )

        alignment = state.message_alignment
        if alignment == "right":
            on_right = True
        elif alignment == "left":
            on_right = False
        else:
            on_right = is_me  # default: mine on right, others on left

        bubble_color = "#d9fdd3" if is_me else "#ffffff"
        name_color = "#008069"

        bubble = flet.Container(
            content=flet.Column(
                controls=[
                    flet.TextButton(
                        display_name,
                        on_click=lambda e, u=author: page.run_task(
                            _show_user_profile, u
                        ),
                        style=flet.ButtonStyle(
                            color=name_color,
                            padding=flet.padding.all(0),
                        ),
                    )
                    if not is_me
                    else flet.Container(),
                    flet.Text(
                        body,
                        size=14,
                        color="#111b21",
                        selectable=True,
                    ),
                    flet.Row(
                        controls=[
                            flet.Text(ts, size=10, color="#667781"),
                        ],
                        alignment=flet.MainAxisAlignment.END,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor=bubble_color,
            border_radius=flet.border_radius.only(
                top_left=12,
                top_right=12,
                bottom_left=4 if on_right else 12,
                bottom_right=12 if on_right else 4,
            ),
            padding=flet.padding.symmetric(horizontal=12, vertical=6),
            border=flet.Border.all(1, "#e0e0e0") if not on_right else None,
            animate_scale=flet.Animation(200, flet.AnimationCurve.EASE_OUT),
            animate_opacity=flet.Animation(200, flet.AnimationCurve.EASE_OUT),
        )

        msg_id = msg.get("id")
        spacer = flet.Container(expand=True)

        if on_right:
            return flet.Row(
                key=str(msg_id) if msg_id else None,
                controls=[spacer, bubble],
                vertical_alignment=flet.CrossAxisAlignment.START,
            )
        else:
            return flet.Row(
                key=str(msg_id) if msg_id else None,
                controls=[bubble, spacer],
                vertical_alignment=flet.CrossAxisAlignment.START,
            )

    def _animate_message(message_control: flet.Row) -> None:
        """Animate a newly added message bubble."""
        bubble = message_control.controls[0] if message_control.controls else None
        if bubble is None:
            return
        # Set initial state (bubble is the first control — either spacer or container)
        # Find the Container (bubble) — it's always the non-spacer control
        container = next(
            (c for c in message_control.controls if isinstance(c, flet.Container) and c.content is not None),
            None,
        )
        if container is None:
            return
        container.scale = 0.85
        container.opacity = 0.0
        page.update()
        container.scale = 1.0
        container.opacity = 1.0
        page.update()

    async def _smooth_scroll_to_bottom() -> None:
        """Smoothly scroll to the bottom of the chat area."""
        print(f"[SCROLL] Starting smooth scroll to bottom...")
        # Small delay to ensure UI is rendered
        import asyncio
        await asyncio.sleep(0.1)
        await messages_list.scroll_to(
            offset=-1,
            duration=400,
            curve=flet.AnimationCurve.EASE_OUT,
        )
        print(f"[SCROLL] Smooth scroll completed")

    def _is_user_at_bottom() -> bool:
        """Check if user is scrolled near the bottom of the chat."""
        # We track this via on_scroll event
        return _state.get("user_at_bottom", True)

    def _on_ws_message(payload: dict) -> None:
        print(f"[WS] Received message payload: {payload}")
        if payload.get("type") == "message":
            msg = payload.get("payload", payload)
            print(f"[WS] Processing message: {msg.get('id', 'no-id')} from {msg.get('author_username', 'unknown')}")
            
            user_at_bottom = _is_user_at_bottom()
            print(f"[WS] User at bottom: {user_at_bottom}")

            _state["messages_data"].append(msg)
            message_control = _build_message_tile(msg)
            messages_list.controls.append(message_control)
            print(f"[WS] Added message to list, total messages: {len(messages_list.controls)}")
            
            reconnecting_banner.visible = False
            _animate_message(message_control)
            print(f"[WS] Animated message")
            
            page.update()
            print(f"[WS] Updated page")
            
            # Only scroll to bottom if user was already at bottom
            if user_at_bottom:
                print(f"[WS] Scrolling to bottom...")
                page.run_task(_smooth_scroll_to_bottom)
            else:
                print(f"[WS] Not scrolling - user not at bottom")

    def _on_reconnecting(delay: float) -> None:
        reconnecting_banner.visible = True
        page.update()

    async def _load_messages(before_id: int | None = None) -> list[dict]:
        client = APIClient(base_url=API_URL, state=state)
        try:
            return await client.get_messages(
                room.id, before_id=before_id, limit=50
            )
        except AuthError:
            state.token = None
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room.session_expired"), color="#ffffff"), open=True, bgcolor="#ea4335"
            )
            page.update()
            from client.views.login_view import login_view

            login_view(page, state)
            return []
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()
            return []
        finally:
            await client.aclose()

    async def _initial_load() -> None:
        print(f"[INIT] Starting initial message load...")

        # Auto-join public rooms if not already a member
        if room.room_type == "public":
            client = APIClient(base_url=API_URL, state=state)
            try:
                updated = await client.join_room(room.id)
                # Sync member count in case it changed
                room.member_count = updated.get("member_count", room.member_count)
            except Exception as exc:
                print(f"[INIT] Auto-join failed: {exc}")
            finally:
                await client.aclose()

        msgs = await _load_messages()
        msgs_sorted = sorted(msgs, key=lambda m: m["id"])
        print(f"[INIT] Loaded {len(msgs_sorted)} messages")
        
        if msgs_sorted:
            _state["min_id"] = msgs_sorted[0]["id"]
            _state["messages_data"] = msgs_sorted
            for m in msgs_sorted:
                messages_list.controls.append(_build_message_tile(m))
            print(f"[INIT] Added {len(msgs_sorted)} messages to UI")
        
        page.update()
        print(f"[INIT] Updated page, now scrolling to bottom...")
        
        # Ensure user is marked as at bottom for initial load
        _state["user_at_bottom"] = True
        await _smooth_scroll_to_bottom()
        print(f"[INIT] Initial load complete")

    async def _load_older() -> None:
        if _state["loading_older"] or _state["min_id"] is None:
            return
        _state["loading_older"] = True
        msgs = await _load_messages(before_id=_state["min_id"])
        if msgs:
            msgs_sorted = sorted(msgs, key=lambda m: m["id"])
            _state["min_id"] = msgs_sorted[0]["id"]
            new_tiles = [_build_message_tile(m) for m in msgs_sorted]
            # Insert older messages at the top (data too)
            _state["messages_data"] = msgs_sorted + _state["messages_data"]
            messages_list.controls = new_tiles + messages_list.controls
            page.update()
            # Scroll to the first of the previously visible messages to keep reading position
            if new_tiles:
                await messages_list.scroll_to(
                    scroll_key=new_tiles[-1],
                    duration=0,
                )
        _state["loading_older"] = False

    async def _send_message() -> None:
        body = (message_input.value or "").strip()
        print(f"[SEND] Attempting to send message: '{body}'")
        if not body:
            print(f"[SEND] Empty message, aborting")
            return
        ws: WsClient | None = _state.get("ws_client")
        if ws is None:
            print(f"[SEND] No WebSocket client available")
            return
        try:
            # Mark user as "at bottom" when sending a message
            print(f"[SEND] Setting user_at_bottom = True")
            _state["user_at_bottom"] = True
            
            print(f"[SEND] Sending message via WebSocket...")
            await ws.send_message(room.id, body)
            
            message_input.value = ""
            print(f"[SEND] Cleared input field")
            page.update()
            print(f"[SEND] Updated page")
        except Exception as exc:
            print(f"[SEND] Error sending message: {exc}")
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()

    def _on_scroll(e: flet.OnScrollEvent) -> None:
        # Track if user is at bottom (within 100px threshold)
        if e.pixels is not None and e.max_scroll_extent is not None:
            distance_from_bottom = e.max_scroll_extent - e.pixels
            was_at_bottom = _state.get("user_at_bottom", True)
            is_at_bottom = distance_from_bottom < 100
            
            if was_at_bottom != is_at_bottom:
                print(f"[SCROLL] User position changed: at_bottom={is_at_bottom} (distance={distance_from_bottom:.1f}px)")
            
            _state["user_at_bottom"] = is_at_bottom
            
            # Load older messages when scrolled to top
            if e.pixels <= 50:
                print(f"[SCROLL] Near top (pixels={e.pixels}), loading older messages...")
                page.run_task(_load_older)

    messages_list.on_scroll = _on_scroll

    def _rebuild_messages(_alignment: str) -> None:
        """Rebuild all message tiles when alignment setting changes."""
        messages_list.controls.clear()
        for m in _state.get("messages_data", []):
            messages_list.controls.append(_build_message_tile(m))
        page.update()

    state.on_alignment_change = _rebuild_messages

    async def _start_ws() -> None:
        # Close any existing room WebSocket before opening a new one
        state.close_room_ws()

        ws = WsClient(
            token=state.token or "",
            room_id=room.id,
            on_message=_on_ws_message,
            on_reconnecting=_on_reconnecting,
        )
        _state["ws_client"] = ws
        state.room_ws = ws
        await ws.connect()

    def _go_back(e: flet.ControlEvent) -> None:
        state.close_room_ws()
        state.on_alignment_change = None
        _state["ws_client"] = None
        state.active_room = None
        from client.views.chat_list_view import chat_list_view

        chat_list_view(page, state)

    def _go_settings(e: flet.ControlEvent) -> None:
        from client.views.room_settings_view import room_settings_view

        room_settings_view(page, state)

    # Диалог приглашения (только для групп)
    invite_username_field = flet.TextField(
        label=t("room.invite_username"), autofocus=True
    )
    invite_error = flet.Text("", color="#ea4335", visible=False, size=12)

    async def _do_invite(e: flet.ControlEvent) -> None:
        invite_error.visible = False
        page.update()
        username = (invite_username_field.value or "").strip()
        if not username:
            return
        client = APIClient(base_url=API_URL, state=state)
        try:
            await client.invite_user(room.id, username)
            invite_dialog.open = False
            invite_username_field.value = ""
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room.invite_success", username=username), color="#ffffff"), 
                open=True, 
                bgcolor="#008069"
            )
            page.update()
        except Exception as exc:
            invite_error.value = str(exc)
            invite_error.visible = True
            page.update()
        finally:
            await client.aclose()

    invite_dialog = flet.AlertDialog(
        title=flet.Text(t("room.invite_user"), weight=flet.FontWeight.BOLD, color="#111b21"),
        content=flet.Column(controls=[invite_username_field, invite_error], tight=True, spacing=8),
        actions=[
            flet.TextButton(t("room.cancel"), on_click=lambda e: _close_invite_dialog(), style=flet.ButtonStyle(color="#008069")),
            flet.ElevatedButton(t("room.invite"), on_click=_do_invite, style=flet.ButtonStyle(bgcolor="#008069", color="#ffffff")),
        ],
    )

    def _close_invite_dialog() -> None:
        invite_dialog.open = False
        page.update()

    def _open_invite_dialog(e: flet.ControlEvent) -> None:
        invite_username_field.value = ""
        invite_error.visible = False
        invite_dialog.open = True
        page.update()

    page.overlay.append(invite_dialog)

    is_owner = (
        state.current_user is not None
        and room.owner_username == state.current_user.username
    )
    is_personal = room.room_type == "personal"
    can_invite = (is_owner or room.allow_member_invite) and not is_personal

    # Получить отображаемое имя чата
    def _get_display_name() -> str:
        if is_personal:
            # Для личных чатов показываем имя собеседника
            name = room.name
            if state.current_user and state.current_user.username in name:
                parts = name.split(", ")
                return next((p for p in parts if p != state.current_user.username), name)
            return name
        return room.name

    display_name = _get_display_name()
    
    # Подзаголовок в зависимости от типа чата
    def _get_subtitle() -> str:
        if is_personal:
            return t("room.personal_chat")
        elif room.room_type == "group":
            return t("room.group_subtitle", count=room.member_count)
        else:
            return t("room.public_subtitle", count=room.member_count)

    subtitle = _get_subtitle()

    top_bar_controls: list[flet.Control] = [
        flet.IconButton(
            icon=flet.Icons.ARROW_BACK,
            on_click=_go_back,
            tooltip=t("room.back"),
            icon_color="#ffffff",
        ),
        flet.Column(
            controls=[
                flet.Text(
                    display_name,
                    size=18,
                    weight=flet.FontWeight.BOLD,
                    color="#ffffff",
                ),
                flet.Text(
                    subtitle,
                    size=13,
                    color="#d1d7db",
                ),
            ],
            spacing=0,
            tight=True,
            expand=True,
        ),
    ]
    if can_invite:
        top_bar_controls.append(
            flet.IconButton(
                icon=flet.Icons.PERSON_ADD,
                on_click=_open_invite_dialog,
                tooltip=t("room.invite_user"),
                icon_color="#ffffff",
            )
        )
    if is_owner:
        top_bar_controls.append(
            flet.IconButton(
                icon=flet.Icons.SETTINGS,
                on_click=_go_settings,
                tooltip=t("room.room_settings"),
                icon_color="#ffffff",
            )
        )

    top_bar = flet.Container(
        content=flet.Row(
            controls=top_bar_controls,
            vertical_alignment=flet.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#008069",
        padding=flet.padding.symmetric(horizontal=8, vertical=8),
    )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                top_bar,
                reconnecting_banner,
                flet.Container(
                    content=messages_list,
                    bgcolor="#efeae2",
                    expand=True,
                    padding=flet.padding.symmetric(horizontal=8, vertical=8),
                ),
                flet.Container(
                    content=flet.Row(
                        controls=[
                            message_input,
                            flet.IconButton(
                                icon=flet.Icons.SEND,
                                on_click=lambda e: page.run_task(_send_message),
                                icon_color="#008069",
                                tooltip=t("room.send"),
                                icon_size=24,
                            ),
                        ],
                        vertical_alignment=flet.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#f0f2f5",
                    padding=flet.padding.symmetric(horizontal=12, vertical=8),
                ),
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()
    page.run_task(_initial_load)
    page.run_task(_start_ws)