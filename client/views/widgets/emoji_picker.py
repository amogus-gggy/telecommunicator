from __future__ import annotations

from typing import Callable

import emoji
import flet as ft


def _categorize(char: str) -> str:
    """Assign a category to an emoji based on its Unicode code point range."""
    cp = ord(char[0])
    if 0x1F600 <= cp <= 0x1F64F:
        return "Smileys & Emotion"
    if 0x1F466 <= cp <= 0x1F46F or 0x1F9D0 <= cp <= 0x1F9FF or 0x1F91A <= cp <= 0x1F91F:
        return "People & Body"
    if 0x1F400 <= cp <= 0x1F43F or 0x1F980 <= cp <= 0x1F9AE:
        return "Animals & Nature"
    if 0x1F32D <= cp <= 0x1F37F or 0x1F950 <= cp <= 0x1F96F:
        return "Food & Drink"
    if 0x1F680 <= cp <= 0x1F6FF or 0x1F30D <= cp <= 0x1F32C:
        return "Travel & Places"
    if 0x1F3A0 <= cp <= 0x1F3FF or 0x1F4A0 <= cp <= 0x1F4FF:
        return "Activities & Objects"
    if 0x1F500 <= cp <= 0x1F5FF:
        return "Symbols"
    if 0x1F1E0 <= cp <= 0x1F1FF:
        return "Flags"
    return "Other"


# Build catalogue at module import time
EMOJI_CATALOGUE: dict[str, list[tuple[str, str]]] = {}
for _char, _data in emoji.EMOJI_DATA.items():
    # Only include fully-qualified emoji (status 2)
    if _data.get("status", 0) != 2:
        continue
    
    # Skip flags (Regional Indicator Symbols) - they often don't render correctly
    # Flags are composed of two Regional Indicator characters (U+1F1E6 to U+1F1FF)
    if len(_char) >= 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in _char[:2]):
        continue
    
    _group = _categorize(_char)
    _name = _data.get("en", _char).strip(":")
    EMOJI_CATALOGUE.setdefault(_group, []).append((_char, _name))


def _filter_emojis(query: str) -> dict[str, list[tuple[str, str]]]:
    """Return catalogue filtered by query (case-insensitive name substring)."""
    if not query:
        return EMOJI_CATALOGUE
    q = query.lower()
    result: dict[str, list[tuple[str, str]]] = {}
    for group, entries in EMOJI_CATALOGUE.items():
        matched = [(char, name) for char, name in entries if q in name.lower()]
        if matched:
            result[group] = matched
    return result


def _build_grid(entries: list[tuple[str, str]], on_click: Callable[[str], None]) -> ft.GridView:
    return ft.GridView(
        runs_count=8,
        max_extent=40,
        spacing=2,
        run_spacing=2,
        expand=True,
        controls=[
            ft.TextButton(
                content=ft.Text(char, size=20),
                tooltip=name,
                on_click=lambda e, c=char: on_click(c),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            for char, name in entries
        ],
    )


class EmojiPicker(ft.Container):
    def __init__(
        self,
        on_emoji_selected: Callable[[str], None],
        on_close: Callable[[], None],
        **kwargs,
    ):
        self._on_emoji_selected = on_emoji_selected
        self._on_close = on_close

        self._search_field = ft.TextField(
            hint_text="Search emojis…",
            dense=True,
            height=40,
            on_change=self._on_search_change,
        )

        self._tabs = self._build_tabs(EMOJI_CATALOGUE)

        column = ft.Column(
            controls=[self._search_field, self._tabs],
            spacing=4,
            expand=True,
        )

        super().__init__(
            content=column,
            width=350,
            height=400,
            padding=ft.padding.all(8),
            border_radius=ft.border_radius.all(12),
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=12,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            ),
            bgcolor=ft.Colors.SURFACE,
            visible=False,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_tabs(self, catalogue: dict[str, list[tuple[str, str]]]) -> ft.Tabs:
        tab_labels = []
        tab_contents = []
        
        for group, entries in catalogue.items():
            short_label = group.split("&")[0].strip()[:12]
            tab_labels.append(ft.Tab(label=short_label))
            tab_contents.append(_build_grid(entries, self._emoji_clicked))
        
        return ft.Tabs(
            content=ft.Column([
                ft.TabBar(tabs=tab_labels),
                ft.TabBarView(controls=tab_contents, expand=True),
            ]),
            length=len(tab_labels),
            expand=True,
        )

    def _emoji_clicked(self, char: str) -> None:
        self._on_emoji_selected(char)
        self.close()

    def _on_search_change(self, e: ft.ControlEvent) -> None:
        query = e.control.value or ""
        filtered = _filter_emojis(query)
        new_tabs = self._build_tabs(filtered)
        
        # Replace the tabs content
        self._tabs.content = new_tabs.content
        self._tabs.length = new_tabs.length
        self._tabs.selected_index = 0
        
        if self.page:
            self.update()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> None:
        self.visible = True
        if self.page:
            self.update()

    def close(self) -> None:
        self.visible = False
        if self.page:
            self.update()
