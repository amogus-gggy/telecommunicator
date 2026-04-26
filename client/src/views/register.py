import flet as ft
import assets.constants as cnst
import email_validator as emval
import asyncio

state = {
    "username": "",
    "email": "",
    "password": ""
}

email_checker_thread = None
async def on_email_change(e, page, err):
    global email_checker_thread
    state["email"] = e.control.value

    if email_checker_thread: email_checker_thread.cancel()
    if not state["email"]:
        err.visible = False
        page.update()
        return

    async def task():
        try:
            await asyncio.sleep(cnst.DAT_AUTH_EMAIL_DELAY)

            emval.validate_email(state["email"])
            err.visible = False
        except (emval.EmailNotValidError, asyncio.CancelledError):
            err.visible = not isinstance(e, asyncio.CancelledError)
        
        page.update()
    
    email_checker_thread = asyncio.create_task(task())


async def register_ui(page: ft.Page):
    page.title = "Telecommunicator - Register"

    card = ft.Container(
        bgcolor=cnst.COL_CARD,
        padding=20,
        border_radius=cnst.BORDER_RADIUS
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
        label="Username",
        autocorrect=False,
        border_radius=cnst.BORDER_RADIUS,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT,
        on_change=lambda e: state.update({"username": e.control.value})
    )

    email_error = ft.Text(
        value="Invalid Email",
        color=ft.Colors.RED,
        visible=False
    )
    async def on_email_change_wrapper(e):
        return await on_email_change(e, page, email_error)

    email = ft.TextField(
        value=state["email"],
        label="Email",
        autocorrect=False,
        border_radius=cnst.BORDER_RADIUS,
        border_width=0,
        bgcolor=cnst.COL_TEXT_FIELD,
        color=cnst.COL_TEXT,
        on_change=on_email_change_wrapper
    )
    password = ft.TextField(
        value=state["password"],
        label="Password",
        autocorrect=False,
        password=True,
        can_reveal_password=True,
        border_radius=cnst.BORDER_RADIUS,
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
            ft.Text("Have an account? ", color=cnst.COL_TEXT)
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
    column.controls.append(email_error)
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