import flet as ft
import assets.constants as cnst

class LoginUI(ft.Container):
    def __init__(self):
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
                ),
                ft.TextField(
                    hint_text="Password",
                    autocorrect=False,
                    password=True,
                    can_reveal_password=True,
                    border_radius=10,
                    border_width=0,
                    bgcolor=cnst.COL_TEXT_FIELD,
                ),
                ft.Button(
                    content="Log in!",
                    color=cnst.COL_BUTTON_TEXT,
                    bgcolor=cnst.COL_BUTTON
                )
            ],
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        )


def main(page: ft.Page):
    page.title = "Login UI Test"
    page.bgcolor = cnst.COL_BACKGROUND

    page.vertical_alignment   =  ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(LoginUI())


if __name__ == "__main__":
    ft.run(main)