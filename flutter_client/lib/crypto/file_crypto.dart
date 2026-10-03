/// Streaming file encryption/decryption for E2EE file transfer.
///
/// Wire format (concatenated):
///   [8 bytes: total chunk count, big-endian uint64]
///   for each chunk:
///     [4 bytes: ciphertext length, big-endian uint32]
///     [12 bytes: nonce]
///     [N bytes: ciphertext || 16-byte GCM tag]
/// The chunk index is included as AAD so chunks cannot be reordered. Key blobs
/// are identical in structure to the Python client (version 2).
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'keys.dart';

const int chunkSize = 1 * 1024 * 1024; // 1 MiB

Uint8List _pack32(int v) {
  final bd = ByteData(4);
  bd.setUint32(0, v, Endian.big);
  return bd.buffer.asUint8List();
}

Uint8List _pack64(int v) {
  final bd = ByteData(8);
  bd.setUint64(0, v, Endian.big);
  return bd.buffer.asUint8List();
}

int _unpack32(Uint8List b) => ByteData.sublistView(b).getUint32(0, Endian.big);
int _unpack64(Uint8List b) => ByteData.sublistView(b).getUint64(0, Endian.big);

Future<Uint8List> _deriveWrappingKey(
  List<int> sharedSecret,
  List<int> ephemeralPubBytes,
  List<int> peerPubBytes,
) =>
    hkdf(sharedSecret, <int>[...ephemeralPubBytes, ...peerPubBytes],
        utf8.encode('file-v1'), keyLen);

Future<(Uint8List, Uint8List)> _wrapFileKey(
  List<int> fileKey,
  List<int> ephemeralPriv,
  List<int> ephemeralPubBytes,
  List<int> peerPub,
) async {
  final shared = await xShared(ephemeralPriv, peerPub);
  final wrap = await _deriveWrappingKey(shared, ephemeralPubBytes, peerPub);
  final nonce = randomBytes(nonceSize);
  final encrypted = await aesEncrypt(fileKey, wrap, nonce: nonce);
  return (encrypted, nonce);
}

Future<Uint8List> _unwrapFileKey(
  List<int> encryptedFileKey,
  List<int> nonceWrap,
  List<int> ephemeralPubBytes,
  List<int> x25519Priv,
) async {
  final shared = await xShared(x25519Priv, ephemeralPubBytes);
  final wrap = await _deriveWrappingKey(shared, ephemeralPubBytes, await x25519PublicBytes(x25519Priv));
  return aesDecrypt(encryptedFileKey, wrap, nonce: nonceWrap);
}

class FileEncryptor {
  /// Stream-encrypt [src] into [dst]; returns key metadata (no ciphertext here).
  static Future<Map<String, String>> encryptFileStreaming({
    required File src,
    required File dst,
    required String filename,
    required List<int> recipientX25519Pub,
    required List<int> senderEd25519Priv,
    required List<int> senderEd25519Pub,
    required String senderId,
    required String recipientId,
  }) async {
    final ephemeral = await generateX25519Keypair();
    final ephemeralPubBytes = ephemeral.$2;
    final fileKey = randomBytes(keyLen);

    final rafIn = await src.open();
    final rafOut = await dst.open(mode: FileMode.write);
    await rafOut.writeFrom(Uint8List(8)); // chunk count placeholder
    var chunkIndex = 0;
    while (true) {
      final plain = await rafIn.read(chunkSize);
      if (plain.isEmpty) break;
      final nonce = randomBytes(nonceSize);
      final aad = _pack64(chunkIndex);
      final ct = await aesEncrypt(plain, fileKey, nonce: nonce, aad: aad);
      await rafOut.writeFrom(_pack32(ct.length));
      await rafOut.writeFrom(nonce);
      await rafOut.writeFrom(ct);
      chunkIndex++;
    }
    final end = await rafOut.position();
    await rafOut.setPosition(0);
    await rafOut.writeFrom(_pack64(chunkIndex));
    await rafOut.setPosition(end);
    await rafIn.close();
    await rafOut.close();

    final (encKey, nonceWrap) =
        await _wrapFileKey(fileKey, ephemeral.$1, ephemeralPubBytes, recipientX25519Pub);
    final blobDict = {
      'sender_id': senderId,
      'recipient_id': recipientId,
      'filename': filename,
      'ephemeral_pub': base64Encode(ephemeralPubBytes),
      'encrypted_file_key': base64Encode(encKey),
      'nonce_wrap': base64Encode(nonceWrap),
      'version': 2,
    };
    final blobBytes = utf8.encode(canonicalJson(blobDict));
    final signature = await edSign(blobBytes, senderEd25519Priv);

    final (encKeyS, nonceWrapS) =
        await _wrapFileKey(fileKey, ephemeral.$1, ephemeralPubBytes, senderEd25519Pub);
    final senderBlobDict = {
      ...blobDict,
      'encrypted_file_key': base64Encode(encKeyS),
      'nonce_wrap': base64Encode(nonceWrapS),
    };
    final senderBlobBytes = utf8.encode(canonicalJson(senderBlobDict));

    return {
      'key_blob': base64Encode(blobBytes),
      'key_sender_blob': base64Encode(senderBlobBytes),
      'signature': base64Encode(signature),
    };
  }

  /// Encrypt a group-room file; returns the raw file key (key travels inside
  /// the sender-key message payload instead of a per-recipient key blob).
  static Future<Uint8List> encryptFileGroupStreaming({
    required File src,
    required File dst,
    Uint8List? fileKey,
  }) async {
    final key = fileKey ?? randomBytes(keyLen);
    final rafIn = await src.open();
    final rafOut = await dst.open(mode: FileMode.write);
    await rafOut.writeFrom(Uint8List(8));
    var chunkIndex = 0;
    while (true) {
      final plain = await rafIn.read(chunkSize);
      if (plain.isEmpty) break;
      final nonce = randomBytes(nonceSize);
      final aad = _pack64(chunkIndex);
      final ct = await aesEncrypt(plain, key, nonce: nonce, aad: aad);
      await rafOut.writeFrom(_pack32(ct.length));
      await rafOut.writeFrom(nonce);
      await rafOut.writeFrom(ct);
      chunkIndex++;
    }
    final end = await rafOut.position();
    await rafOut.setPosition(0);
    await rafOut.writeFrom(_pack64(chunkIndex));
    await rafOut.setPosition(end);
    await rafIn.close();
    await rafOut.close();
    return key;
  }
}

class FileDecryptor {
  static Future<void> decryptFileStreaming({
    required File src,
    required File dst,
    required String keyBlobB64,
    required String signatureB64,
    required List<int> x25519Priv,
    required List<int> senderEd25519Pub,
  }) async {
    final blobBytes = base64Decode(keyBlobB64);
    if (!await edVerify(blobBytes, base64Decode(signatureB64), senderEd25519Pub)) {
      throw Exception('File signature verification failed');
    }
    final fileKey = await _unwrapKey(blobBytes, x25519Priv);
    await _decryptStream(src, dst, fileKey);
  }

  static Future<void> decryptOwnFileStreaming({
    required File src,
    required File dst,
    required String keySenderBlobB64,
    required List<int> x25519Priv,
  }) async {
    final fileKey = await _unwrapKey(base64Decode(keySenderBlobB64), x25519Priv);
    await _decryptStream(src, dst, fileKey);
  }

  static Future<void> decryptFileWithKeyStreaming({
    required File src,
    required File dst,
    required List<int> fileKey,
  }) async {
    await _decryptStream(src, dst, fileKey);
  }

  static Future<Uint8List> _unwrapKey(
      Uint8List keyBlobBytes, List<int> x25519Priv) async {
    final blob = jsonDecode(utf8.decode(keyBlobBytes)) as Map<String, dynamic>;
    return _unwrapFileKey(
      base64Decode(blob['encrypted_file_key'] as String),
      base64Decode(blob['nonce_wrap'] as String),
      base64Decode(blob['ephemeral_pub'] as String),
      x25519Priv,
    );
  }

  static Future<void> _decryptStream(File src, File dst, List<int> fileKey) async {
    final rafIn = await src.open();
    final rafOut = await dst.open(mode: FileMode.write);
    final header = await rafIn.read(8);
    if (header.length < 8) throw Exception('Truncated file: missing chunk count header');
    final totalChunks = _unpack64(header);
    for (var i = 0; i < totalChunks; i++) {
      final lenBuf = await rafIn.read(4);
      if (lenBuf.length < 4) throw Exception('Truncated file at chunk $i');
      final ctLen = _unpack32(lenBuf);
      final nonce = await rafIn.read(nonceSize);
      final ct = await rafIn.read(ctLen);
      final aad = _pack64(i);
      final plain = await aesDecrypt(ct, fileKey, nonce: nonce, aad: aad);
      await rafOut.writeFrom(plain);
    }
    await rafIn.close();
    await rafOut.close();
  }
}
