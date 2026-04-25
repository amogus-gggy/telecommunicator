import flet as ft
import assets.constants as cnst
import views

async def main(page: ft.Page):
    page.title = "Telecommunicator"
    page.bgcolor = cnst.COL_BACKGROUND

    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    def route_changed(e):
        page.views.clear()
        # Use .startswith or normalized strings to be safe
        sel_route = page.route.strip()
        
        if sel_route == "/" or sel_route == "":
            page.go("/login")
            return

        if sel_route == "/login":
            new_view = views.login.main(page)
            page.views.append(new_view)
            if len(page.views) > 1:
                page.views.pop(0)
        elif sel_route == "/register":
            new_view = views.register.main(page)
            page.views.append(new_view)
            if len(page.views) > 1:
                page.views.pop(0)
        
        print(f"Target Route: {sel_route} | Views in stack: {len(page.views)}")
        page.update()

    page.on_route_change = route_changed
    # Start the app
    if page.route == "/":
        page.go("/login")
    else:
        page.update()


ft.run(main)
