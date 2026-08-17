/// High-level Double Ratchet encrypt/decrypt facade.
///
/// Keeps the `{"blob", "sender_blob", "signature"}` transport contract, so the
/// rest of the app needs minimal changes. The recipient blob carries the
/// ratchet header (version 2); the sender's own copy keeps the version-1 shape
/// so `MessageDecryptor.decryptOwnMessage` works without touching ratchet state.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'double_ratchet.dart';
import 'keys.dart';
import 'message_crypto.dart';
import 'ratchet_session_store.dart';

const int _version = 2;

Uint8List _headerAd(Map<String, dynamic> blob) => utf8.encode(
    canonicalJson({'v': _version, 'dh': blob['dh'], 'pn': blob['pn'], 'n': blob['n']}));

int peekBlobVersion(String blobB64) {
  try {
    final blob = jsonDecode(utf8.decode(base64Decode(blobB64))) as Map<String, dynamic>;
    return (blob['v'] as int? ?? 1);
  } catch (_) {
    return 1;
  }
}

class RatchetEncryptor {
  static Future<Map<String, String>> encryptMessage({
    required String plaintext,
    required String peerKey,
    required List<int> peerIdentityX25519Pub,
    required List<int> senderEd25519Priv,
    required List<int> senderEd25519Pub,
    required List<int> senderX25519Priv,
    required List<int> senderX25519Pub,
    required String senderId,
    required String recipientId,
    required RatchetSessionStore store,
  }) async {
    final myPrivRaw = senderX25519Priv;
    final peerPubRaw = peerIdentityX25519Pub;

    var st = await store.get(peerKey);
    st ??= await initAlice(myPrivRaw, peerPubRaw);

    final (header, messageKey) = await ratchetEncrypt(st, utf8.encode(plaintext));

    final nonceR = randomBytes(nonceSize);
    final ad = _headerAd(header);
    final ct = await aesEncrypt(utf8.encode(plaintext), messageKey,
        nonce: nonceR, aad: ad);

    final blobDict = {
      'v': _version,
      'dh': header['dh'],
      'pn': header['pn'],
      'n': header['n'],
      'nonce': base64Encode(nonceR),
      'ct': base64Encode(ct),
    };
    final blobBytes = utf8.encode(canonicalJson(blobDict));
    final signature = await edSign(blobBytes, senderEd25519Priv);

    final senderBlobBytes = await buildSenderBlob(
      messageKey,
      utf8.encode(plaintext),
      senderX25519Priv,
      senderX25519Pub,
      senderId,
      recipientId,
    );

    await store.put(peerKey, st);

    return {
      'blob': base64Encode(blobBytes),
      'sender_blob': base64Encode(senderBlobBytes),
      'signature': base64Encode(signature),
    };
  }
}

/// Build the self-contained v1 sender blob: the message key is wrapped under
/// the sender's own long-term X25519 key and the plaintext is re-encrypted, so
/// the sender's own copy can be decrypted statelessly at any time. Used for
/// both personal (v2) and group (v3) messages (mirrors the Python client).
Future<Uint8List> buildSenderBlob(
  List<int> messageKey,
  List<int> plaintextBytes,
  List<int> senderX25519Priv,
  List<int> senderX25519Pub,
  String senderId,
  String recipientId,
) async {
  final ephemeral = await generateX25519Keypair();
  final ephemeralPubBytes = ephemeral.$2;
  final shared = await xShared(ephemeral.$1, senderX25519Pub);
  final wrapKey = await deriveWrappingKey(shared, ephemeralPubBytes, senderX25519Pub);
  final nonceWrap = randomBytes(nonceSize);
  final encMsgKey = await aesEncrypt(messageKey, wrapKey, nonce: nonceWrap);
  final nonceMsg = randomBytes(nonceSize);
  final ctMsg = await aesEncrypt(plaintextBytes, messageKey, nonce: nonceMsg);

  final senderBlobDict = {
    'sender_id': senderId,
    'recipient_id': recipientId,
    'ephemeral_pub': base64Encode(ephemeralPubBytes),
    'encrypted_msg_key': base64Encode(encMsgKey),
    'nonce_wrap': base64Encode(nonceWrap),
    'ciphertext_msg': base64Encode(ctMsg),
    'nonce_msg': base64Encode(nonceMsg),
  };
  return utf8.encode(canonicalJson(senderBlobDict));
}

class RatchetDecryptor {
  static Future<String> decryptMessage({
    required Map<String, dynamic> encryptedMsg,
    required String peerKey,
    required List<int> recipientX25519Priv,
    required List<int> recipientX25519Pub,
    required List<int> senderEd25519Pub,
    required List<int> senderX25519Pub,
    required RatchetSessionStore store,
  }) async {
    final blobBytes = base64Decode(encryptedMsg['blob'] as String);
    final signatureBytes = base64Decode(encryptedMsg['signature'] as String);

    if (!await edVerify(blobBytes, signatureBytes, senderEd25519Pub)) {
      throw Exception('Message signature verification failed');
    }

    final blob = jsonDecode(utf8.decode(blobBytes)) as Map<String, dynamic>;
    if ((blob['v'] as int? ?? 1) != _version) {
      throw Exception('not a ratchet (v2) blob');
    }

    final header = {'dh': blob['dh'], 'pn': blob['pn'], 'n': blob['n']};
    final nonce = base64Decode(blob['nonce'] as String);
    final ct = base64Decode(blob['ct'] as String);
    final ad = _headerAd(blob);

    final myPrivRaw = recipientX25519Priv;
    final senderIdPubRaw = senderX25519Pub;
    final headerDh = base64Decode(header['dh'] as String);

    Future<(String, RatchetState)> tryDecrypt(RatchetState state) async {
      final mk = await ratchetDecrypt(state, header);
      final pt = await aesDecrypt(ct, mk, nonce: nonce, aad: ad);
      return (utf8.decode(pt), state);
    }

    final existing = await store.get(peerKey);

    if (existing == null) {
      final (plaintext, state) =
          await tryDecrypt(await initBob(myPrivRaw, senderIdPubRaw, headerDh));
      await store.put(peerKey, state);
      return plaintext;
    }

    try {
      final (plaintext, state) = await tryDecrypt(existing.clone());
      await store.put(peerKey, state);
      return plaintext;
    } on Exception {
      // Heal by re-initializing as responder from the signed header.
      try {
        final (plaintext, state) =
            await tryDecrypt(await initBob(myPrivRaw, senderIdPubRaw, headerDh));
        await store.put(peerKey, state);
        return plaintext;
      } catch (e) {
        await store.delete(peerKey);
        rethrow;
      }
    }
  }
}
