from turtle import bgcolor
import flet as ft
import assets.constants as cnst
from typing import Callable

@ft.control
class AuthButton(ft.Button):
    color=cnst.COL_BUTTON_TEXT
    style=ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: cnst.COL_BUTTON,
            ft.ControlState.DISABLED: cnst.COL_BUTTON_DISABLED
        }
    )

@ft.control
class AuthTextField(ft.TextField):
    autocorrect=False
    border_radius=10
    border_width=0
    bgcolor=cnst.COL_TEXT_FIELD
    color=cnst.COL_TEXT

@ft.control
class AuthPasswordField(AuthTextField):
    hint_text="Password"
    password=True
    can_reveal_password=True

@ft.control
class HyperlinkButton(ft.GestureDetector):
    def __init__(self, value: str, on_click: ft.ControlEventHandler[ft.Text] | None = None, **kwargs):
        super().__init__()
        self.mouse_cursor=ft.MouseCursor.CLICK
        self.on_click = on_click
        self.content=ft.Text(
            value,
            color=ft.Colors.BLUE,
            style=ft.TextStyle(
                decoration=ft.TextDecoration.UNDERLINE,
                decoration_color=ft.Colors.BLUE
            ),
        )