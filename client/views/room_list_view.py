from __future__ import annotations

import flet

from client.api.http_client import APIClient
from client.api.ws_client import NotificationClient
from client.config import API_URL
from client.locale import t
from client.state import AppState, RoomDTO


def room_list_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"
    all_rooms: list[dict] = []
    rooms_column = flet.Column(scroll=flet.ScrollMode.AUTO, expand=True, spacing=8)
    search_field = flet.TextField(
        label=t("room_list.search"),
        prefix_icon=flet.Icons.SEARCH,
        expand=True,
        on_change=lambda e: _filter_rooms(e.control.value),
        bgcolor="#ffffff",
        border_color=flet.Colors.TRANSPARENT,
        filled=True,
    )
    status_text = flet.Text("", color="#667781", size=12)

    new_room_name = flet.TextField(label=t("room_list.room_name"), autofocus=True)
    private_toggle = flet.Switch(label=t("room_list.private_room"), value=False)
    create_error = flet.Text("", color="#ea4335", visible=False, size=12)

    async def _do_create_room(e: flet.ControlEvent) -> None:
        create_error.visible = False
        page.update()
        client = APIClient(base_url=API_URL, state=state)
        try:
            room_data = await client.create_room(
                name=new_room_name.value or "",
                is_private=private_toggle.value or False,
            )
            state.active_room = RoomDTO(**{k: room_data[k] for k in RoomDTO.__dataclass_fields__})
            create_dialog.open = False
            page.update()
            _stop_refresh()
            from client.views.room_view import room_view
            room_view(page, state)
        except Exception as exc:
            create_error.value = str(exc)
            create_error.visible = True
            page.update()
        finally:
            await client.aclose()

    create_dialog = flet.AlertDialog(
        title=flet.Text(t("room_list.create_room_title"), weight=flet.FontWeight.BOLD, color="#111b21"),
        content=flet.Column(controls=[new_room_name, private_toggle, create_error], tight=True, spacing=8),
        actions=[
            flet.TextButton(t("room_list.cancel"), on_click=lambda e: _close_dialog(), style=flet.ButtonStyle(color="#008069")),
            flet.ElevatedButton(t("room_list.create"), on_click=_do_create_room, style=flet.ButtonStyle(bgcolor="#008069", color="#ffffff")),
        ],
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
        name_initial = (room.get("name") or "?")[0].upper()

        async def on_join(e: flet.ControlEvent, r: dict = room) -> None:
            client = APIClient(base_url=API_URL, state=state)
            try:
                await client.join_room(r["id"])
                state.active_room = RoomDTO(**{k: r[k] for k in RoomDTO.__dataclass_fields__})
                _stop_refresh()
                from client.views.room_view import room_view
                room_view(page, state)
            except Exception as exc:
                page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
                page.update()
            finally:
                await client.aclose()

        async def on_open(e: flet.ControlEvent, r: dict = room) -> None:
            state.active_room = RoomDTO(**{k: r[k] for k in RoomDTO.__dataclass_fields__})
            _stop_refresh()
            from client.views.room_view import room_view
            room_view(page, state)

        action_btn = (
            flet.ElevatedButton(
                t("room_list.open"),
                on_click=on_open,
                style=flet.ButtonStyle(
                    bgcolor="#d9fdd3", color="#111b21",
                    shape=flet.RoundedRectangleBorder(radius=20),
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
            )
            if member
            else flet.OutlinedButton(
                t("room_list.join"),
                on_click=on_join,
                style=flet.ButtonStyle(
                    color="#008069",
                    shape=flet.RoundedRectangleBorder(radius=20),
                    padding=flet.padding.symmetric(horizontal=16, vertical=8),
                ),
            )
        )

        return flet.Card(
            content=flet.Container(
                content=flet.Row(
                    controls=[
                        flet.CircleAvatar(
                            content=flet.Text(name_initial, color="#ffffff", weight=flet.FontWeight.BOLD, size=16),
                            bgcolor="#008069",
                        ),
                        flet.Column(
                            controls=[
                                flet.Text(room["name"], weight=flet.FontWeight.BOLD, size=15, color="#111b21"),
                                flet.Text(
                                    t("room_list.owner_members", owner=room["owner_username"], count=room["member_count"]),
                                    size=12, color="#667781",
                                ),
                            ],
                            expand=True,
                            spacing=2,
                        ),
                        action_btn,
                    ],
                    alignment=flet.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=flet.CrossAxisAlignment.CENTER,
                ),
                padding=flet.padding.symmetric(horizontal=16, vertical=12),
            ),
            bgcolor="#ffffff",
            elevation=1,
        )

    def _filter_rooms(query: str) -> None:
        q = (query or "").lower()
        filtered = [r for r in all_rooms if q in r["name"].lower()] if q else all_rooms
        rooms_column.controls.clear()
        for r in filtered:
            rooms_column.controls.append(_build_room_tile(r))
        if not filtered:
            rooms_column.controls.append(flet.Text(t("room_list.no_rooms"), color="#667781"))
        page.update()

    async def _load_rooms() -> None:
        nonlocal all_rooms
        status_text.value = t("room_list.loading")
        page.update()
        client = APIClient(base_url=API_URL, state=state)
        try:
            public_rooms = await client.list_rooms()
            try:
                my_rooms = await client.get_my_rooms()
                member_room_ids.clear()
                member_room_ids.update(r["id"] for r in my_rooms)
                public_ids = {r["id"] for r in public_rooms}
                private_member_rooms = [r for r in my_rooms if r["id"] not in public_ids]
                all_rooms = public_rooms + private_member_rooms
            except Exception:
                all_rooms = public_rooms
                if state.current_user:
                    member_room_ids.update(
                        r["id"] for r in all_rooms
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
        client = APIClient(base_url=API_URL, state=state)
        await client.logout()
        await client.aclose()
        from client.views.login_view import login_view
        login_view(page, state)

    _active = {"running": True}

    async def _auto_refresh() -> None:
        import asyncio
        while _active["running"]:
            await asyncio.sleep(10)
            if not _active["running"]:
                break
            await _load_rooms()

    _notif_client: dict = {"client": None}

    def _on_notification(payload: dict) -> None:
        if payload.get("type") == "invite":
            room_name = payload.get("payload", {}).get("name", "")
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room_list.invited", room=room_name), color="#ffffff"),
                open=True, bgcolor="#008069",
            )
            page.update()
            page.run_task(_load_rooms)

    async def _start_notifications() -> None:
        nc = NotificationClient(token=state.token or "", on_notification=_on_notification)
        _notif_client["client"] = nc
        await nc.connect()

    def _stop_refresh() -> None:
        _active["running"] = False
        nc = _notif_client.get("client")
        if nc is not None:
            nc.close()

    def _go_profile(e: flet.ControlEvent) -> None:
        _stop_refresh()
        from client.views.profile_view import profile_view
        profile_view(page, state)

    top_bar = flet.Container(
        content=flet.Row(
            controls=[
                flet.Text(t("room_list.title"), size=22, weight=flet.FontWeight.BOLD, color="#ffffff", expand=True),
                flet.IconButton(icon=flet.Icons.REFRESH, on_click=lambda e: page.run_task(_load_rooms), tooltip=t("room_list.refresh"), icon_color="#ffffff"),
                flet.ElevatedButton(
                    t("room_list.create_room"),
                    on_click=_open_create_dialog,
                    style=flet.ButtonStyle(
                        bgcolor="#00a884", color="#ffffff",
                        shape=flet.RoundedRectangleBorder(radius=20),
                        padding=flet.padding.symmetric(horizontal=16, vertical=8),
                    ),
                ),
                flet.IconButton(icon=flet.Icons.PERSON, on_click=_go_profile, tooltip=t("room_list.profile"), icon_color="#ffffff"),
                flet.TextButton(t("room_list.logout"), on_click=do_logout, style=flet.ButtonStyle(color="#ffffff")),
            ],
            alignment=flet.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=flet.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#008069",
        padding=flet.padding.symmetric(horizontal=16, vertical=12),
    )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                top_bar,
                flet.Container(content=flet.Row(controls=[search_field]), padding=flet.padding.symmetric(horizontal=16, vertical=8)),
                flet.Container(content=status_text, padding=flet.padding.symmetric(horizontal=16)),
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
