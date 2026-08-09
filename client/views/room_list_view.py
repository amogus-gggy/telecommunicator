from __future__ import annotations

import flet

from api.http_client import APIClient
from api.ws_client import UnifiedWsClient
from localization import t
from state import AppState, RoomDTO
from ui.theme import initials_avatar, primary_button, snack, themed_field


def room_list_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = flet.Colors.SURFACE_CONTAINER
    page.overlay.clear()
    all_rooms: list[dict] = []
    rooms_column = flet.Column(scroll=flet.ScrollMode.AUTO, expand=True, spacing=8)
    search_field = themed_field(
        hint_text=t("room_list.search"),
        prefix_icon=flet.Icons.SEARCH,
        expand=True,
        on_change=lambda e: _filter_rooms(e.control.value),
        border_radius=20,
        bgcolor=flet.Colors.SURFACE_CONTAINER_HIGH,
    )
    status_text = flet.Text("", color=flet.Colors.ON_SURFACE_VARIANT, size=12)

    new_room_name = themed_field(label=t("room_list.room_name"), autofocus=True)
    private_toggle = flet.Switch(
        label=t("room_list.private_room"),
        value=False,
        active_color=flet.Colors.PRIMARY,
        label_text_style=flet.TextStyle(color=flet.Colors.ON_SURFACE, size=14),
    )
    create_error = flet.Text("", color=flet.Colors.ERROR, visible=False, size=12)

    async def _do_create_room(e: flet.ControlEvent) -> None:
        create_error.visible = False
        page.update()
        client = APIClient(state=state)
        try:
            room_data = await client.create_room(
                name=new_room_name.value or "",
                is_private=private_toggle.value or False,
            )
            state.active_room = RoomDTO(
                **{k: room_data.get(k) for k in RoomDTO.__dataclass_fields__}
            )
            create_dialog.open = False
            page.update()
            _stop_refresh()
            from views.room_view import room_view

            room_view(page, state)
        except Exception as exc:
            create_error.value = str(exc)
            create_error.visible = True
            page.update()
        finally:
            await client.aclose()

    create_dialog = flet.AlertDialog(
        title=flet.Text(
            t("room_list.create_room_title"),
            weight=flet.FontWeight.BOLD,
            color=flet.Colors.ON_SURFACE,
        ),
        content=flet.Column(
            controls=[new_room_name, private_toggle, create_error],
            tight=True,
            spacing=8,
        ),
        actions=[
            flet.TextButton(
                t("room_list.cancel"),
                on_click=lambda e: _close_dialog(),
                style=flet.ButtonStyle(color=flet.Colors.PRIMARY),
            ),
            primary_button(t("room_list.create"), on_click=_do_create_room),
        ],
        bgcolor=flet.Colors.SURFACE,
    )

    def _close_dialog() -> None:
        create_dialog.open = False
        page.update()

    def _open_create_dialog(e: flet.ControlEvent) -> None:
        new_room_name.value = ""
        private_toggle.value = False
        create_error.visible = False
        create_dialog.open = True
        page.update()

    page.overlay.append(create_dialog)

    member_room_ids: set[int] = set()

    def _is_member(room: dict) -> bool:
        return room.get("id") in member_room_ids

    def _build_room_tile(room: dict) -> flet.Control:
        member = _is_member(room)

        async def on_join(e: flet.ControlEvent, r: dict = room) -> None:
            client = APIClient(state=state)
            try:
                await client.join_room(r["id"])
                state.active_room = RoomDTO(
                    **{k: r[k] for k in RoomDTO.__dataclass_fields__}
                )
                _stop_refresh()
                from views.room_view import room_view

                room_view(page, state)
            except Exception as exc:
                snack(page, str(exc), ok=False)
            finally:
                await client.aclose()

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

        action_btn = (
            flet.ElevatedButton(
                t("room_list.open"),
                on_click=on_open,
                style=flet.ButtonStyle(
                    bgcolor=flet.Colors.PRIMARY_CONTAINER,
                    color=flet.Colors.ON_PRIMARY_CONTAINER,
                    shape=flet.RoundedRectangleBorder(radius=20),
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
            )
            if member
            else flet.OutlinedButton(
                t("room_list.join"),
                on_click=on_join,
                style=flet.ButtonStyle(
                    color=flet.Colors.PRIMARY,
                    side=flet.BorderSide(1, flet.Colors.PRIMARY),
                    shape=flet.RoundedRectangleBorder(radius=20),
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
            )
        )

        return flet.Container(
            content=flet.Row(
                controls=[
                    initials_avatar(room.get("name") or "?", size=44),
                    flet.Column(
                        controls=[
                            flet.Text(
                                room["name"],
                                weight=flet.FontWeight.W_600,
                                size=15,
                                color=flet.Colors.ON_SURFACE,
                            ),
                            flet.Text(
                                t(
                                    "room_list.owner_members",
                                    owner=room["owner_username"],
                                    count=room["member_count"],
                                ),
                                size=12.5,
                                color=flet.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        expand=True,
                        spacing=2,
                    ),
                    action_btn,
                ],
                vertical_alignment=flet.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=flet.padding.symmetric(horizontal=12, vertical=8),
            border_radius=12,
            bgcolor=flet.Colors.TRANSPARENT,
            on_hover=on_hover,
        )

    def _filter_rooms(query: str) -> None:
        q = (query or "").lower()
        filtered = [r for r in all_rooms if q in r["name"].lower()] if q else all_rooms
        rooms_column.controls.clear()
        for r in filtered:
            rooms_column.controls.append(_build_room_tile(r))
        if not filtered:
            rooms_column.controls.append(
                flet.Text(t("room_list.no_rooms"), color=flet.Colors.ON_SURFACE_VARIANT)
            )
        page.update()

    async def _load_rooms() -> None:
        nonlocal all_rooms
        status_text.value = t("room_list.loading")
        page.update()
        client = APIClient(state=state)
        try:
            public_rooms = await client.list_rooms()
            try:
                my_rooms = await client.get_my_rooms()
                member_room_ids.clear()
                member_room_ids.update(r["id"] for r in my_rooms)
                public_ids = {r["id"] for r in public_rooms}
                private_member_rooms = [
                    r for r in my_rooms if r["id"] not in public_ids
                ]
                all_rooms = public_rooms + private_member_rooms
            except Exception:
                all_rooms = public_rooms
                if state.current_user:
                    member_room_ids.update(
                        r["id"]
                        for r in all_rooms
                        if r.get("owner_username") == state.current_user.username
                    )
            _filter_rooms(search_field.value or "")
            status_text.value = t("room_list.loaded", count=len(all_rooms))
        except Exception as exc:
            status_text.value = t("room_list.error_loading", exc=exc)
        finally:
            page.update()
            await client.aclose()

    async def do_logout(e: flet.ControlEvent) -> None:
        _stop_refresh()
        await state.logout()
        from views.login_view import login_view

        login_view(page, state)

    _active = {"running": True}

    async def _auto_refresh() -> None:
        import asyncio

        while _active["running"]:
            await asyncio.sleep(10)
            if not _active["running"]:
                break
            await _load_rooms()

    def _on_notification(payload: dict) -> None:
        if payload.get("type") == "invite":
            room_name = payload.get("payload", {}).get("name", "")
            snack(page, t("room_list.invited", room=room_name))
            page.run_task(_load_rooms)

    async def _start_notifications() -> None:
        if state.ws is not None:
            state.ws._on_notification = _on_notification
            return
        nc = UnifiedWsClient(
            token=state.token or "",
            on_notification=_on_notification,
            ws_url=state.ws_url,
        )
        state.ws = nc
        await nc.connect()

    def _stop_refresh() -> None:
        _active["running"] = False
        if state.ws is not None:
            state.ws._on_notification = None

    def _go_profile(e: flet.ControlEvent) -> None:
        _stop_refresh()
        from views.profile_view import profile_view

        profile_view(page, state)

    top_bar = flet.Container(
        content=flet.Row(
            controls=[
                flet.Text(
                    t("room_list.title"),
                    size=22,
                    weight=flet.FontWeight.BOLD,
                    color=flet.Colors.ON_SURFACE,
                    expand=True,
                ),
                flet.IconButton(
                    icon=flet.Icons.REFRESH,
                    on_click=lambda e: page.run_task(_load_rooms),
                    tooltip=t("room_list.refresh"),
                    icon_color=flet.Colors.ON_SURFACE_VARIANT,
                ),
                flet.ElevatedButton(
                    t("room_list.create_room"),
                    on_click=_open_create_dialog,
                    style=flet.ButtonStyle(
                        bgcolor=flet.Colors.PRIMARY,
                        color=flet.Colors.ON_PRIMARY,
                        shape=flet.RoundedRectangleBorder(radius=20),
                        padding=flet.padding.symmetric(horizontal=16, vertical=8),
                    ),
                ),
                flet.IconButton(
                    icon=flet.Icons.PERSON,
                    on_click=_go_profile,
                    tooltip=t("room_list.profile"),
                    icon_color=flet.Colors.ON_SURFACE_VARIANT,
                ),
                flet.TextButton(
                    t("room_list.logout"),
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
                    content=status_text, padding=flet.padding.symmetric(horizontal=16)
                ),
                flet.Divider(height=4, color=flet.Colors.TRANSPARENT),
                rooms_column,
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()
    page.run_task(_load_rooms)
    page.run_task(_auto_refresh)
    page.run_task(_start_notifications)
