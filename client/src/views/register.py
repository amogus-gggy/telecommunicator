import flet as ft
import assets.constants as cnst

class RegisterUI(ft.Container):
    def __init__(self, page: ft.Page):
        super().__init__()
        self.bgcolor = cnst.COL_CARD
        self.padding = 20
        self.border_radius = 10
        self.content = ft.Column(
            controls=[ # pyright: ignore[reportArgumentType]
                ft.Text(
                    value="Telecommunicator",
                    size=44,
                    weight=ft.FontWeight.W_500,
                    text_align=ft.TextAlign.CENTER,
                    color=cnst.COL_TEXT
                ),
                ft.TextField(
                    hint_text="Username",
                    autocorrect=False,
                    border_radius=10,
                    border_width=0,
                    bgcolor=cnst.COL_TEXT_FIELD,
                    color=cnst.COL_TEXT
                ),
                ft.TextField(
                    hint_text="Email",
                    autocorrect=False,
                    border_radius=10,
                    border_width=0,
                    bgcolor=cnst.COL_TEXT_FIELD,
                    color=cnst.COL_TEXT
                ),
                ft.TextField(
                    hint_text="Password",
                    autocorrect=False,
                    password=True,
                    can_reveal_password=True,
                    border_radius=10,
                    border_width=0,
                    bgcolor=cnst.COL_TEXT_FIELD,
                    color=cnst.COL_TEXT
                ),
                ft.Container(height=10, bgcolor=ft.Colors.TRANSPARENT, width=0),
                ft.Row(
                    controls=[ # pyright: ignore[reportArgumentType]
                        ft.Text(
                            "Already have an account? ",
                            color=cnst.COL_TEXT
                        ),
                        ft.GestureDetector(
                            mouse_cursor=ft.MouseCursor.CLICK,
                            content=ft.Text(
                                "Login Here!",
                                color=ft.Colors.BLUE,
                                style=ft.TextStyle(
                                    decoration=ft.TextDecoration.UNDERLINE,
                                    decoration_color=ft.Colors.BLUE
                                )
                            ),
                            on_tap=lambda _: page.go("/login")
                        ),
                        ft.VerticalDivider(40, color="#00000000"),
                        ft.Button(
                            content="Register!",
                            color=cnst.COL_BUTTON_TEXT,
                            disabled=True,
                            style=ft.ButtonStyle(
                                bgcolor={
                                    ft.ControlState.DEFAULT: cnst.COL_BUTTON,
                                    ft.ControlState.DISABLED: cnst.COL_BUTTON_DISABLED
                                }
                            )
                        )
                    ],
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0
                )
            ],
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        )


def main(page: ft.Page):
    page.title = "Telecommunicator - Register"
    return ft.View(
        route="/register",
        controls=[RegisterUI(page)],
        vertical_alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        bgcolor = cnst.COL_BACKGROUND
    )