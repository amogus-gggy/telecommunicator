import flet as ft
import assets.constants as cnst
import shared

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
                shared.AuthTextField(hint_text="Username"),
                shared.AuthPasswordField(),
                ft.Container(height=10, bgcolor="#00000000", width=0),
                ft.Row(
                    controls=[ # pyright: ignore[reportArgumentType]
                        ft.Text(
                            "Need an account? ",
                            color=cnst.COL_TEXT
                        ),
                        shared.HyperlinkButton("Register Now!"),
                        ft.VerticalDivider(40, color="#00000000"),
                        shared.AuthButton("Login!")
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
    page.title = "Login UI Test"
    page.bgcolor = cnst.COL_BACKGROUND

    page.vertical_alignment   =  ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(LoginUI())


if __name__ == "__main__":
    ft.run(main)