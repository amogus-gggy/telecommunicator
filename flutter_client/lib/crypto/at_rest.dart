/// Encrypted-at-rest helpers for locally persisted E2EE material.
///
/// Values are JSON-serialized then AES-256-GCM encrypted under a key derived
/// from the account's identity X25519 private key (mirrors the Python client).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'keys.dart';

const int _nonceSize = 12;
final Uint8List _salt = utf8.encode('tlc-at-rest-salt-v1');

Future<Uint8List> deriveStorageKey(
  List<int> identityX25519PrivRaw,
  String account,
  String purpose,
) {
  final info = utf8.encode('tlc-at-rest-v1:$purpose:$account');
  return hkdf(identityX25519PrivRaw, _salt, info, keyLen);
}

Future<String> seal(List<int> key, Map<String, dynamic> obj) async {
  final data = utf8.encode(canonicalJson(obj));
  final nonce = randomBytes(_nonceSize);
  final ct = await aesEncrypt(data, key, nonce: nonce);
  final out = Uint8List(nonce.length + ct.length);
  out.setRange(0, nonce.length, nonce);
  out.setRange(nonce.length, out.length, ct);
  return base64Encode(out);
}

/// Decrypt; returns null on any failure.
Future<Object?> openValue(List<int> key, String? value) async {
  if (value == null || value.isEmpty) return null;
  try {
    final raw = base64Decode(value);
    final nonce = raw.sublist(0, _nonceSize);
    final ct = raw.sublist(_nonceSize);
    final data = await aesDecrypt(ct, key, nonce: nonce);
    return jsonDecode(utf8.decode(data));
  } catch (_) {
    return null;
  }
}
