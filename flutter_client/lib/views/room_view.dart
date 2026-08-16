import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import '../api/api_client.dart';
import '../api/ws_client.dart';
import '../config.dart';
import '../crypto/e2ee.dart';
import '../crypto/file_crypto.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';
import 'room_settings_view.dart';

class RoomView extends StatefulWidget {
  const RoomView({super.key, required this.state, required this.room});
  final AppState state;
  final RoomDTO room;

  @override
  State<RoomView> createState() => _RoomViewState();
}

class _RoomViewState extends State<RoomView> {
  late final AppState _state = widget.state;
  late final RoomDTO _room = widget.room;

  final _inputCtrl = TextEditingController();
  final List<Map<String, dynamic>> _messages = [];
  final List<MapEntry<File, String>> _attachments = [];
  final ScrollController _scrollCtrl = ScrollController();

  UnifiedWsClient? _ws;
  bool _reconnecting = false;
  bool _loading = true;
  bool _atBottom = true;
  bool _sending = false;
  bool _canInvite = false;
  bool _isOwner = false;

  final _inviteCtrl = TextEditingController();
  String? _inviteError;

  @override
  void initState() {
    super.initState();
    _isOwner = _state.currentUser != null &&
        _room.ownerUsername == _state.currentUser!.username;
    _canInvite = (_isOwner || _room.allowMemberInvite) &&
        _room.roomType != 'personal';
    _scrollCtrl.addListener(_onScroll);
    _loadHistory();
    _startWs();
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    _inviteCtrl.dispose();
    _scrollCtrl.dispose();
    _ws?.onRoomMessage = null;
    _ws?.onNotification = null;
    _ws?.onReconnecting = null;
    _ws?.setRoom(null);
    super.dispose();
  }

  void _onScroll() {
    if (!_scrollCtrl.hasClients) return;
    final dist = _scrollCtrl.position.maxScrollExtent - _scrollCtrl.offset;
    final atBottom = dist < 100;
    if (atBottom != _atBottom) _atBottom = atBottom;
  }

  String _getSubtitle() {
    if (_room.roomType == 'personal') return L10n.t('room.personal_chat');
    if (_room.roomType == 'group') {
      return L10n.t('room.group_subtitle', {'count': _room.memberCount});
    }
    return L10n.t('room.public_subtitle', {'count': _room.memberCount});
  }

  String _getDisplayName() {
    if (_room.roomType == 'personal') {
      final my = _state.currentUser?.username ?? '';
      final counterpart = _room.participants
          .where((p) => p.split('@').first != my)
          .firstOrNull;
      if (counterpart != null) return counterpart;
      final parts = _room.name.split(', ');
      return parts.where((p) => p != my).firstOrNull ?? _room.name;
    }
    return _room.name;
  }

  Future<void> _loadHistory() async {
    final client = ApiClient(state: _state);
    try {
      final data = await client.getMessages(_room.id);
      if (!mounted) return;
      final items = data.whereType<Map<String, dynamic>>().toList();
      setState(() => _loading = false);
      for (final m in items.reversed) {
        await _decryptInto(m);
      }
      _scrollToBottom(animate: false);
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      showSnack(context, e.toString(), ok: false);
    }
  }

  Future<void> _decryptInto(Map<String, dynamic> msg) async {
    final body = await E2EE.decryptIncoming(_state, msg, _room.id);
    if (!mounted) return;
    setState(() {
      _messages.add({...msg, 'body': body});
    });
  }

  void _startWs() {
    final existing = _state.ws;
    if (existing != null && existing.roomId == _room.id) {
      existing.onRoomMessage = _onRoomMessage;
      existing.onNotification = _onNotification;
      existing.onReconnecting = _onReconnecting;
      existing.setRoom(_room.id);
      _ws = existing;
      return;
    }
    // Server subscribes socket to a room from the room_id query param at
    // connect time — switching rooms must re-establish the socket.
    if (existing != null) {
      existing.onRoomMessage = null;
      existing.onNotification = null;
      existing.onReconnecting = null;
      existing.close();
      _state.ws = null;
    }
    final ws = UnifiedWsClient(
      token: _state.token ?? '',
      onRoomMessage: _onRoomMessage,
      onNotification: _onNotification,
      onReconnecting: _onReconnecting,
      wsUrl: _state.wsUrl,
    );
    ws.setRoom(_room.id);
    _state.ws = ws;
    _ws = ws;
    ws.connect(_state.wsUrl).catchError((_) {});
  }

  void _onReconnecting(double delay) {
    if (mounted) setState(() => _reconnecting = true);
  }

  void _onNotification(Map<String, dynamic> payload) {
    final type = payload['type'];
    if (type == 'member_joined' ||
        type == 'member_left' ||
        type == 'member_removed') {
      final evt = payload['payload'] as Map? ?? {};
      if (evt['room_id'] != _room.id) return;
      _refreshRoster();
    }
  }

  Future<void> _refreshRoster() async {
    try {
      final data = await ApiClient(state: _state).getRoom(_room.id);
      if (!mounted) return;
      final participants =
          (data['participants'] as List? ?? []).map((e) => e.toString()).toList();
      setState(() {
        _room.participants.clear();
        _room.participants.addAll(participants);
      });
    } catch (_) {}
  }

  Future<void> _onRoomMessage(Map<String, dynamic> payload) async {
    if (payload['type'] == 'encrypted_message') {
      final raw = payload['payload'] is Map
          ? payload['payload'] as Map<String, dynamic>
          : payload;
      final msg = <String, dynamic>{
        'id': raw['message_id'] ?? raw['id'],
        'room_id': raw['room_id'],
        'author_username': raw['sender_username'] ?? raw['author_username'],
        'author_display_name': raw['author_display_name'],
        'body': '',
        'created_at': raw['created_at'] ?? '',
        'files': raw['files'] ?? [],
        'is_encrypted': true,
        'encrypted_blob': raw['encrypted_blob'],
        'sender_encrypted_blob': raw['sender_encrypted_blob'],
        'signature': raw['signature'],
      };
      if (msg['room_id'] != _room.id) return;
      // If it's our own optimistic message, replace rather than append.
      final isOwn = _state.currentUser != null &&
          msg['author_username'] == _state.currentUser!.username;
      await _decryptInto(msg);
      if (!mounted) return;
      if (isOwn) {
        // Remove duplicate optimistic entry if any
        final idx = _messages.indexWhere((m) =>
            m['is_optimistic'] == true &&
            m['body'] == msg['body']);
        if (idx >= 0) setState(() => _messages.removeAt(idx));
      }
      _scrollToBottom();
    } else if (payload['type'] == 'message') {
      final msg = Map<String, dynamic>.from(payload);
      if (msg['room_id'] != _room.id) return;
      final body = msg['body'] as String? ?? '';
      if (!mounted) return;
      setState(() => _messages.add({...msg, 'body': body, 'decrypted': true}));
      _scrollToBottom();
    }
  }

  void _scrollToBottom({bool animate = true}) {
    if (!mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollCtrl.hasClients) return;
      if (animate) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      } else {
        _scrollCtrl.jumpTo(_scrollCtrl.position.maxScrollExtent);
      }
    });
  }

  // ---- Sending ----

  Future<void> _pickFiles() async {
    final result = await FilePicker.platform.pickFiles(allowMultiple: true);
    if (result == null || result.files.isEmpty) return;
    const maxSize = 100 * 1024 * 1024; // 100 MB
    final newAttachments = <MapEntry<File, String>>[];
    final oversized = <String>[];
    for (final f in result.files) {
      if (f.path == null) continue;
      final file = File(f.path!);
      final size = await file.length();
      if (size > maxSize) {
        oversized.add(f.name);
      } else {
        newAttachments.add(MapEntry(file, f.name));
      }
    }
    if (!mounted) return;
    setState(() => _attachments.addAll(newAttachments));
    if (oversized.isNotEmpty) {
      showSnack(context, 'File(s) exceed 100 MB: ${oversized.join(', ')}',
          ok: false);
    }
  }

  Future<File> _tempFile(String suffix) async {
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/tlc_${DateTime.now().millisecondsSinceEpoch}_$suffix';
    return File(path);
  }

  String? _resolveCounterpart() {
    final my = _state.currentUser?.username ?? '';
    final p = _room.participants
        .where((x) => x.split('@').first != my)
        .firstOrNull;
    if (p != null) return p;
    final parts = _room.name.split(', ');
    return parts.where((x) => x != my).firstOrNull;
  }

  Future<void> _send() async {
    final rawBody = _inputCtrl.text.trim();
    if (rawBody.isEmpty && _attachments.isEmpty) return;
    if (_state.ws == null || _ws == null) return;

    final body = rawBody.isEmpty ? '📎' : rawBody;

    final optimistic = <String, dynamic>{
      'temp_id': 'temp_${DateTime.now().millisecondsSinceEpoch}',
      'body': body,
      'files': <dynamic>[],
      'author_username': _state.currentUser?.username ?? '?',
      'author_display_name': _state.currentUser?.displayName,
      'created_at': DateTime.now().toIso8601String(),
      'is_optimistic': true,
      'is_encrypted': false,
    };

    setState(() {
      _messages.add(optimistic);
      _inputCtrl.clear();
      _atBottom = true;
    });
    _scrollToBottom();

    final client = ApiClient(state: _state);
    try {
      final isPersonal = _room.roomType == 'personal';
      final isGroup = _room.roomType == 'group' || _room.roomType == 'public';
      final hasE2ee = _state.hasE2ee;

      final uploadedFiles = <Map<String, dynamic>>[];
      final groupFileKeys = <Uint8List?>[];

      final e2eeRecipientUsername = isPersonal && hasE2ee
          ? _resolveCounterpart()
          : null;

      for (final att in _attachments) {
        var uploadPath = att.key;
        File? tmp;
        String? keyBlob;
        String? keySenderBlob;
        String? keySignature;
        var groupKey = null as Uint8List?;

        try {
          if (isGroup && hasE2ee) {
            tmp = await _tempFile('group.enc');
            groupKey =
                await FileEncryptor.encryptFileGroupStreaming(src: att.key, dst: tmp);
            uploadPath = tmp;
          } else if (e2eeRecipientUsername != null && hasE2ee) {
            tmp = await _tempFile('personal.enc');
            final keys = await E2EE.senderKeys(_state, e2eeRecipientUsername);
            final meta = await FileEncryptor.encryptFileStreaming(
              src: att.key,
              dst: tmp,
              filename: att.value,
              recipientX25519Pub: keys.x25519Pub,
              senderEd25519Priv: _state.crypto!.ed25519Private,
              senderEd25519Pub: _state.crypto!.ed25519Public,
              senderId: _state.currentUser!.id.toString(),
              recipientId: keys.userId ?? '',
            );
            keyBlob = meta['key_blob'];
            keySenderBlob = meta['key_sender_blob'];
            keySignature = meta['signature'];
            uploadPath = tmp;
          }
          groupFileKeys.add(groupKey);

          final meta2 = await client.uploadFile(
            _room.id,
            uploadPath,
            filename: att.value,
            keyBlob: keyBlob,
            keySenderBlob: keySenderBlob,
            keySignature: keySignature,
          );
          uploadedFiles.add(meta2);
        } catch (e) {
          // fall back to plaintext upload
          groupFileKeys.add(null);
          final meta2 =
              await client.uploadFile(_room.id, att.key, filename: att.value);
          uploadedFiles.add(meta2);
        } finally {
          if (tmp != null && await tmp.exists()) await tmp.delete();
        }
      }

      if (isGroup && hasE2ee) {
        final payload = await E2EE.encryptGroup(
          state: _state,
          roomId: _room.id,
          plaintext: body,
          participants: _room.participants,
          uploadedFiles: uploadedFiles,
          groupFileKeys: groupFileKeys,
        );
        await client.sendGroupEncryptedMessage(
          roomId: _room.id,
          encryptedBlobB64: payload['encrypted_blob'] as String,
          senderEncryptedBlobB64: payload['sender_encrypted_blob'] as String,
          signatureB64: payload['signature'] as String,
          fileIds: (payload['file_ids'] as List).cast<int>(),
        );
      } else if (e2eeRecipientUsername != null && hasE2ee) {
        final keys = await E2EE.senderKeys(_state, e2eeRecipientUsername);
        final encrypted = await E2EE.encryptPersonal(
          state: _state,
          peerKey: e2eeRecipientUsername,
          peerX25519PubB64: base64Encode(keys.x25519Pub),
          plaintext: body,
        );
        await client.sendEncryptedMessage(
          roomId: _room.id,
          recipientUsername: e2eeRecipientUsername,
          encryptedBlobB64: encrypted['blob']!,
          senderEncryptedBlobB64: encrypted['sender_blob']!,
          signatureB64: encrypted['signature']!,
          fileIds: uploadedFiles.map((f) => f['id'] as int).toList(),
        );
      } else {
        _ws!.sendMessage(_room.id, body,
            files: uploadedFiles);
      }

      if (!mounted) return;
      setState(() {
        final idx =
            _messages.indexWhere((m) => m['is_optimistic'] == true);
        if (idx >= 0) {
          _messages[idx]['files'] = uploadedFiles;
        }
        _attachments.clear();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        final idx =
            _messages.indexWhere((m) => m['is_optimistic'] == true);
        if (idx >= 0) _messages.removeAt(idx);
      });
      showSnack(
          context,
          L10n.t('room.send_error', {'exc': e.toString()}),
          ok: false);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _invite() async {
    final username = _inviteCtrl.text.trim();
    if (username.isEmpty) return;
    setState(() => _inviteError = null);
    try {
      await ApiClient(state: _state).inviteUser(_room.id, username);
      if (!mounted) return;
      Navigator.of(context).pop();
      showSnack(context,
          L10n.t('room.invite_success', {'username': username}));
    } catch (e) {
      if (!mounted) return;
      setState(() => _inviteError = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final isPersonal = _room.roomType == 'personal';

    return Scaffold(
      backgroundColor: context.surfaceContainer,
      appBar: AppBar(
        backgroundColor: context.surface,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_getDisplayName(),
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            Text(
              _reconnecting
                  ? L10n.t('room.reconnecting')
                  : _getSubtitle(),
              style: TextStyle(fontSize: 12, color: context.onSurfaceVariant),
            ),
          ],
        ),
        actions: [
          if (!isPersonal && _canInvite)
            IconButton(
              icon: const Icon(Icons.person_add),
              tooltip: L10n.t('room.invite_user'),
              onPressed: () => _showInviteDialog(context),
            ),
          if (!isPersonal)
            IconButton(
              icon: const Icon(Icons.settings),
              tooltip: L10n.t('room.room_settings'),
              onPressed: () {
                Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => RoomSettingsView(state: _state, room: _room),
                ));
              },
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 8),
                    itemCount: _messages.length,
                    itemBuilder: (_, i) => _buildMessage(_messages[i]),
                  ),
          ),
          if (_attachments.isNotEmpty)
            SizedBox(
              height: 56,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                itemCount: _attachments.length,
                itemBuilder: (_, i) => Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: InputChip(
                    label: Text(_attachments[i].value),
                    onDeleted: () =>
                        setState(() => _attachments.removeAt(i)),
                  ),
                ),
              ),
            ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.attach_file),
                    tooltip: L10n.t('room.attach_file'),
                    onPressed: _pickFiles,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _inputCtrl,
                      minLines: 1,
                      maxLines: 4,
                      decoration: themedFieldDecoration(
                        hintText: L10n.t('room.message_hint'),
                      ),
                      onSubmitted: (_) => _send(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    icon: const Icon(Icons.send),
                    tooltip: L10n.t('room.send'),
                    onPressed: _sending ? null : _send,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessage(Map<String, dynamic> m) {
    final isOwn = _state.currentUser != null &&
        m['author_username'] == _state.currentUser!.username;
    final alignment = _state.messageAlignment == 'left'
        ? Alignment.centerLeft
        : _state.messageAlignment == 'right'
            ? Alignment.centerRight
            : (isOwn ? Alignment.centerRight : Alignment.centerLeft);

    final body = m['body'] as String? ?? '';
    final isEncryptedError = m['decryption_error'] == true;

    final files = (m['files'] as List? ?? []);
    final fileCards = files
        .map<Widget>((f) =>
            _buildFileCard(Map<String, dynamic>.from(f as Map), m, isOwn: isOwn))
        .toList();

    return Align(
      alignment: alignment,
      child: Container(
        constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.75),
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: isOwn ? context.primary : context.surface,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (!isOwn)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  m['author_display_name']?.toString() ??
                      m['author_username']?.toString() ??
                      '',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: isOwn ? context.onPrimary : context.primary,
                  ),
                ),
              ),
            Text(
              body,
              style: TextStyle(
                color: isOwn ? context.onPrimary : context.onSurface,
                fontStyle:
                    isEncryptedError ? FontStyle.italic : FontStyle.normal,
              ),
            ),
            if (fileCards.isNotEmpty) ...[
              const SizedBox(height: 6),
              ...fileCards,
            ],
            if (m['created_at'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text(
                  _formatTime(m['created_at'] as String),
                  style: TextStyle(
                    fontSize: 10,
                    color: isOwn
                        ? context.onPrimary.withValues(alpha: 0.7)
                        : context.onSurfaceVariant,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildFileCard(
      Map<String, dynamic> fileMeta, Map<String, dynamic> msg,
      {required bool isOwn}) {
    final filename = (fileMeta['filename'] as String?) ?? 'file';
    final cardColor = isOwn
        ? context.onPrimary.withValues(alpha: 0.14)
        : context.onSurface.withValues(alpha: 0.06);
    final textColor = isOwn ? context.onPrimary : context.onSurface;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: cardColor,
        borderRadius: BorderRadius.circular(12),
      ),
      margin: const EdgeInsets.only(top: 4),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.attach_file,
              size: 18, color: textColor.withValues(alpha: 0.8)),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              filename,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: textColor,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            icon: Icon(Icons.download, size: 18, color: textColor),
            visualDensity: VisualDensity.compact,
            tooltip: L10n.t('room.download'),
            onPressed: () => _downloadFile(fileMeta, msg),
          ),
        ],
      ),
    );
  }

  /// Download + (if needed) decrypt a message file, then save it locally.
  /// Mirrors the flet client's download flow and file-metadata standard.
  Future<void> _downloadFile(
      Map<String, dynamic> fileMeta, Map<String, dynamic> msg) async {
    final fileId = fileMeta['id'];
    if (fileId == null) {
      if (!mounted) return;
      showSnack(context, L10n.t('room.download_error'), ok: false);
      return;
    }
    final filename = (fileMeta['filename'] as String?) ?? 'download';
    final isEncrypted = fileMeta['is_encrypted'] == true;
    final isGroupEncrypted = fileMeta['_group_file_key_b64'] != null;
    final isOwn = _state.currentUser != null &&
        fileMeta['uploader_id'] == _state.currentUser!.id;

    try {
      List<int>? senderEd25519Pub;
      if (isEncrypted && !isOwn && !isGroupEncrypted) {
        final uploader = (fileMeta['uploader_username'] as String?) ??
            (msg['author_username'] as String?);
        if (uploader != null) {
          final keys = await E2EE.senderKeys(_state, uploader);
          senderEd25519Pub = keys.ed25519Pub;
        }
      }

      final savePath = await FilePicker.platform.saveFile(
        dialogTitle: L10n.t('room.download'),
        fileName: filename,
        type: FileType.any,
      );
      if (savePath == null) return;
      final outFile = File(savePath);
      final client = ApiClient(state: _state);

      if (isGroupEncrypted || isEncrypted) {
        final tmp = await _tempFile('download.enc');
        try {
          await client.downloadFile(_room.id, fileId as int, tmp);
          if (isGroupEncrypted) {
            await FileDecryptor.decryptFileWithKeyStreaming(
              src: tmp,
              dst: outFile,
              fileKey:
                  base64Decode(fileMeta['_group_file_key_b64'] as String),
            );
          } else if (isOwn && fileMeta['key_sender_blob'] != null) {
            await FileDecryptor.decryptOwnFileStreaming(
              src: tmp,
              dst: outFile,
              keySenderBlobB64: fileMeta['key_sender_blob'] as String,
              x25519Priv: _state.crypto!.x25519Private,
            );
          } else if (senderEd25519Pub != null &&
              fileMeta['key_blob'] != null &&
              fileMeta['key_signature'] != null) {
            await FileDecryptor.decryptFileStreaming(
              src: tmp,
              dst: outFile,
              keyBlobB64: fileMeta['key_blob'] as String,
              signatureB64: fileMeta['key_signature'] as String,
              x25519Priv: _state.crypto!.x25519Private,
              senderEd25519Pub: senderEd25519Pub,
            );
          } else {
            throw Exception('Missing decryption keys');
          }
        } finally {
          if (await tmp.exists()) await tmp.delete();
        }
      } else {
        await client.downloadFile(_room.id, fileId as int, outFile);
      }

      if (!mounted) return;
      showSnack(context, L10n.t('room.downloaded', {'name': filename}));
    } catch (e) {
      if (!mounted) return;
      showSnack(context, e.toString(), ok: false);
    }
  }

  String _formatTime(String iso) {
    try {
      final dt = DateTime.parse(iso).toLocal();
      final now = DateTime.now();
      if (dt.year == now.year &&
          dt.month == now.month &&
          dt.day == now.day) {
        return '${dt.hour.toString().padLeft(2, '0')}:'
            '${dt.minute.toString().padLeft(2, '0')}';
      }
      return '${dt.day.toString().padLeft(2, '0')}.'
          '${dt.month.toString().padLeft(2, '0')}.'
          '${dt.year}';
    } catch (_) {
      return iso;
    }
  }

  void _showInviteDialog(BuildContext context) {
    _inviteCtrl.clear();
    _inviteError = null;
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(L10n.t('room.invite_user')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _inviteCtrl,
                autofocus: true,
                decoration: themedFieldDecoration(
                    label: L10n.t('room.invite_username')),
              ),
              if (_inviteError != null)
                Text(_inviteError!,
                    style: TextStyle(
                        color: context.error, fontSize: 12)),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: Text(L10n.t('room.cancel')),
            ),
            FilledButton(
              onPressed: _invite,
              child: Text(L10n.t('room.invite')),
            ),
          ],
        ),
      ),
    );
  }
}
