/// Message encryption/decryption using ephemeral X25519 + AES-256-GCM.
///
/// This is the version-1 ("double wrapped") scheme used by the Python client's
/// `MessageEncryptor`/`MessageDecryptor`. The v2 Double-Ratchet path lives in
/// `ratchet_facade.dart`; it reuses [deriveWrappingKey] to build the
/// sender's own stateless copy of each message.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'keys.dart';

/// Derive the AES key that wraps the per-message key for one peer.
Future<Uint8List> deriveWrappingKey(
  List<int> sharedSecret,
  List<int> ephemeralPubBytes,
  List<int> peerPubBytes,
) =>
    hkdf(sharedSecret, <int>[...ephemeralPubBytes, ...peerPubBytes],
        utf8.encode('msg-v1'), keyLen);

class MessageEncryptor {
  /// Encrypt [plaintext] for both recipient and sender, returning base64
  /// `blob`, `sender_blob`, and `signature` (mirrors the Python v1 scheme).
  static Future<Map<String, String>> encryptMessage({
    required String plaintext,
    required List<int> recipientX25519Pub,
    required List<int> senderEd25519Priv,
    required List<int> senderEd25519Pub,
    required List<int> senderX25519Priv,
    required List<int> senderX25519Pub,
    required String senderId,
    required String recipientId,
  }) async {
    final ephemeral = await generateX25519Keypair();
    final ephemeralPubBytes = ephemeral.$2;

    final messageKey = randomBytes(keyLen);
    final nonceMsg = randomBytes(nonceSize);
    final ctMsg = await aesEncrypt(utf8.encode(plaintext), messageKey,
        nonce: nonceMsg);

    // Recipient blob
    final sharedR = await xShared(ephemeral.$1, recipientX25519Pub);
    final wrapR = await deriveWrappingKey(sharedR, ephemeralPubBytes, recipientX25519Pub);
    final nonceWrapR = randomBytes(nonceSize);
    final encMsgKeyR = await aesEncrypt(messageKey, wrapR, nonce: nonceWrapR);

    final blobDict = {
      'sender_id': senderId,
      'recipient_id': recipientId,
      'ephemeral_pub': base64Encode(ephemeralPubBytes),
      'encrypted_msg_key': base64Encode(encMsgKeyR),
      'nonce_wrap': base64Encode(nonceWrapR),
      'ciphertext_msg': base64Encode(ctMsg),
      'nonce_msg': base64Encode(nonceMsg),
    };
    final blobBytes = utf8.encode(canonicalJson(blobDict));
    final signature = await edSign(blobBytes, senderEd25519Priv);

    // Sender blob (same ciphertext, wrapped under sender's long-term key)
    final sharedS = await xShared(ephemeral.$1, senderX25519Pub);
    final wrapS = await deriveWrappingKey(sharedS, ephemeralPubBytes, senderX25519Pub);
    final nonceWrapS = randomBytes(nonceSize);
    final encMsgKeyS = await aesEncrypt(messageKey, wrapS, nonce: nonceWrapS);

    final senderBlobDict = {
      'sender_id': senderId,
      'recipient_id': recipientId,
      'ephemeral_pub': base64Encode(ephemeralPubBytes),
      'encrypted_msg_key': base64Encode(encMsgKeyS),
      'nonce_wrap': base64Encode(nonceWrapS),
      'ciphertext_msg': base64Encode(ctMsg),
      'nonce_msg': base64Encode(nonceMsg),
    };
    final senderBlobBytes = utf8.encode(canonicalJson(senderBlobDict));

    return {
      'blob': base64Encode(blobBytes),
      'sender_blob': base64Encode(senderBlobBytes),
      'signature': base64Encode(signature),
    };
  }
}

class MessageDecryptor {
  static Future<String> decryptMessage(
    Map<String, dynamic> encryptedMsg,
    List<int> recipientX25519Priv,
    List<int> recipientX25519Pub,
    List<int> senderEd25519Pub,
  ) async {
    final blobBytes = base64Decode(encryptedMsg['blob'] as String);
    final signature = base64Decode(encryptedMsg['signature'] as String);
    if (!await edVerify(blobBytes, signature, senderEd25519Pub)) {
      throw Exception('Message signature verification failed');
    }
    return _decryptBlob(blobBytes, recipientX25519Priv, recipientX25519Pub);
  }

  static Future<String> decryptOwnMessage(
    String senderBlobB64,
    List<int> senderX25519Priv,
    List<int> senderX25519Pub,
  ) async {
    return _decryptBlob(base64Decode(senderBlobB64), senderX25519Priv, senderX25519Pub);
  }

  static Future<String> _decryptBlob(
      Uint8List blobBytes, List<int> x25519Priv, List<int> x25519Pub) async {
    final blob = jsonDecode(utf8.decode(blobBytes)) as Map<String, dynamic>;
    final ephemeralPub = base64Decode(blob['ephemeral_pub'] as String);
    final encMsgKey = base64Decode(blob['encrypted_msg_key'] as String);
    final nonceWrap = base64Decode(blob['nonce_wrap'] as String);
    final ctMsg = base64Decode(blob['ciphertext_msg'] as String);
    final nonceMsg = base64Decode(blob['nonce_msg'] as String);

    final shared = await xShared(x25519Priv, ephemeralPub);
    final wrap = await deriveWrappingKey(shared, ephemeralPub, x25519Pub);
    final messageKey = await aesDecrypt(encMsgKey, wrap, nonce: nonceWrap);
    final plaintext = await aesDecrypt(ctMsg, messageKey, nonce: nonceMsg);
    return utf8.decode(plaintext);
  }
}
