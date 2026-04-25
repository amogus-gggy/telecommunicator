import flet as ft


class MarkdownViewer(ft.Container):
    def __init__(self, value: str = "", **kwargs):
        super().__init__(**kwargs)
        self._md = ft.Markdown(
            value=value,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
            selectable=True,
            soft_line_break=True,
            auto_follow_links=True,
            on_tap_link=lambda e: e.page.launch_url(e.data),
        )
        self.content = ft.Column(controls=[self._md], tight=True)

    @property
    def value(self) -> str:
        return self._md.value

    @value.setter
    def value(self, text: str) -> None:
        self._md.value = text
        if self.page is not None:
            self.update()


def resolve_shortcodes(text: str) -> str:
    """Replace :shortcode: patterns with Unicode emoji. Unrecognised shortcodes are left unchanged."""
    try:
        import emoji
        return emoji.emojize(text, language="alias")
    except Exception:
        return text
