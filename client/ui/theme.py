from __future__ import annotations

from dataclasses import dataclass, field

import flet

FONT_FAMILY = "RobotoFlex"

AVATAR_GRADIENTS = [
    ["#FF885E", "#FF516A"],
    ["#FFCD6A", "#FFA85C"],
    ["#82B1FF", "#665FFF"],
    ["#A0DE7E", "#54CB68"],
    ["#53EDD6", "#28C9B7"],
    ["#72D5FD", "#2A9EF1"],
    ["#E0A2F3", "#D669ED"],
    ["#FF9AA2", "#E5737F"],
]


@dataclass(frozen=True)
class Palette:
    """Hex colors for things Material tokens cannot express."""

    chat_bg: list[str]
    own_bubble: str
    other_bubble: str
    snackbar_bg: str
    snackbar_text: str


LIGHT_PALETTE = Palette(
    chat_bg=["#F0F2F5", "#E4EAEE"],
    own_bubble="#D9FDD3",
    other_bubble="#FFFFFF",
    snackbar_bg="#1F2C33",
    snackbar_text="#FFFFFF",
)

DARK_PALETTE = Palette(
    chat_bg=["#0E1621", "#0E1621"],
    own_bubble="#1F3D33",
    other_bubble="#17212B",
    snackbar_bg="#2B3B47",
    snackbar_text="#F5F5F5",
)


def light_scheme() -> flet.ColorScheme:
    return flet.ColorScheme(
        primary="#00A884",
        on_primary="#FFFFFF",
        primary_container="#D9FDD3",
        on_primary_container="#0B3D2E",
        secondary="#00A884",
        on_secondary="#FFFFFF",
        tertiary="#2A9EF1",
        error="#EA4335",
        on_error="#FFFFFF",
        surface="#FFFFFF",
        on_surface="#111B21",
        on_surface_variant="#667781",
        outline="#8696A0",
        outline_variant="#E0E4E7",
        shadow="#000000",
        inverse_surface="#1F2C33",
        on_inverse_surface="#FFFFFF",
        surface_container_lowest="#FFFFFF",
        surface_container_low="#F5F6F6",
        surface_container="#F0F2F5",
        surface_container_high="#EAECED",
        surface_container_highest="#E2E5E7",
    )


def dark_scheme() -> flet.ColorScheme:
    return flet.ColorScheme(
        primary="#2DD4A7",
        on_primary="#0E1621",
        primary_container="#1F3D33",
        on_primary_container="#D9FDD3",
        secondary="#2DD4A7",
        on_secondary="#0E1621",
        tertiary="#5EB5F7",
        error="#F28B82",
        on_error="#1F0E0D",
        surface="#17212B",
        on_surface="#F5F5F5",
        on_surface_variant="#8696A0",
        outline="#3E5466",
        outline_variant="#2B3B47",
        shadow="#000000",
        inverse_surface="#F5F5F5",
        on_inverse_surface="#17212B",
        surface_container_lowest="#0B131B",
        surface_container_low="#131C26",
        surface_container="#17212B",
        surface_container_high="#1E2A36",
        surface_container_highest="#232E3C",
    )


def _build_theme(scheme: flet.ColorScheme) -> flet.Theme:
    return flet.Theme(
        use_material3=True,
        font_family=FONT_FAMILY,
        color_scheme=scheme,
        snackbar_theme=flet.SnackBarTheme(
            shape=flet.RoundedRectangleBorder(radius=12),
            behavior=flet.SnackBarBehavior.FLOATING,
            show_close_icon=False,
        ),
        dialog_theme=flet.DialogTheme(
            shape=flet.RoundedRectangleBorder(radius=20),
            elevation=4,
        ),
        card_theme=flet.CardTheme(
            elevation=0,
            shape=flet.RoundedRectangleBorder(radius=16),
        ),
        tab_bar_theme=flet.TabBarTheme(
            indicator_color=flet.Colors.PRIMARY,
            label_color=flet.Colors.PRIMARY,
            unselected_label_color=flet.Colors.ON_SURFACE_VARIANT,
        ),
    )


def _resolve_theme_mode(theme_mode: str) -> flet.ThemeMode:
    if theme_mode == "light":
        return flet.ThemeMode.LIGHT
    if theme_mode == "dark":
        return flet.ThemeMode.DARK
    return flet.ThemeMode.SYSTEM


def set_theme_mode(page: flet.Page, theme_mode: str) -> None:
    """Switch the active theme mode (\"system\" | \"light\" | \"dark\")."""
    page.theme_mode = _resolve_theme_mode(theme_mode)
    page.update()


def apply_theme(page: flet.Page, theme_mode: str = "system") -> None:
    page.fonts = {FONT_FAMILY: "fonts/RobotoFlex.ttf"}
    page.theme_mode = _resolve_theme_mode(theme_mode)
    page.theme = _build_theme(light_scheme())
    page.dark_theme = _build_theme(dark_scheme())
    page.padding = 0


def is_dark(page: flet.Page) -> bool:
    mode = getattr(page, "theme_mode", None)
    if mode == flet.ThemeMode.DARK:
        return True
    if mode == flet.ThemeMode.LIGHT:
        return False
    try:
        brightness = getattr(page, "platform_brightness", None)
        return brightness == flet.Brightness.DARK
    except Exception:
        return False


def palette(page: flet.Page) -> Palette:
    return DARK_PALETTE if is_dark(page) else LIGHT_PALETTE


def themed_field(**kwargs) -> flet.TextField:
    defaults = dict(
        filled=True,
        bgcolor=flet.Colors.SURFACE_CONTAINER_LOW,
        border_radius=12,
        border_color=flet.Colors.TRANSPARENT,
        focused_border_color=flet.Colors.PRIMARY,
        cursor_color=flet.Colors.PRIMARY,
        color=flet.Colors.ON_SURFACE,
        hint_style=flet.TextStyle(color=flet.Colors.ON_SURFACE_VARIANT, size=14),
        label_style=flet.TextStyle(color=flet.Colors.ON_SURFACE_VARIANT, size=14),
        text_size=15,
        content_padding=flet.padding.symmetric(horizontal=16, vertical=14),
    )
    defaults.update(kwargs)
    return flet.TextField(**defaults)


def primary_button(text: str, on_click=None, **kwargs) -> flet.ElevatedButton:
    return flet.ElevatedButton(
        text,
        on_click=on_click,
        style=flet.ButtonStyle(
            bgcolor=flet.Colors.PRIMARY,
            color=flet.Colors.ON_PRIMARY,
            shape=flet.RoundedRectangleBorder(radius=12),
            padding=flet.padding.symmetric(vertical=14, horizontal=24),
        ),
        **kwargs,
    )


def snack(page: flet.Page, text: str, ok: bool = True) -> None:
    pal = palette(page)
    page.snack_bar = flet.SnackBar(
        content=flet.Text(text, color=pal.snackbar_text, size=14),
        bgcolor=pal.snackbar_bg if ok else flet.Colors.ERROR,
        behavior=flet.SnackBarBehavior.FLOATING,
        shape=flet.RoundedRectangleBorder(radius=12),
        margin=flet.margin.all(16),
    )
    page.snack_bar.open = True
    page.update()


def initials_avatar(name: str, size: int = 44) -> flet.Container:
    words = [w for w in (name or "?").split() if w]
    letters = "".join(w[0] for w in words[:2]).upper() or "?"
    gradient = AVATAR_GRADIENTS[hash(name or "?") % len(AVATAR_GRADIENTS)]
    return flet.Container(
        content=flet.Text(
            letters,
            color="#FFFFFF",
            size=size * 0.38,
            weight=flet.FontWeight.W_600,
        ),
        width=size,
        height=size,
        border_radius=size // 2,
        alignment=flet.Alignment.CENTER,
        gradient=flet.LinearGradient(
            begin=flet.Alignment.TOP_LEFT,
            end=flet.Alignment.BOTTOM_RIGHT,
            colors=gradient,
        ),
    )


def surface_app_bar(
    title: str,
    on_back=None,
    subtitle: str | None = None,
    actions: list | None = None,
    leading: flet.Control | None = None,
) -> flet.Container:
    title_controls: list[flet.Control] = [
        flet.Text(title, size=17, weight=flet.FontWeight.W_600, color=flet.Colors.ON_SURFACE)
    ]
    if subtitle:
        title_controls.append(
            flet.Text(subtitle, size=12.5, color=flet.Colors.ON_SURFACE_VARIANT)
        )
    controls: list[flet.Control] = []
    if on_back is not None:
        controls.append(
            flet.IconButton(
                flet.Icons.ARROW_BACK,
                icon_color=flet.Colors.ON_SURFACE,
                on_click=on_back,
                tooltip="Back",
            )
        )
    if leading is not None:
        controls.append(leading)
    controls.append(
        flet.Column(
            controls=title_controls,
            spacing=1,
            alignment=flet.MainAxisAlignment.CENTER,
            expand=True,
        )
    )
    if actions:
        controls.extend(actions)
    return flet.Container(
        content=flet.Row(
            controls=controls,
            vertical_alignment=flet.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        bgcolor=flet.Colors.SURFACE,
        padding=flet.padding.symmetric(horizontal=8, vertical=8),
        border=flet.border.only(bottom=flet.BorderSide(1, flet.Colors.OUTLINE_VARIANT)),
    )
