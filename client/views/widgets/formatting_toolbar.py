"""Formatting toolbar widget for inserting Markdown syntax into message input."""

from dataclasses import dataclass
from typing import Callable, Optional

import flet as ft


@dataclass
class _FormatAction:
    """Defines a formatting action with its icon, tooltip, and Markdown syntax."""
    icon: str
    tooltip: str
    prefix: str
    suffix: str
    placeholder: str


class FormattingToolbar(ft.Row):
    """A toolbar with buttons for inserting Markdown formatting syntax.
    
    Args:
        get_value: Callable that returns the current input field value
        set_value: Callable that sets the input field value
        get_cursor: Callable that returns the current cursor position (or None)
        text_field: Optional reference to the TextField for selection support
        disabled: Whether the toolbar buttons should be disabled
        **kwargs: Additional arguments forwarded to ft.Row
    """
    
    def __init__(
        self,
        get_value: Callable[[], str],
        set_value: Callable[[str], None],
        get_cursor: Callable[[], int],
        text_field: Optional[ft.TextField] = None,
        disabled: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        
        self._get_value = get_value
        self._set_value = set_value
        self._get_cursor = get_cursor
        self._text_field = text_field
        self._last_selection_start = None
        self._last_selection_end = None
        
        # Track selection changes if text_field is provided
        if self._text_field is not None:
            original_on_selection_change = self._text_field.on_selection_change

            def on_selection_change(e):
                if e.control.selection is not None:
                    self._last_selection_start = e.control.selection.start
                    self._last_selection_end = e.control.selection.end
                if original_on_selection_change is not None:
                    original_on_selection_change(e)

            self._text_field.on_selection_change = on_selection_change

        # Define formatting actions
        actions = [
            _FormatAction(
                icon=ft.Icons.FORMAT_BOLD,
                tooltip="Bold",
                prefix="**",
                suffix="**",
                placeholder="bold",
            ),
            _FormatAction(
                icon=ft.Icons.FORMAT_ITALIC,
                tooltip="Italic",
                prefix="_",
                suffix="_",
                placeholder="italic",
            ),
            _FormatAction(
                icon=ft.Icons.STRIKETHROUGH_S,
                tooltip="Strikethrough",
                prefix="~~",
                suffix="~~",
                placeholder="strikethrough",
            ),
            _FormatAction(
                icon=ft.Icons.CODE,
                tooltip="Inline code",
                prefix="`",
                suffix="`",
                placeholder="code",
            ),
            _FormatAction(
                icon=ft.Icons.FORMAT_QUOTE,
                tooltip="Blockquote",
                prefix="> ",
                suffix="",
                placeholder="quote",
            ),
        ]

        # Create icon buttons for each action
        self.controls = [
            ft.IconButton(
                icon=action.icon,
                tooltip=action.tooltip,
                disabled=disabled,
                on_click=lambda e, a=action: self._apply(a) if not disabled else None,
            )
            for action in actions
        ]

    def _apply(self, action: _FormatAction) -> None:
        """Apply a formatting action at the current cursor position or wrap selected text."""
        value = self._get_value()

        selection_start = self._last_selection_start
        selection_end = self._last_selection_end

        has_selection = (
            selection_start is not None
            and selection_end is not None
            and selection_start != selection_end
        )

        if has_selection:
            selected_text = value[selection_start:selection_end]
            new_value = (
                value[:selection_start]
                + action.prefix
                + selected_text
                + action.suffix
                + value[selection_end:]
            )
        else:
            cursor = self._get_cursor()
            if cursor is None:
                cursor = len(value)
            cursor = max(0, min(cursor, len(value)))

            insertion = action.prefix + action.placeholder + action.suffix
            new_value = value[:cursor] + insertion + value[cursor:]

        self._set_value(new_value)


        if self._text_field is not None:
            self._text_field.update()
            self._text_field.focus()