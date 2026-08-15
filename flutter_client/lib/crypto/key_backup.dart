/// Key backup and restore utilities for E2EE cryptographic keys.
///
/// Encrypts Ed25519 and X25519 private keys with a password using
/// PBKDF2-HMAC-SHA256 key derivation and AES-256-GCM encryption. Blob format:
/// salt(16) || nonce(12) || ciphertext+tag.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'keys.dart';

const int pbkdf2Iterations = 600000;
const int _saltSize = 16;
const int _nonceSize = 12;
const int _keySize = 32;

class KeyBackupManager {
  static Future<Uint8List> _deriveKey(String password, List<int> salt) {
    return pbkdf2(utf8.encode(password), salt, pbkdf2Iterations, _keySize * 8);
  }

  /// Encrypt private keys into a portable backup blob.
  static Future<Uint8List> encryptBackup(
    List<int> ed25519Priv,
    List<int> x25519Priv,
    String password,
  ) async {
    final plaintext = utf8.encode(canonicalJson({
      'ed25519_priv': base64Encode(ed25519Priv),
      'x25519_priv': base64Encode(x25519Priv),
      'version': 1,
    }));
    final salt = randomBytes(_saltSize);
    final nonce = randomBytes(_nonceSize);
    final key = await _deriveKey(password, salt);
    final ciphertext = await aesEncrypt(plaintext, key, nonce: nonce);
    final out = Uint8List(_saltSize + _nonceSize + ciphertext.length);
    out.setRange(0, _saltSize, salt);
    out.setRange(_saltSize, _saltSize + _nonceSize, nonce);
    out.setRange(_saltSize + _nonceSize, out.length, ciphertext);
    return out;
  }

  /// Decrypt a backup blob; throws on wrong password / corruption.
  static Future<(Uint8List, Uint8List)> decryptBackup(
    List<int> encryptedBlob,
    String password,
  ) async {
    final salt = encryptedBlob.sublist(0, _saltSize);
    final nonce = encryptedBlob.sublist(_saltSize, _saltSize + _nonceSize);
    final ciphertext = encryptedBlob.sublist(_saltSize + _nonceSize);
    final key = await _deriveKey(password, salt);
    final plaintext = await aesDecrypt(ciphertext, key, nonce: nonce);
    final data = jsonDecode(utf8.decode(plaintext)) as Map<String, dynamic>;
    return (
      base64Decode(data['ed25519_priv'] as String),
      base64Decode(data['x25519_priv'] as String),
    );
  }
}
