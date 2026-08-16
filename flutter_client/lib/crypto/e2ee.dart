/// High-level E2EE orchestration used by the chat views. Bridges the crypto
/// modules with the API client (public-key lookup/caching, sender-key
/// distribution fetch) and applies group-payload parsing.
library;

import 'dart:convert';
import 'dart:typed_data';

import '../api/api_client.dart';
import '../crypto/key_cache.dart';
import '../crypto/keys.dart';
import '../crypto/message_crypto.dart';
import '../crypto/ratchet_facade.dart';
import '../crypto/sender_keys.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';

class E2EE {
  static Future<PublicKeyEntry> senderKeys(AppState state, String username) async {
    final cache = state.publicKeyCache;
    if (cache == null) {
      throw StateError('E2EE stores not initialized');
    }
    final existing = cache.get(username);
    if (existing != null) return existing;
    final data = await ApiClient(state: state).getPublicKeys(username);
    final ed = base64Decode(data['identity_pub_ed25519'] as String);
    final x = base64Decode(data['identity_pub_x25519'] as String);
    final entry =
        PublicKeyEntry(ed25519Pub: ed, x25519Pub: x, userId: data['user_id']?.toString());
    cache.set(username, ed, x, data['user_id']?.toString());
    return entry;
  }

  /// Encrypt a 1:1 personal message (Double Ratchet v2).
  static Future<Map<String, String>> encryptPersonal({
    required AppState state,
    required String peerKey,
    required String peerX25519PubB64,
    required String plaintext,
  }) async {
    if (!state.hasE2ee) {
      throw StateError('E2EE keys not available');
    }
    final c = state.crypto!;
    final store = state.ratchetStore!;
    final peerPub = base64Decode(peerX25519PubB64);
    final recipientId = (await senderKeys(state, peerKey)).userId ?? '';
    return RatchetEncryptor.encryptMessage(
      plaintext: plaintext,
      peerKey: peerKey,
      peerIdentityX25519Pub: peerPub,
      senderEd25519Priv: c.ed25519Private,
      senderEd25519Pub: c.ed25519Public,
      senderX25519Priv: c.x25519Private,
      senderX25519Pub: c.x25519Public,
      senderId: state.currentUser!.id.toString(),
      recipientId: recipientId,
      store: store,
    );
  }

  /// Decrypt an incoming message in place; returns the visible body.
  static Future<String> decryptIncoming(
    AppState state,
    Map<String, dynamic> msg,
    int roomId,
  ) async {
    if (msg['is_encrypted'] != true) return msg['body'] as String? ?? '';

    if (msg['id'] != null && state.messageStore != null) {
      final cached = await state.messageStore!.get(msg['id'] as int);
      if (cached != null) {
        _applyGroupPayload(msg, cached);
        return msg['body'] as String? ?? cached;
      }
    }

    final c = state.crypto;
    if (c == null) {
      msg['decryption_error'] = true;
      return L10n.t('room.encrypted_no_keys');
    }

    final senderUsername = msg['author_username'] as String?;
    if (senderUsername == null) {
      msg['decryption_error'] = true;
      return L10n.t('room.encrypted_unknown_sender');
    }

    final blob = msg['encrypted_blob'] as String?;
    final signature = msg['signature'] as String?;
    if (blob == null || signature == null) {
      msg['decryption_error'] = true;
      return L10n.t('room.encrypted_malformed');
    }

    // Own message: decrypt the sender's own copy (no signature check). The
    // sender blob is always the self-contained v1 shape, so this works for
    // v1/v2 personal and v3 group messages alike (mirrors the Python client).
    if (state.currentUser != null && senderUsername == state.currentUser!.username) {
      final senderBlob = msg['sender_encrypted_blob'] as String?;
      if (senderBlob == null) return L10n.t('room.encrypted_sent');
      try {
        final plaintext = await MessageDecryptor.decryptOwnMessage(
            senderBlob, c.x25519Private, c.x25519Public);
        _persist(state, msg, plaintext);
        return msg['body'] as String? ?? plaintext;
      } catch (_) {
        return L10n.t('room.encrypted_sent');
      }
    }

    final keys = await senderKeys(state, senderUsername);

    try {
      if (peekBlobVersion(blob) == 3) {
        final plaintext = await _decryptGroup(state, roomId, senderUsername, blob, signature, keys);
        _persist(state, msg, plaintext);
        return msg['body'] as String? ?? plaintext;
      } else if (peekBlobVersion(blob) >= 2) {
        final store = state.ratchetStore;
        if (store == null) {
          msg['decryption_error'] = true;
          return L10n.t('room.encrypted_no_keys');
        }
        final plaintext = await RatchetDecryptor.decryptMessage(
          encryptedMsg: {'blob': blob, 'signature': signature},
          peerKey: senderUsername,
          recipientX25519Priv: c.x25519Private,
          recipientX25519Pub: c.x25519Public,
          senderEd25519Pub: keys.ed25519Pub,
          senderX25519Pub: keys.x25519Pub,
          store: store,
        );
        _persist(state, msg, plaintext);
        return msg['body'] as String? ?? plaintext;
      } else {
        final plaintext = await MessageDecryptor.decryptMessage(
          {'blob': blob, 'signature': signature},
          c.x25519Private,
          c.x25519Public,
          keys.ed25519Pub,
        );
        _persist(state, msg, plaintext);
        return msg['body'] as String? ?? plaintext;
      }
    } catch (e) {
      msg['decryption_error'] = true;
      final s = e.toString();
      if (s.contains('signature')) return L10n.t('room.encrypted_bad_signature');
      if (s.contains('consumed') || s.contains('gone')) {
        return L10n.t('room.encrypted_key_gone');
      }
      return L10n.t('room.encrypted_bad_key');
    }
  }

  static Future<String> _decryptGroup(
    AppState state,
    int roomId,
    String senderUsername,
    String blob,
    String signature,
    PublicKeyEntry senderKeys,
  ) async {
    // The signature covers the canonical re-serialization of the parsed blob
    // (mirrors Python's `serialize_blob(json.loads(b64decode(blob)))`).
    final blobBytes = base64Decode(blob);
    final parsed = jsonDecode(utf8.decode(blobBytes)) as Map<String, dynamic>;
    if (!await edVerify(utf8.encode(serializeBlob(parsed)), base64Decode(signature),
        senderKeys.ed25519Pub)) {
      throw Exception('signature verification failed');
    }
    final skStore = state.senderKeyStore!;
    final gen = peekGroupGeneration(blob);
    if (gen == null) throw Exception('malformed group blob');
    final sender = senderUsername;
    var chain = await skStore.getPeer(roomId, sender, gen);
    if (chain == null) {
      final info = await ApiClient(state: state).getSenderKeys(roomId, sender: sender);
      final entries = (info['keys'] as List? ?? []);
      final entry = entries.firstWhere(
        (k) => (k['generation'] as int? ?? -1) == gen,
        orElse: () => null,
      );
      if (entry == null) throw Exception('no sender key for generation $gen');
      chain = await unwrapDistribution(entry['blob'] as String, state.crypto!.x25519Private);
      await skStore.putPeer(roomId, sender, chain);
    }
    final (payloadBytes, newChain) = await decryptGroupMessage(blob, chain);
    await skStore.putPeer(roomId, sender, newChain);
    return utf8.decode(payloadBytes);
  }

  /// Encrypt a group message (sender-key v3). Returns the send payload.
  static Future<Map<String, dynamic>> encryptGroup({
    required AppState state,
    required int roomId,
    required String plaintext,
    required List<String> participants,
    required List<Map<String, dynamic>> uploadedFiles,
    required List<Uint8List?> groupFileKeys,
  }) async {
    if (!state.hasE2ee) {
      throw StateError('E2EE keys not available');
    }
    final c = state.crypto!;
    final skStore = state.senderKeyStore!;
    final room = await ApiClient(state: state).getRoom(roomId);
    final roster = (room['participants'] as List? ?? []).map((e) => e as String).toList();
    final digest = rosterDigest(roster);

    var chain = await skStore.getOwn(roomId);
    final needRotation = chain == null ||
        chain.iteration >= rotationInterval ||
        (await skStore.getRoster(roomId)) != digest;
    if (needRotation) {
      chain = rotateChain(chain);
      final myUsername = state.currentUser!.username;
      final entries = <Map<String, dynamic>>[];
      for (final handle in roster) {
        if (handle.split('@').first == myUsername) continue;
        final keys = await senderKeys(state, handle);
        final blob = await wrapDistribution(chain, keys.x25519Pub);
        entries.add({
          'recipient_username': handle,
          'generation': chain.generation,
          'blob': blob,
        });
      }
      if (entries.isNotEmpty) {
        await ApiClient(state: state).putSenderKeys(roomId, entries);
      }
      await skStore.putRoster(roomId, digest);
    }

    final filesMap = <String, String>{};
    for (var i = 0; i < uploadedFiles.length; i++) {
      final fid = uploadedFiles[i]['id'];
      final raw = groupFileKeys[i];
      if (raw != null && fid != null) {
        filesMap[fid.toString()] = base64Encode(raw);
      }
    }
    final payload = utf8.encode(canonicalJson({
      't': 'group-payload',
      'v': 1,
      'body': plaintext,
      'files': filesMap,
    }));
    final (blobDict, messageKey, newChain) =
        await encryptGroupMessage(chain, payload);
    await skStore.putOwn(roomId, newChain);

    final senderBlobBytes = await buildSenderBlob(
      messageKey,
      payload,
      c.x25519Private,
      c.x25519Public,
      state.currentUser!.id.toString(),
      roomId.toString(),
    );

    final blobBytes = utf8.encode(canonicalJson(blobDict));
    final signature = await edSign(blobBytes, c.ed25519Private);

    return {
      'encrypted_blob': base64Encode(blobBytes),
      'sender_encrypted_blob': base64Encode(senderBlobBytes),
      'signature': base64Encode(signature),
      'file_ids': uploadedFiles.map((f) => f['id']).whereType<int>().toList(),
    };
  }

  static void _applyGroupPayload(Map<String, dynamic> msg, String plaintext) {
    // The file metadata (filename, id, is_encrypted and the decryption key in
    // `key_blob`) is delivered by the server inside `msg['files']`, so we only
    // need to recover the visible body from the (possibly group) payload.
    try {
      final payload = jsonDecode(plaintext) as Map<String, dynamic>;
      if (payload['t'] == 'group-payload') {
        msg['body'] = payload['body'] as String? ?? '';
      } else {
        msg['body'] = plaintext;
      }
    } catch (_) {
      msg['body'] = plaintext;
    }
  }

  static Future<void> _persist(
      AppState state, Map<String, dynamic> msg, String plaintext) async {
    _applyGroupPayload(msg, plaintext);
    msg['decrypted'] = true;
    if (state.messageStore != null && msg['id'] != null) {
      await state.messageStore!.put(msg['id'] as int, plaintext);
    }
  }
}
