from __future__ import annotations

import logging
import flet

from api.http_client import APIClient, AuthError
from api.ws_client import UnifiedWsClient
from config import API_URL
from localization import t
from state import AppState
from views.widgets.markdown_viewer import MarkdownViewer, resolve_shortcodes
from views.widgets.formatting_toolbar import FormattingToolbar
from views.widgets.emoji_picker import EmojiPicker

import httpx


def room_view(page: flet.Page, state: AppState) -> None:
    room = state.active_room
    print(f"[room_view] entered, room={room}")
    if room is None:
        print("[room_view] room is None, returning early")
        return

    page.bgcolor = "#efeae2"
    print("[room_view] creating widgets...")

    messages_list = flet.ListView(
        expand=True,
        spacing=6,
        auto_scroll=False,
    )

    file_picker: flet.FilePicker = flet.FilePicker()

    attached_files: list[flet.FilePickerFile] = []
    attached_preview = flet.Row(scroll="auto", spacing=6)

    async def pick_file(e):
        files = await file_picker.pick_files(allow_multiple=True, with_data=True)
        
        if files is not None:
            for file in files:
                attached_files.append(file)

        attached_preview.controls.clear()

        for i, f in enumerate(attached_files):
            idx = i
            attached_preview.controls.append(
                flet.Row(
                    spacing=4,
                    controls=[
                        flet.Icon(flet.Icons.ATTACH_FILE, size=14, color="#008069"),
                        flet.Text(f.name, size=12),
                        flet.IconButton(
                            icon=flet.Icons.CLOSE,
                            icon_size=14,
                            on_click=lambda e, i=idx: _remove_attached_file(i),
                        ),
                    ],
                )
            )

        page.update()

    def _remove_attached_file(idx: int) -> None:
        if 0 <= idx < len(attached_files):
            attached_files.pop(idx)
        attached_preview.controls.clear()
        for i, f in enumerate(attached_files):
            attached_preview.controls.append(
                flet.Row(
                    spacing=4,
                    controls=[
                        flet.Icon(flet.Icons.ATTACH_FILE, size=14, color="#008069"),
                        flet.Text(f.name, size=12),
                        flet.IconButton(
                            icon=flet.Icons.CLOSE,
                            icon_size=14,
                            on_click=lambda e, i=i: _remove_attached_file(i),
                        ),
                    ],
                )
            )
        page.update()

    message_input = flet.TextField(
        label=t("room.message_hint"),
        expand=True,
        multiline=True,
        on_submit=lambda e: page.run_task(_send_message),
        bgcolor="#ffffff",
        filled=True,
        border_color=flet.Colors.TRANSPARENT,
        color=flet.Colors.BLACK
    )
    print("[room_view] message_input ok")

    reconnecting_banner = flet.Container(
        content=flet.Text(
            t("room.reconnecting"),
            color="#ffffff",
            size=13,
            weight=flet.FontWeight.W_500,
        ),
        bgcolor="#f57c00",
        padding=flet.padding.symmetric(horizontal=12, vertical=6),
        visible=False,
        border_radius=4,
        alignment=flet.alignment.Alignment(0, 0),
    )
    print("[room_view] reconnecting_banner ok")

    _state: dict = {"min_id": None, "loading_older": False, "ws_client": None, "user_at_bottom": True, "messages_data": []}

    # User profile bottom sheet
    _profile_sheet_content = flet.Column(tight=True, spacing=8, width=320)
    _profile_sheet = flet.BottomSheet(
        content=flet.Container(
            content=_profile_sheet_content,
            padding=flet.padding.all(20),
        ),
        open=False,
    )

    page.overlay.append(_profile_sheet)
    print("[room_view] profile_sheet ok")

    # Emoji picker callbacks
    def _on_emoji_selected(emoji_char: str) -> None:
        """Insert emoji at cursor position or at end of message."""
        current_value = message_input.value or ""
        
        # TextField doesn't expose cursor_position, so just append to end
        new_value = current_value + emoji_char
        message_input.value = new_value
        page.update()

    def _on_emoji_picker_close() -> None:
        """Hide the emoji picker."""
        emoji_picker.close()
        page.update()

    # Create emoji picker
    print("[room_view] creating EmojiPicker...")
    emoji_picker = EmojiPicker(
        on_emoji_selected=_on_emoji_selected,
        on_close=_on_emoji_picker_close,
    )
    page.overlay.append(emoji_picker)
    print("[room_view] EmojiPicker ok")

    def _toggle_emoji_picker(e: flet.ControlEvent) -> None:
        """Toggle emoji picker visibility."""
        if emoji_picker.visible:
            emoji_picker.close()
        else:
            emoji_picker.open()
        page.update()

    async def _show_user_profile(username: str) -> None:
        _profile_sheet_content.controls.clear()
        _profile_sheet_content.controls.append(
            flet.Text(t("room.loading"), size=14, color="#667781")
        )
        _profile_sheet.open = True
        page.update()

        client = APIClient(base_url=API_URL, state=state)
        try:
            data = await client.get_user(username)
            dn = data.get("display_name") or ""
            _profile_sheet_content.controls.clear()
            _profile_sheet_content.controls += [
                flet.Row(
                    controls=[
                        flet.Icon(
                            flet.Icons.ACCOUNT_CIRCLE, size=48, color="#008069"
                        ),
                        flet.Column(
                            controls=[
                                flet.Text(
                                    data.get("username", ""),
                                    size=18,
                                    weight=flet.FontWeight.BOLD,
                                    color="#111b21",
                                ),
                                flet.Text(
                                    dn, size=14, color="#667781"
                                )
                                if dn
                                else flet.Text(
                                    t("room.no_display_name"),
                                    size=14,
                                    color="#667781",
                                    italic=True,
                                ),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=flet.CrossAxisAlignment.CENTER,
                ),
                flet.Divider(height=8),
                flet.Row(
                    controls=[
                        flet.Icon(flet.Icons.BADGE, size=18, color="#667781"),
                        flet.Text(
                            t("room.username_label", username=data.get('username', '')),
                            size=14,
                            color="#111b21",
                        ),
                    ],
                    spacing=8,
                ),
                flet.Row(
                    controls=[
                        flet.Icon(flet.Icons.LABEL, size=18, color="#667781"),
                        flet.Text(
                            t("room.display_name_label", name=dn or "—"), size=14, color="#111b21"
                        ),
                    ],
                    spacing=8,
                ),
                flet.TextButton(
                    t("room.close"),
                    on_click=lambda e: _close_profile_sheet(),
                    style=flet.ButtonStyle(color="#008069"),
                ),
            ]
            page.update()
        except Exception as exc:
            _profile_sheet_content.controls.clear()
            _profile_sheet_content.controls.append(
                flet.Text(str(exc), color="#ea4335")
            )
            page.update()
        finally:
            await client.aclose()

    def _close_profile_sheet() -> None:
        _profile_sheet.open = False
        page.update()

    def _build_message_tile(msg: dict) -> flet.Control:
        author = msg.get("author_username", "?")
        display_name = msg.get("author_display_name") or author
        body = msg.get("body", "")
        ts_raw = msg.get("created_at", "")
        ts = ts_raw
        if isinstance(ts_raw, str) and "T" in ts_raw:
            ts = ts_raw.split("T")[1][:5]

        is_me = (
            state.current_user is not None
            and author == state.current_user.username
        )

        alignment = state.message_alignment
        if alignment == "right":
            on_right = True
        elif alignment == "left":
            on_right = False
        else:
            on_right = is_me  # default: mine on right, others on left

        bubble_color = "#d9fdd3" if is_me else "#ffffff"
        name_color = "#008069"

        file_controls = []

        for file_item in msg.get("files", []):
            file_id_val = file_item["id"]
            file_name_val = file_item.get("filename", "download")
            # Attach message author as uploader_username fallback for key lookup
            if "uploader_username" not in file_item:
                file_item = dict(file_item)
                file_item.setdefault("uploader_username", msg.get("author_username"))

            async def local_download_task(fid: int, fname: str, file_meta: dict):
                client = APIClient(base_url=API_URL, state=state)
                try:
                    url = f"{API_URL}/rooms/{room.id}/files/{fid}/download"

                    # Fetch file bytes first
                    async with httpx.AsyncClient() as http:
                        r = await http.get(url, headers=client._headers())
                        r.raise_for_status()
                        file_bytes = r.content

                    # Decrypt if encrypted
                    if file_meta.get("is_encrypted"):
                        try:
                            import base64
                            import logging
                            from crypto.file_crypto import FileDecryptor
                            from crypto.key_generator import KeyGenerator

                            decryptor = FileDecryptor()
                            is_own = (
                                state.current_user is not None
                                and file_meta.get("uploader_id") == state.current_user.id
                            )

                            if is_own and file_meta.get("key_sender_blob"):
                                file_bytes = decryptor.decrypt_own_file(
                                    ciphertext=file_bytes,
                                    key_sender_blob_b64=file_meta["key_sender_blob"],
                                    x25519_priv=state.x25519_private,
                                )
                            elif file_meta.get("key_blob") and file_meta.get("key_signature"):
                                # Need sender public key
                                sender_keys = None
                                sender_username = file_meta.get("uploader_username") or file_meta.get("author_username")
                                if sender_username and state.public_key_cache:
                                    sender_keys = state.public_key_cache.get_public_keys(sender_username)
                                if not sender_keys and sender_username:
                                    _kc = APIClient(base_url=API_URL, state=state)
                                    try:
                                        kd = await _kc.get_public_keys(sender_username)
                                        ed_pub = KeyGenerator.load_ed25519_public_key(base64.b64decode(kd["identity_pub_ed25519"]))
                                        x_pub = KeyGenerator.load_x25519_public_key(base64.b64decode(kd["identity_pub_x25519"]))
                                        sender_keys = {"ed25519_pub": ed_pub, "x25519_pub": x_pub}
                                        if state.public_key_cache:
                                            state.public_key_cache.set_public_keys(sender_username, ed_pub, x_pub)
                                    finally:
                                        await _kc.aclose()

                                if sender_keys:
                                    file_bytes = decryptor.decrypt_file(
                                        ciphertext=file_bytes,
                                        key_blob_b64=file_meta["key_blob"],
                                        signature_b64=file_meta["key_signature"],
                                        x25519_priv=state.x25519_private,
                                        sender_ed25519_pub=sender_keys["ed25519_pub"],
                                    )
                        except Exception as dec_exc:
                            import logging
                            logging.error(f"[FILE] Decryption failed: {dec_exc}", exc_info=True)
                            page.snack_bar = flet.SnackBar(
                                flet.Text(f"Decryption failed: {dec_exc}", color="#fff"),
                                open=True, bgcolor="#ea4335",
                            )
                            page.update()
                            return

                    # save_file on Android/iOS/web requires src_bytes
                    save_path = await file_picker.save_file(
                        file_name=fname,
                        file_type=flet.FilePickerFileType.ANY,
                        src_bytes=file_bytes,
                    )

                    # On desktop save_path is returned and we write the file ourselves
                    if save_path:
                        with open(save_path, "wb") as f_save:
                            f_save.write(file_bytes)

                    page.snack_bar = flet.SnackBar(
                        flet.Text(f"Downloaded {fname}", color="#fff"),
                        open=True,
                        bgcolor="#008069",
                    )
                except Exception as e:
                    page.snack_bar = flet.SnackBar(
                        flet.Text(str(e), color="#fff"),
                        open=True,
                        bgcolor="#ea4335",
                    )
                finally:
                    await client.aclose()
                page.update()

            file_controls.append(
                flet.Container(
                    padding=10,
                    border_radius=12,
                    bgcolor=flet.Colors.with_opacity(0.06, flet.Colors.ON_SURFACE),
                    margin=flet.margin.symmetric(vertical=4),
                    content=flet.Row(
                        alignment=flet.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=flet.CrossAxisAlignment.CENTER,
                        controls=[
                            flet.Row(
                                spacing=10,
                                controls=[
                                    flet.Icon(
                                        flet.Icons.ATTACH_FILE,
                                        size=18,
                                        opacity=0.8,
                                    ),
                                    flet.Text(
                                        value=file_name_val,
                                        size=13,
                                        weight=flet.FontWeight.W_500,
                                        overflow=flet.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                            ),

                            flet.IconButton(
                                icon=flet.Icons.DOWNLOAD,
                                icon_size=18,
                                tooltip="Download",
                                on_click=lambda e, fid=file_id_val, fn=file_name_val, fm=file_item: page.run_task(
                                    local_download_task,
                                    fid,
                                    fn,
                                    fm,
                                ),
                            ),
                        ],
                    ),
                )
            )

        bubble = flet.Container(
            content=flet.Column(
                controls=[
                    flet.TextButton(
                        display_name,
                        on_click=lambda e, u=author: page.run_task(
                            _show_user_profile, u
                        ),
                        style=flet.ButtonStyle(
                            color=name_color,
                            padding=flet.padding.all(0),
                        ),
                    )
                    if not is_me
                    else flet.Container(),
                    MarkdownViewer(value=body),
                    *file_controls,
                    flet.Row(
                        controls=[
                            flet.Text(ts, size=10, color="#667781"),
                        ],
                        alignment=flet.MainAxisAlignment.END,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor=bubble_color,
            border_radius=flet.border_radius.only(
                top_left=12,
                top_right=12,
                bottom_left=4 if on_right else 12,
                bottom_right=12 if on_right else 4,
            ),
            padding=flet.padding.symmetric(horizontal=12, vertical=6),
            border=flet.Border.all(1, "#e0e0e0") if not on_right else None,
            animate_scale=flet.Animation(200, flet.AnimationCurve.EASE_OUT),
            animate_opacity=flet.Animation(200, flet.AnimationCurve.EASE_OUT),
        )

        msg_id = msg.get("id")
        spacer = flet.Container(expand=True)

        if on_right:
            return flet.Row(
                key=str(msg_id) if msg_id else None,
                controls=[spacer, bubble],
                vertical_alignment=flet.CrossAxisAlignment.START,
            )
        else:
            return flet.Row(
                key=str(msg_id) if msg_id else None,
                controls=[bubble, spacer],
                vertical_alignment=flet.CrossAxisAlignment.START,
            )

    def _animate_message(message_control: flet.Row) -> None:
        """Animate a newly added message bubble."""
        bubble = message_control.controls[0] if message_control.controls else None
        if bubble is None:
            return
        # Set initial state (bubble is the first control — either spacer or container)
        # Find the Container (bubble) — it's always the non-spacer control
        container = next(
            (c for c in message_control.controls if isinstance(c, flet.Container) and c.content is not None),
            None,
        )
        if container is None:
            return
        container.scale = 0.85
        container.opacity = 0.0
        page.update()
        container.scale = 1.0
        container.opacity = 1.0
        page.update()

    async def _smooth_scroll_to_bottom() -> None:
        """Smoothly scroll to the bottom of the chat area."""
        print("[SCROLL] Starting smooth scroll to bottom...")
        # Small delay to ensure UI is rendered
        import asyncio
        await asyncio.sleep(0.1)
        await messages_list.scroll_to(
            offset=-1,
            duration=400,
            curve=flet.AnimationCurve.EASE_OUT,
        )
        print("[SCROLL] Smooth scroll completed")

    def _is_user_at_bottom() -> bool:
        """Check if user is scrolled near the bottom of the chat."""
        # We track this via on_scroll event
        return _state.get("user_at_bottom", True)

    async def _decrypt_message_if_needed(msg: dict) -> dict:
        """Decrypt message if it's encrypted, otherwise return as-is."""
        if not msg.get("is_encrypted"):
            return msg
        
        # If current user is the sender, decrypt using the sender's own copy
        if (
            state.current_user is not None
            and msg.get("author_username") == state.current_user.username
        ):
            sender_blob = msg.get("sender_encrypted_blob")
            if not sender_blob:
                # Old message without sender copy — just show placeholder
                if not msg.get("body"):
                    msg["body"] = t("room.encrypted_sent")
                return msg

            import base64
            import logging
            from crypto.message_crypto import MessageDecryptor
            from cryptography.exceptions import InvalidTag

            try:
                decryptor = MessageDecryptor()
                msg["body"] = decryptor.decrypt_own_message(sender_blob, state.x25519_private)
                msg["decrypted"] = True
            except (InvalidTag, Exception) as exc:
                logging.error(f"[DECRYPT] Failed to decrypt own message: {exc}")
                msg["body"] = t("room.encrypted_sent")
            return msg
        
        # Message is encrypted, attempt to decrypt
        import base64
        import logging
        from crypto.message_crypto import MessageDecryptor
        from crypto.key_generator import KeyGenerator
        from cryptography.exceptions import InvalidSignature, InvalidTag
        
        try:
            if not state.x25519_private or not state.ed25519_private:
                logging.warning("[DECRYPT] No private keys available")
                msg["body"] = t("room.encrypted_no_keys")
                msg["decryption_error"] = True
                return msg
            
            # Get sender public keys
            sender_username = msg.get("author_username")
            if not sender_username:
                logging.warning("[DECRYPT] No sender username in message")
                msg["body"] = t("room.encrypted_unknown_sender")
                msg["decryption_error"] = True
                return msg
            
            sender_keys = None
            if state.public_key_cache:
                sender_keys = state.public_key_cache.get_public_keys(sender_username)
            
            if not sender_keys:
                logging.info(f"[DECRYPT] Fetching public keys for {sender_username}")
                client = APIClient(base_url=API_URL, state=state)
                try:
                    keys_data = await client.get_public_keys(sender_username)
                    ed25519_pub_bytes = base64.b64decode(keys_data["identity_pub_ed25519"])
                    x25519_pub_bytes = base64.b64decode(keys_data["identity_pub_x25519"])
                    
                    ed25519_pub = KeyGenerator.load_ed25519_public_key(ed25519_pub_bytes)
                    x25519_pub = KeyGenerator.load_x25519_public_key(x25519_pub_bytes)
                    
                    sender_keys = {"ed25519_pub": ed25519_pub, "x25519_pub": x25519_pub}
                    if state.public_key_cache:
                        state.public_key_cache.set_public_keys(sender_username, ed25519_pub, x25519_pub)
                finally:
                    await client.aclose()
            
            # Decrypt message
            encrypted_blob = msg.get("encrypted_blob")
            signature = msg.get("signature")
            
            if not encrypted_blob or not signature:
                logging.warning("[DECRYPT] Missing encrypted_blob or signature")
                msg["body"] = t("room.encrypted_malformed")
                msg["decryption_error"] = True
                return msg
            
            logging.info(f"[DECRYPT] Decrypting message from {sender_username}")
            decryptor = MessageDecryptor()
            encrypted_data = {
                "blob": encrypted_blob,
                "signature": signature
            }
            
            plaintext = decryptor.decrypt_message(
                encrypted_msg=encrypted_data,
                recipient_x25519_priv=state.x25519_private,
                sender_ed25519_pub=sender_keys["ed25519_pub"]
            )
            
            msg["body"] = plaintext
            msg["decrypted"] = True
            logging.info("[DECRYPT] Message decrypted successfully")
            return msg
            
        except InvalidSignature:
            logging.error(f"[DECRYPT] Signature verification failed for message from {sender_username}")
            msg["body"] = t("room.encrypted_bad_signature")
            msg["signature_error"] = True
            return msg
        except InvalidTag:
            logging.error(f"[DECRYPT] Decryption failed for message from {sender_username}")
            msg["body"] = t("room.encrypted_bad_key")
            msg["decryption_error"] = True
            return msg
        except Exception as exc:
            logging.error(f"[DECRYPT] Unexpected error: {exc}", exc_info=True)
            msg["body"] = t("room.encrypted_error", exc=exc)
            msg["decryption_error"] = True
            return msg

    def _on_ws_message(payload: dict) -> None:
        print(f"[WS] Received raw payload: {payload}") # Log raw payload

        msg_type = payload.get("type")

        # Handle encrypted_message delivered directly to recipient via user-level WS
        if msg_type == "encrypted_message":
            raw = payload.get("payload", payload)
            # Normalise field names to match the standard message format
            msg: dict = {
                "id": raw.get("message_id") or raw.get("id"),
                "room_id": raw.get("room_id"),
                "author_username": raw.get("sender_username") or raw.get("author_username"),
                "author_display_name": raw.get("author_display_name"),
                "body": "",
                "created_at": raw.get("created_at", ""),
                "files": raw.get("files", []),
                "is_encrypted": True,
                "encrypted_blob": raw.get("encrypted_blob"),
                "sender_encrypted_blob": raw.get("sender_encrypted_blob"),
                "signature": raw.get("signature"),
            }
            # Only display if this message belongs to the currently open room
            if msg["room_id"] != room.id:
                return

            async def decrypt_and_display_encrypted():
                decrypted_msg = await _decrypt_message_if_needed(msg)
                _state["messages_data"].append(decrypted_msg)
                message_control = _build_message_tile(decrypted_msg)
                messages_list.controls.append(message_control)
                reconnecting_banner.visible = False
                _animate_message(message_control)
                page.update()
                if _is_user_at_bottom():
                    page.run_task(_smooth_scroll_to_bottom)

            page.run_task(decrypt_and_display_encrypted)
            return

        if msg_type == "message":
            msg = payload.get("payload", payload)
            print(f"[WS] Processed message payload: {msg}") # Log processed message
            print(f"[WS] Files section in message: {msg.get('files', [])}") # Log files section

            # Decrypt message if encrypted
            if msg.get("is_encrypted"):
                print("[WS] Message is encrypted, decrypting...")
                # Run decryption in async task
                async def decrypt_and_display():
                    decrypted_msg = await _decrypt_message_if_needed(msg)
                    
                    # Check if this is our own message (optimistic update already shown)
                    is_own_message = (
                        state.current_user is not None
                        and decrypted_msg.get("author_username") == state.current_user.username
                    )
                    
                    # Check if we already have this message (by temporary ID or real ID)
                    msg_id = decrypted_msg.get("id")
                    temp_id = decrypted_msg.get("temp_id")
                    already_exists = False
                    
                    if is_own_message:
                        # Look for temporary message with matching temp_id or body
                        for i, existing_msg in enumerate(_state["messages_data"]):
                            if existing_msg.get("temp_id") == temp_id or existing_msg.get("is_optimistic"):
                                # Keep the original body from the optimistic message (encrypted
                                # outgoing messages can't be decrypted by the sender)
                                if decrypted_msg.get("is_encrypted"):
                                    decrypted_msg["body"] = existing_msg.get("body", decrypted_msg.get("body", ""))
                                # Replace optimistic message with real one
                                _state["messages_data"][i] = decrypted_msg
                                messages_list.controls[i] = _build_message_tile(decrypted_msg)
                                already_exists = True
                                print("[WS] Replaced optimistic message with real one")
                                break
                    
                    if not already_exists:
                        user_at_bottom = _is_user_at_bottom()
                        print(f"[WS] User at bottom: {user_at_bottom}")

                        _state["messages_data"].append(decrypted_msg)
                        message_control = _build_message_tile(decrypted_msg)
                        messages_list.controls.append(message_control)
                        print(f"[WS] Added message to list, total messages: {len(messages_list.controls)}")
                        
                        reconnecting_banner.visible = False
                        _animate_message(message_control)
                        print("[WS] Animated message")
                    
                    page.update()
                    print("[WS] Updated page")
                    
                    # Only scroll to bottom if user was already at bottom
                    if not already_exists:
                        user_at_bottom = _is_user_at_bottom()
                        if user_at_bottom:
                            print("[WS] Scrolling to bottom...")
                            page.run_task(_smooth_scroll_to_bottom)
                        else:
                            print("[WS] Not scrolling - user not at bottom")
                
                page.run_task(decrypt_and_display)
                return

            # Check if this is our own message (optimistic update already shown)
            is_own_message = (
                state.current_user is not None
                and msg.get("author_username") == state.current_user.username
            )
            
            # Check if we already have this message (by temporary ID or real ID)
            msg_id = msg.get("id")
            temp_id = msg.get("temp_id")
            already_exists = False
            
            if is_own_message:
                # Look for temporary message with matching temp_id or body
                for i, existing_msg in enumerate(_state["messages_data"]):
                    if existing_msg.get("temp_id") == temp_id or (
                        existing_msg.get("is_optimistic") and 
                        existing_msg.get("body") == msg.get("body")
                    ):
                        # Replace optimistic message with real one
                        _state["messages_data"][i] = msg
                        messages_list.controls[i] = _build_message_tile(msg)
                        already_exists = True
                        print("[WS] Replaced optimistic message with real one")
                        break
            
            if not already_exists:
                user_at_bottom = _is_user_at_bottom()
                print(f"[WS] User at bottom: {user_at_bottom}")

                _state["messages_data"].append(msg)
                message_control = _build_message_tile(msg)
                messages_list.controls.append(message_control)
                print(f"[WS] Added message to list, total messages: {len(messages_list.controls)}")
                
                reconnecting_banner.visible = False
                _animate_message(message_control)
                print("[WS] Animated message")
            
            page.update()
            print("[WS] Updated page")
            
            # Only scroll to bottom if user was already at bottom
            if not already_exists:
                user_at_bottom = _is_user_at_bottom()
                if user_at_bottom:
                    print("[WS] Scrolling to bottom...")
                    page.run_task(_smooth_scroll_to_bottom)
                else:
                    print("[WS] Not scrolling - user not at bottom")

    def _on_reconnecting(delay: float) -> None:
        reconnecting_banner.visible = True
        page.update()

    async def _load_messages(before_id: int | None = None) -> list[dict]:
        client = APIClient(base_url=API_URL, state=state)
        try:
            return await client.get_messages(
                room.id, before_id=before_id, limit=50
            )
        except AuthError:
            state.token = None
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room.session_expired"), color="#ffffff"), open=True, bgcolor="#ea4335"
            )
            page.update()
            from views.login_view import login_view

            login_view(page, state)
            return []
        except Exception as exc:
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()
            return []
        finally:
            await client.aclose()

    async def _initial_load() -> None:
        print("[INIT] Starting initial message load...")

        # Auto-join public rooms if not already a member
        if room.room_type == "public":
            client = APIClient(base_url=API_URL, state=state)
            try:
                updated = await client.join_room(room.id)
                # Sync member count in case it changed
                room.member_count = updated.get("member_count", room.member_count)
            except Exception as exc:
                print(f"[INIT] Auto-join failed: {exc}")
            finally:
                await client.aclose()

        msgs = await _load_messages()
        msgs_sorted = sorted(msgs, key=lambda m: m["id"])
        print(f"[INIT] Loaded {len(msgs_sorted)} messages")
        
        # Decrypt encrypted messages
        decrypted_msgs = []
        for m in msgs_sorted:
            if m.get("is_encrypted"):
                print(f"[INIT] Decrypting message {m.get('id')}")
                decrypted_msg = await _decrypt_message_if_needed(m)
                decrypted_msgs.append(decrypted_msg)
            else:
                decrypted_msgs.append(m)
        
        if decrypted_msgs:
            _state["min_id"] = decrypted_msgs[0]["id"]
            _state["messages_data"] = decrypted_msgs
            for m in decrypted_msgs:
                messages_list.controls.append(_build_message_tile(m))
            print(f"[INIT] Added {len(decrypted_msgs)} messages to UI")
        
        page.update()
        print("[INIT] Updated page, now scrolling to bottom...")
        
        # Ensure user is marked as at bottom for initial load
        _state["user_at_bottom"] = True
        await _smooth_scroll_to_bottom()
        print("[INIT] Initial load complete")

    async def _load_older() -> None:
        if _state["loading_older"] or _state["min_id"] is None:
            return
        _state["loading_older"] = True
        msgs = await _load_messages(before_id=_state["min_id"])
        if msgs:
            msgs_sorted = sorted(msgs, key=lambda m: m["id"])
            
            # Decrypt encrypted messages
            decrypted_msgs = []
            for m in msgs_sorted:
                if m.get("is_encrypted"):
                    print(f"[LOAD_OLDER] Decrypting message {m.get('id')}")
                    decrypted_msg = await _decrypt_message_if_needed(m)
                    decrypted_msgs.append(decrypted_msg)
                else:
                    decrypted_msgs.append(m)
            
            _state["min_id"] = decrypted_msgs[0]["id"]
            new_tiles = [_build_message_tile(m) for m in decrypted_msgs]
            # Insert older messages at the top (data too)
            _state["messages_data"] = decrypted_msgs + _state["messages_data"]
            messages_list.controls = new_tiles + messages_list.controls
            page.update()
            # Scroll to the first of the previously visible messages to keep reading position
            if new_tiles:
                await messages_list.scroll_to(
                    scroll_key=new_tiles[-1],
                    duration=0,
                )
        _state["loading_older"] = False
        _state["loading_older"] = False

    async def _send_message() -> None:
        body = (message_input.value or "").strip()

        if not body and attached_files:
            body = "📎"

        print(f"[SEND] Attempting to send message: '{body}'")
        if not body and not attached_files:
            print("[SEND] Empty message, aborting")
            return
        ws: WsClient | None = _state.get("ws_client")
        if ws is None:
            print("[SEND] No WebSocket client available")
            return
        try:
            # Mark user as "at bottom" when sending a message
            print("[SEND] Setting user_at_bottom = True")
            _state["user_at_bottom"] = True
            
            # Resolve emoji shortcodes before sending
            resolved_body = resolve_shortcodes(body)
            
            # Create optimistic message for immediate display
            import time
            temp_id = f"temp_{int(time.time() * 1000)}"
            optimistic_msg = {
                "id": None,
                "temp_id": temp_id,
                "body": resolved_body,
                "files": [],
                "author_username": state.current_user.username if state.current_user else "?",
                "author_display_name": state.current_user.display_name if state.current_user else None,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "is_optimistic": True,
            }
            
            # Add optimistic message to UI immediately
            _state["messages_data"].append(optimistic_msg)
            message_control = _build_message_tile(optimistic_msg)
            messages_list.controls.append(message_control)
            _animate_message(message_control)
            
            # Clear input and update UI
            message_input.value = ""
            print("[SEND] Cleared input field and added optimistic message")
            page.update()
            
            # Scroll to bottom
            page.run_task(_smooth_scroll_to_bottom)
            
            # Send message via WebSocket or encrypted API
            print("[SEND] Sending message...")
            client = APIClient(base_url=API_URL, state=state)

            try:
                # Upload files first
                uploaded_files = []
                is_personal = room.room_type == "personal"

                for f in attached_files:
                    # On Android f.path is None — use f.bytes instead
                    if f.path:
                        with open(f.path, "rb") as fh:
                            file_bytes = fh.read()
                    elif f.bytes:
                        file_bytes = f.bytes
                    else:
                        continue

                    # Encrypt file for personal E2EE chats
                    key_blob = None
                    key_sender_blob = None
                    key_signature = None

                    if is_personal and state.ed25519_private and state.x25519_private:
                        parts = room.name.split(", ")
                        _recipient = next((p for p in parts if p != state.current_user.username), None)
                        if _recipient:
                            try:
                                import base64
                                from crypto.file_crypto import FileEncryptor
                                from crypto.key_generator import KeyGenerator

                                r_keys = None
                                if state.public_key_cache:
                                    r_keys = state.public_key_cache.get_public_keys(_recipient)
                                if not r_keys:
                                    _kc = APIClient(base_url=API_URL, state=state)
                                    try:
                                        kd = await _kc.get_public_keys(_recipient)
                                        r_x25519_pub = KeyGenerator.load_x25519_public_key(base64.b64decode(kd["identity_pub_x25519"]))
                                        r_ed25519_pub = KeyGenerator.load_ed25519_public_key(base64.b64decode(kd["identity_pub_ed25519"]))
                                        r_keys = {"x25519_pub": r_x25519_pub, "ed25519_pub": r_ed25519_pub, "user_id": kd.get("user_id", "")}
                                        if state.public_key_cache:
                                            state.public_key_cache.set_public_keys(_recipient, r_ed25519_pub, r_x25519_pub, str(kd.get("user_id", "")))
                                    finally:
                                        await _kc.aclose()

                                enc = FileEncryptor()
                                result = enc.encrypt_file(
                                    plaintext=file_bytes,
                                    filename=f.name,
                                    recipient_x25519_pub=r_keys["x25519_pub"],
                                    sender_ed25519_priv=state.ed25519_private,
                                    sender_x25519_pub=state.x25519_private.public_key(),
                                    sender_id=str(state.current_user.id),
                                    recipient_id=str(r_keys.get("user_id", "")),
                                )
                                file_bytes = result["ciphertext"]
                                key_blob = result["key_blob"]
                                key_sender_blob = result["key_sender_blob"]
                                key_signature = result["signature"]
                            except Exception as enc_exc:
                                import logging
                                logging.error(f"[FILE] Encryption failed: {enc_exc}", exc_info=True)

                    async with httpx.AsyncClient() as http:
                        data = {}
                        if key_blob:
                            data["key_blob"] = key_blob
                            data["key_sender_blob"] = key_sender_blob
                            data["key_signature"] = key_signature
                        response = await http.post(
                            f"{API_URL}/rooms/{room.id}/files",
                            headers=client._headers(),
                            files={"file": (f.name, file_bytes)},
                            data=data or None,
                        )
                        response.raise_for_status()
                        uploaded_files.append(response.json())

                # Check if this is a personal chat and we should encrypt
                should_encrypt = False
                recipient_username = None
                
                if is_personal and state.ed25519_private and state.x25519_private:
                    # Extract recipient username from room name
                    # Personal chat names are formatted as "user1, user2"
                    parts = room.name.split(", ")
                    recipient_username = next((p for p in parts if p != state.current_user.username), None)
                    
                    if recipient_username:
                        print(f"[SEND] Personal chat detected, attempting E2EE with {recipient_username}")
                        should_encrypt = True
                
                if should_encrypt and recipient_username:
                    try:
                        import base64
                        import logging
                        from crypto.message_crypto import MessageEncryptor
                        from crypto.key_generator import KeyGenerator
                        
                        # Fetch recipient public keys
                        recipient_keys = None
                        keys_data = None
                        if state.public_key_cache:
                            recipient_keys = state.public_key_cache.get_public_keys(recipient_username)
                        
                        if not recipient_keys:
                            logging.info(f"[SEND] Fetching public keys for {recipient_username}")
                            keys_data = await client.get_public_keys(recipient_username)
                            ed25519_pub_bytes = base64.b64decode(keys_data["identity_pub_ed25519"])
                            x25519_pub_bytes = base64.b64decode(keys_data["identity_pub_x25519"])
                            
                            ed25519_pub = KeyGenerator.load_ed25519_public_key(ed25519_pub_bytes)
                            x25519_pub = KeyGenerator.load_x25519_public_key(x25519_pub_bytes)
                            
                            recipient_keys = {"ed25519_pub": ed25519_pub, "x25519_pub": x25519_pub, "user_id": keys_data.get("user_id", "")}
                            if state.public_key_cache:
                                state.public_key_cache.set_public_keys(recipient_username, ed25519_pub, x25519_pub, str(keys_data.get("user_id", "")))
                        
                        recipient_id = str(recipient_keys.get("user_id", "") if isinstance(recipient_keys, dict) else "")
                        
                        # Encrypt message
                        logging.info(f"[SEND] Encrypting message for {recipient_username}")
                        encryptor = MessageEncryptor()
                        encrypted_data = encryptor.encrypt_message(
                            plaintext=resolved_body,
                            recipient_x25519_pub=recipient_keys["x25519_pub"],
                            sender_ed25519_priv=state.ed25519_private,
                            sender_x25519_pub=state.x25519_private.public_key(),
                            sender_id=str(state.current_user.id),
                            recipient_id=recipient_id
                        )
                        
                        # Send encrypted message via API
                        logging.info("[SEND] Sending encrypted message via API")
                        await client.send_encrypted_message(
                            room_id=room.id,
                            recipient_username=recipient_username,
                            encrypted_blob_b64=encrypted_data["blob"],
                            sender_encrypted_blob_b64=encrypted_data["sender_blob"],
                            signature_b64=encrypted_data["signature"],
                            file_ids=[f["id"] for f in uploaded_files if f.get("id")],
                        )
                        logging.info("[SEND] Encrypted message sent successfully")
                    except Exception as enc_exc:
                        logging.error(f"[SEND] Encryption failed: {enc_exc}", exc_info=True)
                        print(f"[SEND] Encryption failed, falling back to plaintext: {enc_exc}")
                        # Fall back to plaintext WebSocket
                        await ws.send_message(room.id, resolved_body, files=uploaded_files)
                else:
                    # Send plaintext via WebSocket (group chat or no keys)
                    print("[SEND] Sending plaintext message via WebSocket")
                    await ws.send_message(room.id, resolved_body, files=uploaded_files)

                # re-render
                if attached_files:
                    _state["messages_data"][-1]["files"] = uploaded_files

                    messages_list.controls[-1] = _build_message_tile(
                        _state["messages_data"][-1]
                    )
                    page.update()

                # Clear attached files after sending
                attached_files.clear()

            finally:
                await client.aclose()
            print("[SEND] Message sent")
        except Exception as exc:
            print(f"[SEND] Error sending message: {exc}")
            page.snack_bar = flet.SnackBar(flet.Text(str(exc), color="#ffffff"), open=True, bgcolor="#ea4335")
            page.update()

    def _on_scroll(e: flet.OnScrollEvent) -> None:
        # Track if user is at bottom (within 100px threshold)
        if e.pixels is not None and e.max_scroll_extent is not None:
            distance_from_bottom = e.max_scroll_extent - e.pixels
            was_at_bottom = _state.get("user_at_bottom", True)
            is_at_bottom = distance_from_bottom < 100
            
            if was_at_bottom != is_at_bottom:
                print(f"[SCROLL] User position changed: at_bottom={is_at_bottom} (distance={distance_from_bottom:.1f}px)")
            
            _state["user_at_bottom"] = is_at_bottom
            
            # Load older messages when scrolled to top
            if e.pixels <= 50:
                print(f"[SCROLL] Near top (pixels={e.pixels}), loading older messages...")
                page.run_task(_load_older)

    messages_list.on_scroll = _on_scroll

    def _rebuild_messages(_alignment: str) -> None:
        """Rebuild all message tiles when alignment setting changes."""
        messages_list.controls.clear()
        for m in _state.get("messages_data", []):
            messages_list.controls.append(_build_message_tile(m))
        page.update()

    state.on_alignment_change = _rebuild_messages

    async def _start_ws() -> None:
        if state.ws is not None:
            # Reuse existing connection — just update callbacks and room subscription
            state.ws._on_room_message = _on_ws_message
            state.ws._on_reconnecting = _on_reconnecting
            state.ws.set_room(room.id)
            _state["ws_client"] = state.ws
            logger.debug("[room_view] Reusing existing WS, switched to room %s", room.id)
            return

        # No existing connection — create a new unified client
        ws = UnifiedWsClient(
            token=state.token or "",
            on_room_message=_on_ws_message,
            on_reconnecting=_on_reconnecting,
        )
        ws.set_room(room.id)
        _state["ws_client"] = ws
        state.ws = ws
        await ws.connect()

    def _go_back(e: flet.ControlEvent) -> None:
        # Clear room-specific callbacks but keep the connection alive for notifications
        if state.ws is not None:
            state.ws._on_room_message = None
            state.ws._on_reconnecting = None
            state.ws.set_room(None)
        state.on_alignment_change = None
        _state["ws_client"] = None
        state.active_room = None
        from views.chat_list_view import chat_list_view
        chat_list_view(page, state)

    def _go_settings(e: flet.ControlEvent) -> None:
        from views.room_settings_view import room_settings_view

        room_settings_view(page, state)

    # Диалог приглашения (только для групп)
    invite_username_field = flet.TextField(
        label=t("room.invite_username"), autofocus=True
    )
    invite_error = flet.Text("", color="#ea4335", visible=False, size=12)

    async def _do_invite(e: flet.ControlEvent) -> None:
        invite_error.visible = False
        page.update()
        username = (invite_username_field.value or "").strip()
        if not username:
            return
        client = APIClient(base_url=API_URL, state=state)
        try:
            await client.invite_user(room.id, username)
            invite_dialog.open = False
            invite_username_field.value = ""
            page.snack_bar = flet.SnackBar(
                flet.Text(t("room.invite_success", username=username), color="#ffffff"), 
                open=True, 
                bgcolor="#008069"
            )
            page.update()
        except Exception as exc:
            invite_error.value = str(exc)
            invite_error.visible = True
            page.update()
        finally:
            await client.aclose()

    invite_dialog = flet.AlertDialog(
        title=flet.Text(t("room.invite_user"), weight=flet.FontWeight.BOLD, color="#111b21"),
        content=flet.Column(controls=[invite_username_field, invite_error], tight=True, spacing=8),
        actions=[
            flet.TextButton(t("room.cancel"), on_click=lambda e: _close_invite_dialog(), style=flet.ButtonStyle(color="#008069")),
            flet.ElevatedButton(t("room.invite"), on_click=_do_invite, style=flet.ButtonStyle(bgcolor="#008069", color="#ffffff")),
        ],
    )

    def _close_invite_dialog() -> None:
        invite_dialog.open = False
        page.update()

    def _open_invite_dialog(e: flet.ControlEvent) -> None:
        invite_username_field.value = ""
        invite_error.visible = False
        invite_dialog.open = True
        page.update()

    page.overlay.append(invite_dialog)

    is_owner = (
        state.current_user is not None
        and room.owner_username == state.current_user.username
    )
    is_personal = room.room_type == "personal"
    can_invite = (is_owner or room.allow_member_invite) and not is_personal

    # Получить отображаемое имя чата
    def _get_display_name() -> str:
        if is_personal:
            # Для личных чатов показываем имя собеседника
            name = room.name
            if state.current_user and state.current_user.username in name:
                parts = name.split(", ")
                return next((p for p in parts if p != state.current_user.username), name)
            return name
        return room.name

    display_name = _get_display_name()
    
    # Подзаголовок в зависимости от типа чата
    def _get_subtitle() -> str:
        if is_personal:
            return t("room.personal_chat")
        elif room.room_type == "group":
            return t("room.group_subtitle", count=room.member_count)
        else:
            return t("room.public_subtitle", count=room.member_count)

    subtitle = _get_subtitle()

    top_bar_controls: list[flet.Control] = [
        flet.IconButton(
            icon=flet.Icons.ARROW_BACK,
            on_click=_go_back,
            tooltip=t("room.back"),
            icon_color="#ffffff",
        ),
        flet.Column(
            controls=[
                flet.Text(
                    display_name,
                    size=18,
                    weight=flet.FontWeight.BOLD,
                    color="#ffffff",
                ),
                flet.Text(
                    subtitle,
                    size=13,
                    color="#d1d7db",
                ),
            ],
            spacing=0,
            tight=True,
            expand=True,
        ),
    ]
    if can_invite:
        top_bar_controls.append(
            flet.IconButton(
                icon=flet.Icons.PERSON_ADD,
                on_click=_open_invite_dialog,
                tooltip=t("room.invite_user"),
                icon_color="#ffffff",
            )
        )
    if is_owner:
        top_bar_controls.append(
            flet.IconButton(
                icon=flet.Icons.SETTINGS,
                on_click=_go_settings,
                tooltip=t("room.room_settings"),
                icon_color="#ffffff",
            )
        )

    top_bar = flet.Container(
        content=flet.Row(
            controls=top_bar_controls,
            vertical_alignment=flet.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#008069",
        padding=flet.padding.symmetric(horizontal=8, vertical=8),
    )

    # Create formatting toolbar
    print("[room_view] creating FormattingToolbar...")
    formatting_toolbar = FormattingToolbar(
        get_value=lambda: message_input.value or "",
        set_value=lambda v: setattr(message_input, 'value', v),  # No need for page.update()
        get_cursor=lambda: None,  # Flet TextField doesn't expose cursor_position
        text_field=message_input,  # Pass TextField reference for selection support
        disabled=False,  # For now, use False since there's no read-only state
    )
    print("[room_view] FormattingToolbar ok")

    page.controls.clear()
    print("[room_view] controls cleared, building UI...")
    page.add(
        flet.Column(
            controls=[
                top_bar,
                reconnecting_banner,
                flet.Container(
                    content=messages_list,
                    bgcolor="#efeae2",
                    expand=True,
                    padding=flet.padding.symmetric(horizontal=8, vertical=8),
                ),
                flet.Container(
                    content=flet.Column(
                        controls=[
                            formatting_toolbar,
                            attached_preview,
                            flet.Row(
                                controls=[
                                    flet.IconButton(
                                        icon=flet.Icons.EMOJI_EMOTIONS,
                                        on_click=_toggle_emoji_picker,
                                        icon_color="#008069",
                                        tooltip=t("room.emoji_picker"),
                                        icon_size=24,
                                    ),
                                    flet.IconButton(
                                icon=flet.Icons.ATTACH_FILE,
                                on_click=pick_file,
                                icon_color="#008069",
                                tooltip="Attach file",
                            ),
                            message_input,
                                    flet.IconButton(
                                        icon=flet.Icons.SEND,
                                        on_click=lambda e: page.run_task(_send_message),
                                        icon_color="#008069",
                                        tooltip=t("room.send"),
                                        icon_size=24,
                                    ),
                                ],
                                vertical_alignment=flet.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor="#f0f2f5",
                    padding=flet.padding.symmetric(horizontal=12, vertical=8),
                ),
            ],
            expand=True,
            spacing=0,
        )
    )
    page.update()
    print("[room_view] page.update() done, starting tasks...")
    page.run_task(_initial_load)
    page.run_task(_start_ws)