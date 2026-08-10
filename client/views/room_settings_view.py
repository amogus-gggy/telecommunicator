from __future__ import annotations

import flet

from api.http_client import APIClient, ForbiddenError
from localization import t
from state import AppState
from ui.theme import snack, surface_app_bar


def room_settings_view(page: flet.Page, state: AppState) -> None:
    page.bgcolor = flet.Colors.SURFACE_CONTAINER
    page.overlay.clear()
    room = state.active_room

    def _go_back(e: flet.ControlEvent | None = None) -> None:
        from views.room_view import room_view

        room_view(page, state)

    if (
        room is None
        or state.current_user is None
        or state.current_user.username != room.owner_username
    ):
        snack(page, t("room_settings.only_owner_access"), ok=False)
        _go_back()
        return

    allow_invite_switch = flet.Switch(
        label=t("room_settings.allow_invite"),
        value=room.allow_member_invite,
        active_color=flet.Colors.PRIMARY,
        label_text_style=flet.TextStyle(color=flet.Colors.ON_SURFACE, size=15),
    )
    read_only_switch = flet.Switch(
        label=t("room_settings.read_only"),
        value=room.read_only,
        active_color=flet.Colors.PRIMARY,
        label_text_style=flet.TextStyle(color=flet.Colors.ON_SURFACE, size=15),
    )

    async def _on_allow_invite_change(e: flet.ControlEvent) -> None:
        new_value: bool = allow_invite_switch.value or False
        client = APIClient(state=state)
        try:
            updated = await client.update_permissions(
                room.id, allow_member_invite=new_value
            )
            room.allow_member_invite = updated.get("allow_member_invite", new_value)
            room.read_only = updated.get("read_only", room.read_only)
            snack(page, t("room_settings.permissions_updated"))
        except ForbiddenError:
            snack(page, t("room_settings.only_owner_permissions"), ok=False)
            allow_invite_switch.value = not new_value
            page.update()
        except Exception as exc:
            snack(page, str(exc), ok=False)
            allow_invite_switch.value = not new_value
            page.update()
        finally:
            await client.aclose()

    async def _on_read_only_change(e: flet.ControlEvent) -> None:
        new_value: bool = read_only_switch.value or False
        client = APIClient(state=state)
        try:
            updated = await client.update_permissions(room.id, read_only=new_value)
            room.allow_member_invite = updated.get(
                "allow_member_invite", room.allow_member_invite
            )
            room.read_only = updated.get("read_only", new_value)
            snack(page, t("room_settings.permissions_updated"))
        except ForbiddenError:
            snack(page, t("room_settings.only_owner_permissions"), ok=False)
            read_only_switch.value = not new_value
            page.update()
        except Exception as exc:
            snack(page, str(exc), ok=False)
            read_only_switch.value = not new_value
            page.update()
        finally:
            await client.aclose()

    allow_invite_switch.on_change = _on_allow_invite_change
    read_only_switch.on_change = _on_read_only_change

    if room.room_type == "personal":
        settings_content = flet.Column(
            controls=[
                flet.Text(
                    t("room_settings.permissions"),
                    size=16,
                    weight=flet.FontWeight.W_600,
                    color=flet.Colors.ON_SURFACE,
                ),
                flet.Divider(height=8, color=flet.Colors.OUTLINE_VARIANT),
                flet.Text(
                    t("room_settings.personal_auto"),
                    size=14,
                    color=flet.Colors.ON_SURFACE_VARIANT,
                    italic=True,
                ),
            ],
            spacing=16,
        )
    else:
        settings_content = flet.Column(
            controls=[
                flet.Text(
                    t("room_settings.permissions"),
                    size=16,
                    weight=flet.FontWeight.W_600,
                    color=flet.Colors.ON_SURFACE,
                ),
                flet.Divider(height=8, color=flet.Colors.OUTLINE_VARIANT),
                allow_invite_switch,
                read_only_switch,
            ],
            spacing=16,
        )

    page.controls.clear()
    page.add(
        flet.Column(
            controls=[
                surface_app_bar(
                    t("room_settings.title", name=room.name),
                    on_back=_go_back,
                ),
                flet.Container(
                    content=flet.Container(
                        content=settings_content,
                        padding=20,
                        bgcolor=flet.Colors.SURFACE,
                        border_radius=16,
                        border=flet.border.all(1, flet.Colors.OUTLINE_VARIANT),
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
