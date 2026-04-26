import flet as ft
import assets.constants as cnst
import views

async def main(page: ft.Page):
    page.title = "Telecommunicator"
    page.vertical_alignment=ft.MainAxisAlignment.CENTER
    page.horizontal_alignment=ft.CrossAxisAlignment.CENTER

    page.bgcolor = cnst.COL_BACKGROUND

    async def route_changed(e):
        page.views.clear()
        page.controls.clear()
        if page.route == "/auth/login":
            page.views.append(await views.login.login_ui(page))
        elif page.route == "/auth/register":
            page.views.append(await views.register.register_ui(page))
        
        page.update()
    
    page.on_route_change = route_changed
    await page.push_route("/auth/login")

ft.run(main)
