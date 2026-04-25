#!/usr/bin/env python3
"""Verification script for Task 5: Checkpoint — Ensure all widget tests pass"""

import sys

def test_markdown_viewer():
    """Test MarkdownViewer and resolve_shortcodes imports and basic functionality."""
    print("Testing markdown_viewer.py...")
    
    try:
        from client.views.widgets.markdown_viewer import MarkdownViewer, resolve_shortcodes
        print("  ✓ Successfully imported MarkdownViewer and resolve_shortcodes")
    except ImportError as e:
        print(f"  ✗ Failed to import: {e}")
        return False
    
    # Test resolve_shortcodes
    test_text = "Hello :smile: world"
    resolved = resolve_shortcodes(test_text)
    if "😄" in resolved or "😊" in resolved:
        print(f"  ✓ resolve_shortcodes works: '{test_text}' → '{resolved}'")
    else:
        print(f"  ✗ resolve_shortcodes failed: '{test_text}' → '{resolved}'")
        return False
    
    # Test MarkdownViewer instantiation (without page context)
    try:
        viewer = MarkdownViewer(value="**bold** text")
        if viewer.value == "**bold** text":
            print(f"  ✓ MarkdownViewer instantiation and value property work")
        else:
            print(f"  ✗ MarkdownViewer value mismatch: expected '**bold** text', got '{viewer.value}'")
            return False
    except Exception as e:
        print(f"  ✗ MarkdownViewer instantiation failed: {e}")
        return False
    
    print("  ✓ markdown_viewer.py: ALL CHECKS PASSED\n")
    return True


def test_emoji_picker():
    """Test EmojiPicker and EMOJI_CATALOGUE imports and basic functionality."""
    print("Testing emoji_picker.py...")
    
    try:
        from client.views.widgets.emoji_picker import EmojiPicker, EMOJI_CATALOGUE
        print("  ✓ Successfully imported EmojiPicker and EMOJI_CATALOGUE")
    except ImportError as e:
        print(f"  ✗ Failed to import: {e}")
        return False
    
    # Test EMOJI_CATALOGUE has data
    if not EMOJI_CATALOGUE:
        print("  ✗ EMOJI_CATALOGUE is empty")
        return False
    
    total_emojis = sum(len(entries) for entries in EMOJI_CATALOGUE.values())
    num_categories = len(EMOJI_CATALOGUE)
    print(f"  ✓ EMOJI_CATALOGUE has {num_categories} categories with {total_emojis} total emojis")
    
    if total_emojis < 500:
        print(f"  ⚠ Warning: Expected at least 500 emojis, found {total_emojis}")
    
    # Test EmojiPicker instantiation
    try:
        picker = EmojiPicker(
            on_emoji_selected=lambda char: None,
            on_close=lambda: None,
        )
        print(f"  ✓ EmojiPicker instantiation works")
    except Exception as e:
        print(f"  ✗ EmojiPicker instantiation failed: {e}")
        return False
    
    print("  ✓ emoji_picker.py: ALL CHECKS PASSED\n")
    return True


def test_formatting_toolbar():
    """Test FormattingToolbar and _FormatAction imports and basic functionality."""
    print("Testing formatting_toolbar.py...")
    
    try:
        from client.views.widgets.formatting_toolbar import FormattingToolbar, _FormatAction
        print("  ✓ Successfully imported FormattingToolbar and _FormatAction")
    except ImportError as e:
        print(f"  ✗ Failed to import: {e}")
        return False
    
    # Test FormattingToolbar instantiation
    test_value = "hello world"
    cursor_pos = 5
    
    def get_value():
        return test_value
    
    def set_value(new_val):
        nonlocal test_value
        test_value = new_val
    
    def get_cursor():
        return cursor_pos
    
    try:
        toolbar = FormattingToolbar(
            get_value=get_value,
            set_value=set_value,
            get_cursor=get_cursor,
            disabled=False,
        )
        print(f"  ✓ FormattingToolbar instantiation works")
        
        # Check that toolbar has controls (buttons)
        if len(toolbar.controls) >= 5:
            print(f"  ✓ FormattingToolbar has {len(toolbar.controls)} formatting buttons")
        else:
            print(f"  ✗ FormattingToolbar has only {len(toolbar.controls)} buttons, expected at least 5")
            return False
            
    except Exception as e:
        print(f"  ✗ FormattingToolbar instantiation failed: {e}")
        return False
    
    print("  ✓ formatting_toolbar.py: ALL CHECKS PASSED\n")
    return True


def main():
    print("=" * 60)
    print("Task 5: Widget Verification Checkpoint")
    print("=" * 60 + "\n")
    
    results = []
    results.append(("markdown_viewer.py", test_markdown_viewer()))
    results.append(("emoji_picker.py", test_emoji_picker()))
    results.append(("formatting_toolbar.py", test_formatting_toolbar()))
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for module, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {module}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n✓ ALL WIDGET MODULES ARE FUNCTIONAL\n")
        return 0
    else:
        print("\n✗ SOME WIDGET MODULES HAVE ISSUES\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
