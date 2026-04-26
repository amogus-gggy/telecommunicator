import flet as ft
import assets.constants as cnst
from time import time as currentTime
import views

async def main(page: ft.Page):
    page.title = "Telecommunicator"
    page.vertical_alignment=ft.MainAxisAlignment.CENTER
    page.horizontal_alignment=ft.CrossAxisAlignment.CENTER

    page.bgcolor = cnst.COL_BACKGROUND
    page.theme = ft.Theme(
        page_transitions=ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.CUPERTINO,
            ios=ft.PageTransitionTheme.CUPERTINO,
            macos=ft.PageTransitionTheme.NONE,
            linux=ft.PageTransitionTheme.NONE,
            windows=ft.PageTransitionTheme.NONE,
        )
    )

    async def route_changed(e):
        page.views.clear()

        if page.route == "/auth/login":
            view = await views.login.login_ui(page)
            page.views.append(view)
        elif page.route == "/auth/register":
            view = await views.register.register_ui(page)
            page.views.append(view)
        
        page.update()
    
    page.on_route_change = route_changed
    await page.push_route("/auth/register")

ft.run(main)
