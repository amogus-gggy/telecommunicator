import flet as ft
import assets.constants as cnst

async def login_ui(page: ft.Page):
    page.title = "Telecommunicator - Login"

    card = ft.Container(
        bgcolor=cnst.COL_CARD,
        padding=20,
        border_radius=10
    )

    column = ft.Column(
        tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER
    )

    header = ft.Text(
        value="Telecommunicator",
        size=44,
        weight=ft.FontWeight.W_500,
        text_align=ft.TextAlign.CENTER,
        color=cnst.COL_TEXT
    )

    username = ft.TextField(
        hint_text="Username",
        autocorrect=False,
        border_radius=10,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT
    )
    password = ft.TextField(
        hint_text="Password",
        autocorrect=False,
        password=True,
        can_reveal_password=True,
        border_radius=10,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT
    )

    hspacer = ft.Container(height=10, bgcolor=ft.Colors.TRANSPARENT, width=0)

    row = ft.Row(
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=0,
        controls=[
            ft.Text("Need an account?")
        ]
    )
    hyperlink_button = ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.CLICK,
        content=ft.Text(
            "Register Now!",
            color=ft.Colors.BLUE,
            style=ft.TextStyle(
                decoration=ft.TextDecoration.UNDERLINE,
                decoration_color=ft.Colors.BLUE
            )
        ),
        on_tap=lambda _: page.push_route("/auth/register")
    )

    vspacer = ft.VerticalDivider(40, color=ft.Colors.TRANSPARENT)
    login = ft.Button(
        content="Login!",
        color=cnst.COL_BUTTON_TEXT,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: cnst.COL_BUTTON,
                ft.ControlState.DISABLED: cnst.COL_BUTTON_DISABLED
            }
        ),
        disabled=True
    )

    row.controls.append(hyperlink_button)
    row.controls.append(vspacer)
    row.controls.append(login)

    column.controls.append(header)
    column.controls.append(username)
    column.controls.append(password)
    column.controls.append(hspacer)
    column.controls.append(row)

    card.content = column

    return ft.View(
        controls=[card],
        route="/auth/login"
    )