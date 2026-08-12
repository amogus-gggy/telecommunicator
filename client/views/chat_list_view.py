from __future__ import annotations

import asyncio

import flet

from api.http_client import APIClient
from api.ws_client import UnifiedWsClient
from cache.cache_manager import CacheManager
from localization import t
from state import AppState, RoomDTO
from ui.theme import initials_avatar, primary_button, snack, themed_field


def chat_list_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = flet.Colors.SURFACE_CONTAINER
    page.overlay.clear()

    cache_manager = CacheManager(refresh_interval=10, max_age=300)

    personal_chats: list[dict] = []
    group_chats: list[dict] = []
    public_rooms: list[dict] = []

    # Cache of built tiles keyed by room id — avoids recreating widgets on every filter
    _tile_cache: dict[int, flet.Control] = {}

    personal_column = flet.Column(scroll=flet.ScrollMode.AUTO, expand=True, spacing=8)
    group_column = flet.Column(scroll=flet.ScrollMode.AUTO, expand=True, spacing=8)
    public_column = flet.Column(scroll=flet.ScrollMode.AUTO, expand=True, spacing=8)

    # Debounce state for search
    _search_task: asyncio.Task | None = None

    async def _debounced_filter(query: str) -> None:
        await asyncio.sleep(0.3)
        _filter_chats(query)

    def _on_search_change(e: flet.ControlEvent) -> None:
        nonlocal _search_task
        if _search_task and not _search_task.done():
            _search_task.cancel()
        _search_task = page.run_task(_debounced_filter, e.control.value)

    search_field = themed_field(
        hint_text=t("chat_list.search"),
        prefix_icon=flet.Icons.SEARCH,
        expand=True,
        on_change=_on_search_change,
        border_radius=20,
        bgcolor=flet.Colors.SURFACE_CONTAINER_HIGH,
    )

    tabs = flet.Tabs(
        selected_index=0,
        length=3,
        expand=True,
        content=flet.Column(
            expand=True,
            controls=[
                flet.TabBar(
                    tabs=[
                        flet.Tab(
                            label=flet.Text(t("chat_list.tab_personal")),
                            icon=flet.Icons.PERSON,
                        ),
                        flet.Tab(
                            label=flet.Text(t("chat_list.tab_groups")),
                            icon=flet.Icons.GROUP,
                        ),
                        flet.Tab(
                            label=flet.Text(t("chat_list.tab_public")),
                            icon=flet.Icons.PUBLIC,
                        ),
                    ]
                ),
                flet.TabBarView(
                    expand=True,
                    controls=[personal_column, group_column, public_column],
                ),
            ],
        ),
    )

    # --- Диалог личного чата ---
    username_field = themed_field(
        label=t("chat_list.username_field"), autofocus=True
    )
    personal_error = flet.Text("", color=flet.Colors.ERROR, visible=False, size=12)

    async def _create_personal_chat(e: flet.ControlEvent) -> None:
        personal_error.visible = False
        page.update()
        client = APIClient(state=state)
        try:
            room_data = await client.create_personal_chat(username_field.value or "")
            state.active_room = RoomDTO(
                **{k: room_data.get(k) for k in RoomDTO.__dataclass_fields__}
            )
            personal_dialog.open = False
            page.update()
            _stop_refresh()
            from views.room_view import room_view

            room_view(page, state)
        except Exception as exc:
            personal_error.value = str(exc)
            personal_error.visible = True
            page.update()
        finally:
            await client.aclose()

    personal_dialog = flet.AlertDialog(
        title=flet.Text(
            t("chat_list.new_personal_chat"),
            weight=flet.FontWeight.BOLD,
            color=flet.Colors.ON_SURFACE,
        ),
        content=flet.Column(
            controls=[username_field, personal_error], tight=True, spacing=8
        ),
        actions=[
            flet.TextButton(
                t("chat_list.cancel"),
                on_click=lambda e: _close_personal_dialog(),
                style=flet.ButtonStyle(color=flet.Colors.PRIMARY),
            ),
            primary_button(t("chat_list.create"), on_click=_create_personal_chat),
        ],
        bgcolor=flet.Colors.SURFACE,
    )

    # --- Диалог группового чата ---
    group_name_field = themed_field(
        label=t("chat_list.group_name_field"), autofocus=True
    )
    public_toggle = flet.Switch(
        label=t("chat_list.public_group"),
        value=False,
        active_color=flet.Colors.PRIMARY,
        label_text_style=flet.TextStyle(color=flet.Colors.ON_SURFACE, size=14),
    )
    group_error = flet.Text("", color=flet.Colors.ERROR, visible=False, size=12)

    async def _create_group_chat(e: flet.ControlEvent) -> None:
        group_error.visible = False
        page.update()
        client = APIClient(state=state)
        try:
            room_type = "public" if public_toggle.value else "group"
            room_data = await client.create_room(
                name=group_name_field.value or "",
                room_type=room_type,
                is_private=not public_toggle.value,
            )
            state.active_room = RoomDTO(
                **{k: room_data.get(k) for k in RoomDTO.__dataclass_fields__}
            )
            group_dialog.open = False
            page.update()
            _stop_refresh()
            from views.room_view import room_view

            room_view(page, state)
        except Exception as exc:
            group_error.value = str(exc)
            group_error.visible = True
            page.update()
        finally:
            await client.aclose()

    group_dialog = flet.AlertDialog(
        title=flet.Text(
            t("chat_list.new_group_chat"),
            weight=flet.FontWeight.BOLD,
            color=flet.Colors.ON_SURFACE,
        ),
        content=flet.Column(
            controls=[group_name_field, public_toggle, group_error],
            tight=True,
            spacing=8,
        ),
        actions=[
            flet.TextButton(
                t("chat_list.cancel"),
                on_click=lambda e: _close_group_dialog(),
                style=flet.ButtonStyle(color=flet.Colors.PRIMARY),
            ),
            primary_button(t("chat_list.create"), on_click=_create_group_chat),
        ],
        bgcolor=flet.Colors.SURFACE,
    )

    def _close_personal_dialog() -> None:
        personal_dialog.open = False
        page.update()

    def _close_group_dialog() -> None:
        group_dialog.open = False
        page.update()

    def _open_personal_dialog(e: flet.ControlEvent) -> None:
        username_field.value = ""
        personal_error.visible = False
        personal_dialog.open = True
        page.update()

    def _open_group_dialog(e: flet.ControlEvent) -> None:
        group_name_field.value = ""
        public_toggle.value = False
        group_error.visible = False
        group_dialog.open = True
        page.update()

    page.overlay.extend([personal_dialog, group_dialog])

    # --- Кнопки создания ---
    create_buttons = flet.Row(alignment=flet.MainAxisAlignment.CENTER, controls=[])

    def _update_create_buttons() -> None:
        create_buttons.controls.clear()
        if tabs.selected_index == 0:
            create_buttons.controls.append(
                flet.ElevatedButton(
                    t("chat_list.new_chat"),
                    icon=flet.Icons.PERSON_ADD,
                    on_click=_open_personal_dialog,
                    style=flet.ButtonStyle(
                        bgcolor=flet.Colors.PRIMARY,
                        color=flet.Colors.ON_PRIMARY,
                        shape=flet.RoundedRectangleBorder(radius=20),
                        padding=flet.padding.symmetric(
                            vertical=12, horizontal=16
                        ),
                    ),
                )
            )
        elif tabs.selected_index == 1:
            create_buttons.controls.append(
                flet.ElevatedButton(
                    t("chat_list.new_group"),
                    icon=flet.Icons.GROUP_ADD,
                    on_click=_open_group_dialog,
                    style=flet.ButtonStyle(
                        bgcolor=flet.Colors.PRIMARY,
                        color=flet.Colors.ON_PRIMARY,
                        shape=flet.RoundedRectangleBorder(radius=20),
                        padding=flet.padding.symmetric(
                            vertical=12, horizontal=16
                        ),
                    ),
                )
            )
        page.update()

    def _on_tab_change(e: flet.ControlEvent) -> None:
        _update_create_buttons()

    tabs.on_change = _on_tab_change

    # --- Отображение чатов ---
    def _get_chat_display_name(room: dict) -> str:
        if room.get("room_type") == "personal":
            my_username = state.current_user.username if state.current_user else ""
            # Prefer full member handles so remote users show as "user@server"
            counterpart = next(
                (
                    p
                    for p in room.get("participants") or []
                    if p.split("@", 1)[0] != my_username
                ),
                None,
            )
            if counterpart:
                return counterpart
            name = room.get("name", "")
            if my_username and my_username in name:
                parts = name.split(", ")
                return next((p for p in parts if p != my_username), name)
            return name
        return room.get("name", "")

    def _build_chat_tile(room: dict) -> flet.Control:
        room_id: int = room["id"]
        # Return cached tile if data hasn't changed
        if room_id in _tile_cache:
            return _tile_cache[room_id]

        display_name = _get_chat_display_name(room)
        room_type = room.get("room_type", "public")

        if room_type == "personal":
            icon = flet.Icons.PERSON
        elif room_type == "group":
            icon = flet.Icons.GROUP
        else:
            icon = flet.Icons.PUBLIC

        async def on_open(e: flet.ControlEvent, r: dict = room) -> None:
            state.active_room = RoomDTO(
                **{k: r[k] for k in RoomDTO.__dataclass_fields__}
            )
            _stop_refresh()
            from views.room_view import room_view

            room_view(page, state)

        def on_hover(e: flet.ControlEvent) -> None:
            e.control.bgcolor = (
                flet.Colors.SURFACE_CONTAINER_HIGH
                if e.data == "true"
                else flet.Colors.TRANSPARENT
            )
            e.control.update()

        subtitle_parts = []
        if room_type != "personal":
            subtitle_parts.append(
                t("chat_list.members_count", count=room["member_count"])
            )
        if room.get("is_private"):
            subtitle_parts.append(t("chat_list.private"))

        subtitle = " • ".join(subtitle_parts) if subtitle_parts else t("chat_list.chat")

        tile = flet.Container(
            content=flet.Row(
                controls=[
                    flet.Stack(
                        controls=[
                            initials_avatar(display_name, size=44),
                            flet.Container(
                                content=flet.Icon(
                                    icon, size=12, color=flet.Colors.ON_PRIMARY
                                ),
                                bgcolor=flet.Colors.PRIMARY,
                                border_radius=10,
                                padding=2,
                                right=0,
                                bottom=0,
                            ),
                        ],
                        width=44,
                        height=44,
                    ),
                    flet.Column(
                        controls=[
                            flet.Text(
                                display_name,
                                weight=flet.FontWeight.W_600,
                                size=15,
                                color=flet.Colors.ON_SURFACE,
                            ),
                            flet.Text(
                                subtitle,
                                size=12.5,
                                color=flet.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        expand=True,
                        spacing=2,
                    ),
                    flet.Icon(
                        flet.Icons.CHEVRON_RIGHT,
                        size=20,
                        color=flet.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                vertical_alignment=flet.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=flet.padding.symmetric(horizontal=12, vertical=8),
            border_radius=12,
            bgcolor=flet.Colors.TRANSPARENT,
            on_click=on_open,
            on_hover=on_hover,
        )

        _tile_cache[room_id] = tile
        return tile

    def _invalidate_tile_cache() -> None:
        """Clear tile cache when room list is refreshed."""
        _tile_cache.clear()

    def _filter_chats(query: str) -> None:
        q = (query or "").lower()

        filtered_personal = (
            [r for r in personal_chats if q in _get_chat_display_name(r).lower()]
            if q
            else personal_chats
        )
        filtered_groups = (
            [r for r in group_chats if q in r["name"].lower()] if q else group_chats
        )
        filtered_public = (
            [r for r in public_rooms if q in r["name"].lower()] if q else public_rooms
        )

        personal_column.controls.clear()
        for r in filtered_personal:
            personal_column.controls.append(_build_chat_tile(r))
        if not filtered_personal:
            personal_column.controls.append(
                flet.Text(
                    t("chat_list.no_personal"),
                    color=flet.Colors.ON_SURFACE_VARIANT,
                    text_align=flet.TextAlign.CENTER,
                )
            )

        group_column.controls.clear()
        for r in filtered_groups:
            group_column.controls.append(_build_chat_tile(r))
        if not filtered_groups:
            group_column.controls.append(
                flet.Text(
                    t("chat_list.no_groups"),
                    color=flet.Colors.ON_SURFACE_VARIANT,
                    text_align=flet.TextAlign.CENTER,
                )
            )

        public_column.controls.clear()
        for r in filtered_public:
            public_column.controls.append(_build_chat_tile(r))
        if not filtered_public:
            public_column.controls.append(
                flet.Text(
                    t("chat_list.no_public"),
                    color=flet.Colors.ON_SURFACE_VARIANT,
                    text_align=flet.TextAlign.CENTER,
                )
            )

        page.update()

    def _apply_data(my_chats: list[dict], public: list[dict]) -> bool:
        """Replace list data and re-render only if something changed."""
        nonlocal personal_chats, group_chats, public_rooms
        new_personal = [r for r in my_chats if r.get("room_type") == "personal"]
        new_groups = [r for r in my_chats if r.get("room_type") == "group"]
        if (new_personal, new_groups, public) == (
            personal_chats,
            group_chats,
            public_rooms,
        ):
            return False
        personal_chats, group_chats, public_rooms = new_personal, new_groups, public
        _invalidate_tile_cache()
        _filter_chats(search_field.value or "")
        return True

    async def _load_chats() -> None:
        # Always fetch fresh data — the cache must not block explicit refreshes
        # (manual button, WS notifications), otherwise the list goes stale.
        client = APIClient(state=state)
        try:
            my_chats, public = await asyncio.gather(
                cache_manager.get("my_chats", client.get_my_rooms, force=True),
                cache_manager.get("public_rooms", client.list_rooms, force=True),
            )
            _apply_data(my_chats, public)
        except Exception as exc:
            snack(page, str(exc), ok=False)
        finally:
            page.update()
            await client.aclose()

    async def do_logout(e: flet.ControlEvent) -> None:
        _stop_refresh()
        await state.logout()
        from views.login_view import login_view

        login_view(page, state)

    def _go_profile(e: flet.ControlEvent) -> None:
        _stop_refresh()
        from views.profile_view import profile_view

        profile_view(page, state)

    state.close_notif_ws()

    def _on_notification(payload: dict) -> None:
        msg_type = payload.get("type")
        if msg_type == "invite":
            room_name = payload.get("payload", {}).get("name", "")
            snack(page, t("chat_list.invited", room=room_name))
            page.run_task(_load_chats)
        elif msg_type == "member_joined":
            data = payload.get("payload", {})
            username = data.get("username", "")
            room_name = data.get("room_name", "")
            snack(
                page,
                t("chat_list.member_joined", username=username, room=room_name),
            )
            page.run_task(_load_chats)

    async def _start_notifications() -> None:
        # Reuse existing connection if already alive, otherwise create one
        if state.ws is not None:
            # Update the notification callback on the existing connection
            state.ws._on_notification = _on_notification
            return
        nc = UnifiedWsClient(
            token=state.token or "",
            on_notification=_on_notification,
            ws_url=state.ws_url,
        )
        state.ws = nc
        await nc.connect()

    def _start_background_refresh() -> None:
        def on_my_chats_update(data):
            _apply_data(data, public_rooms)

        def on_public_rooms_update(data):
            _apply_data(personal_chats + group_chats, data)

        cache_manager.start_background_refresh(
            "my_chats",
            lambda: APIClient(state=state).get_my_rooms(),
            on_my_chats_update,
        )
        cache_manager.start_background_refresh(
            "public_rooms",
            lambda: APIClient(state=state).list_rooms(),
            on_public_rooms_update,
        )

    def _stop_refresh() -> None:
        cache_manager.stop_background_refresh()
        # Don't close the WS here — room_view will reuse it.
        # Only clear the notification callback so stale notifications are ignored.
        if state.ws is not None:
            state.ws._on_notification = None

    def _logged_as() -> str:
        user = state.current_user
        if user is None:
            return ""
        handle = (
            f"{user.username}@{user.server_name}" if user.server_name else user.username
        )
        return t("chat_list.logged_as", user=handle)

    top_bar = flet.Container(
        content=flet.Row(
            controls=[
                flet.Column(
                    controls=[
                        flet.Text(
                            t("chat_list.title"),
                            size=22,
                            weight=flet.FontWeight.BOLD,
                            color=flet.Colors.ON_SURFACE,
                        ),
                        flet.Text(
                            _logged_as(),
                            size=12,
                            color=flet.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=0,
                    expand=True,
                ),
                flet.IconButton(
                    icon=flet.Icons.REFRESH,
                    on_click=lambda e: page.run_task(_load_chats),
                    tooltip=t("chat_list.refresh"),
                    icon_color=flet.Colors.ON_SURFACE_VARIANT,
                ),
                flet.IconButton(
                    icon=flet.Icons.PERSON,
                    on_click=_go_profile,
                    tooltip=t("chat_list.profile"),
                    icon_color=flet.Colors.ON_SURFACE_VARIANT,
                ),
                flet.TextButton(
                    t("chat_list.logout"),
                    on_click=do_logout,
                    style=flet.ButtonStyle(color=flet.Colors.ON_SURFACE_VARIANT),
                ),
            ],
            alignment=flet.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=flet.CrossAxisAlignment.CENTER,
        ),
        bgcolor=flet.Colors.SURFACE,
        padding=flet.padding.symmetric(horizontal=16, vertical=10),
        border=flet.border.only(bottom=flet.BorderSide(1, flet.Colors.OUTLINE_VARIANT)),
    )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                top_bar,
                flet.Container(
                    content=flet.Row(controls=[search_field]),
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
                flet.Container(
                    content=create_buttons,
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
                tabs,
            ],
            expand=True,
            spacing=0,
        )
    )

    _update_create_buttons()
    page.update()
    page.run_task(_load_chats)
    page.run_task(_start_notifications)
    _start_background_refresh()
