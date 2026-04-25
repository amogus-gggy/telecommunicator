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
            original_on_change = self._text_field.on_selection_change
            
            def on_selection_change(e):
                if e.control.selection is not None:
                    self._last_selection_start = e.control.selection.start
                    self._last_selection_end = e.control.selection.end
                else:
                    self._last_selection_start = None
                    self._last_selection_end = None
                
                # Call original handler if it exists
                if original_on_change is not None:
                    original_on_change(e)
            
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
        """Apply a formatting action at the current cursor position or wrap selected text.
        
        Args:
            action: The formatting action to apply
        """
        # Get current value
        value = self._get_value()
        
        # Use the last tracked selection
        selection_start = self._last_selection_start
        selection_end = self._last_selection_end
        
        # If we have a valid selection, wrap it
        if selection_start is not None and selection_end is not None and selection_start != selection_end:
            # Wrap the selected text
            selected_text = value[selection_start:selection_end]
            new_value = value[:selection_start] + action.prefix + selected_text + action.suffix + value[selection_end:]
        else:
            # No selection, insert at cursor position
            cursor = self._get_cursor()
            
            # Fall back to end of string if cursor is None
            if cursor is None:
                cursor = len(value)
            
            # Clamp cursor to valid range
            cursor = max(0, min(cursor, len(value)))
            
            # Build the insertion text
            insertion = action.prefix + action.placeholder + action.suffix
            
            # Insert at cursor position
            new_value = value[:cursor] + insertion + value[cursor:]
        
        # Update the value
        self._set_value(new_value)
