from __future__ import annotations

import flet

from client.api.http_client import APIClient, ForbiddenError
from client.config import API_URL
from client.locale import t
from client.state import AppState


def room_settings_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = "#f0f2f5"
    room = state.active_room

    def _go_back(e: flet.ControlEvent | None = None) -> None:
        from client.views.room_view import room_view
        room_view(page, state)

    if (
        room is None
        or state.current_user is None
        or state.current_user.username != room.owner_username
    ):
        page.snack_bar = flet.SnackBar(
            flet.Text(t("room_settings.only_owner_access"), color="#ffffff"),
            open=True, bgcolor="#ea4335",
        )
        page.update()
        _go_back()
        return

    allow_invite_switch = flet.Switch(label=t("room_settings.allow_invite"), value=room.allow_member_invite)
    read_only_switch = flet.Switch(label=t("room_settings.read_only"), value=room.read_only)

    async def _on_allow_invite_change(e: flet.ControlEvent) -> None:
        new_value: bool = allow_invite_switch.value or False
        client = APIClient(base_url=API_URL, state=state)
        try:
            updated = await client.update_permissions(room.id, allow_member_invite=new_value)
            room.allow_member_invite = updated.get("allow_member_invite", new_value)
            room.read_only = updated.get("read_only", room.read_only)
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room_settings.permissions_updated"), color="#ffffff"),
                open=True, bgcolor="#008069",
            )
            page.update()
        except ForbiddenError:
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room_settings.only_owner_permissions"), color="#ffffff"),
                open=True, bgcolor="#ea4335",
            )
            allow_invite_switch.value = not new_value
            page.update()
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            allow_invite_switch.value = not new_value
            page.update()
        finally:
            await client.aclose()

    async def _on_read_only_change(e: flet.ControlEvent) -> None:
        new_value: bool = read_only_switch.value or False
        client = APIClient(base_url=API_URL, state=state)
        try:
            updated = await client.update_permissions(room.id, read_only=new_value)
            room.allow_member_invite = updated.get("allow_member_invite", room.allow_member_invite)
            room.read_only = updated.get("read_only", new_value)
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room_settings.permissions_updated"), color="#ffffff"),
                open=True, bgcolor="#008069",
            )
            page.update()
        except ForbiddenError:
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room_settings.only_owner_permissions"), color="#ffffff"),
                open=True, bgcolor="#ea4335",
            )
            read_only_switch.value = not new_value
            page.update()
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            read_only_switch.value = not new_value
            page.update()
        finally:
            await client.aclose()

    allow_invite_switch.on_change = _on_allow_invite_change
    read_only_switch.on_change = _on_read_only_change

    if room.room_type == "personal":
        settings_content = flet.Column(
            controls=[
                flet.Text(t("room_settings.permissions"), size=16, weight=flet.FontWeight.W_600, color="#111b21"),
                flet.Divider(height=8),
                flet.Text(t("room_settings.personal_auto"), size=14, color="#667781", italic=True),
            ],
            spacing=16,
        )
    else:
        settings_content = flet.Column(
            controls=[
                flet.Text(t("room_settings.permissions"), size=16, weight=flet.FontWeight.W_600, color="#111b21"),
                flet.Divider(height=8),
                allow_invite_switch,
                read_only_switch,
            ],
            spacing=16,
        )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                flet.Container(
                    content=flet.Row(
                        controls=[
                            flet.IconButton(
                                icon=flet.Icons.ARROW_BACK,
                                on_click=_go_back,
                                tooltip=t("room_settings.back"),
                                icon_color="#ffffff",
                            ),
                            flet.Text(
                                t("room_settings.title", name=room.name),
                                size=20,
                                weight=flet.FontWeight.BOLD,
                                color="#ffffff",
                            ),
                        ],
                        vertical_alignment=flet.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#008069",
                    padding=flet.padding.symmetric(horizontal=8, vertical=8),
                ),
                flet.Container(
                    content=flet.Card(
                        content=flet.Container(content=settings_content, padding=20),
                        bgcolor="#ffffff",
                        elevation=1,
                    ),
                    padding=16,
                    expand=True,
                ),
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()
