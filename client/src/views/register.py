import flet as ft
import assets.constants as cnst

state = {
    "username": "",
    "email": "",
    "password": ""
}

async def register_ui(page: ft.Page):
    page.title = "Telecommunicator - Register"

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
        value=state["username"],
        hint_text="Username",
        autocorrect=False,
        border_radius=10,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT,
        on_change=lambda e: state.update({"username": e.control.value})
    )
    email = ft.TextField(
        value=state["email"],
        hint_text="Email",
        autocorrect=False,
        border_radius=10,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT,
        on_change=lambda e: state.update({"email": e.control.value})
    )
    password = ft.TextField(
        value=state["password"],
        hint_text="Password",
        autocorrect=False,
        password=True,
        can_reveal_password=True,
        border_radius=10,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT,
        on_change=lambda e: state.update({"password": e.control.value})
    )

    hspacer = ft.Container(height=10, bgcolor=ft.Colors.TRANSPARENT, width=0)

    row = ft.Row(
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=0,
        controls=[
            ft.Text("Have an account? ")
        ]
    )
    hyperlink_button = ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.CLICK,
        content=ft.Text(
            "Login!",
            color=ft.Colors.BLUE,
            style=ft.TextStyle(
                decoration=ft.TextDecoration.UNDERLINE,
                decoration_color=ft.Colors.BLUE
            )
        ),
        on_tap=lambda _: page.go("/auth/login")
    )

    vspacer = ft.VerticalDivider(40, color=ft.Colors.TRANSPARENT)
    login = ft.Button(
        content="Register!",
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
    column.controls.append(email)
    column.controls.append(password)
    column.controls.append(hspacer)
    column.controls.append(row)

    card.content = column

    return ft.View(
        controls=[card],
        route="/auth/register",
        vertical_alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        bgcolor = cnst.COL_BACKGROUND
    )