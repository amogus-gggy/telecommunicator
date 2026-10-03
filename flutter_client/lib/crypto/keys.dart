/// Low-level cryptography primitives wrapping the `cryptography` package to
/// match the wire format of the Python `cryptography` library:
///  * AES-GCM output is `ciphertext || 16-byte tag`.
///  * Canonical JSON (`sort_keys`, `separators=(",",":")`) is used for signing.
library;

import 'dart:convert';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

const int keyLen = 32;
const int nonceSize = 12;
const int gcmTagSize = 16;

// ---------------------------------------------------------------------------
// Key generation
// ---------------------------------------------------------------------------

Future<(Uint8List, Uint8List)> generateX25519Keypair() async {
  final kp = await X25519().newKeyPair();
  final priv = Uint8List.fromList(await kp.extractPrivateKeyBytes());
  final pub = Uint8List.fromList((await kp.extractPublicKey()).bytes);
  return (priv, pub);
}

Future<(Uint8List, Uint8List)> generateEd25519Keypair() async {
  final kp = await Ed25519().newKeyPair();
  final priv = Uint8List.fromList(await kp.extractPrivateKeyBytes());
  final pub = Uint8List.fromList((await kp.extractPublicKey()).bytes);
  return (priv, pub);
}

// ---------------------------------------------------------------------------
// X25519 ECDH
// ---------------------------------------------------------------------------

final Uint8List _x25519BasePoint = Uint8List(32)..[0] = 9;

Future<Uint8List> _xSharedRaw(List<int> priv, List<int> pub) async {
  final kp = SimpleKeyPairData(
    priv,
    publicKey: SimplePublicKey(pub, type: KeyPairType.x25519),
    type: KeyPairType.x25519,
  );
  final shared = await X25519().sharedSecretKey(
      keyPair: kp, remotePublicKey: SimplePublicKey(pub, type: KeyPairType.x25519));
  return Uint8List.fromList(await shared.extractBytes());
}

/// X25519 shared secret (ECDH) with a peer public key.
Future<Uint8List> xShared(List<int> priv, List<int> pub) => _xSharedRaw(priv, pub);

/// X25519 public key bytes = scalar_mult(priv, basepoint).
Future<Uint8List> x25519PublicBytes(List<int> priv) => _xSharedRaw(priv, _x25519BasePoint);

// ---------------------------------------------------------------------------
// Ed25519 signatures
// ---------------------------------------------------------------------------

Future<Uint8List> ed25519PublicBytes(List<int> seed) async {
  final kp = await Ed25519().newKeyPairFromSeed(seed);
  return Uint8List.fromList((await kp.extractPublicKey()).bytes);
}

Future<Uint8List> edSign(List<int> message, List<int> privateSeed) async {
  final kp = await Ed25519().newKeyPairFromSeed(privateSeed);
  final sig = await Ed25519().sign(message, keyPair: kp);
  return Uint8List.fromList(sig.bytes);
}

Future<bool> edVerify(List<int> message, List<int> signature, List<int> publicKey) async {
  try {
    return await Ed25519().verify(
      message,
      signature: Signature(signature, publicKey: SimplePublicKey(publicKey, type: KeyPairType.ed25519)),
    );
  } catch (_) {
    return false;
  }
}

// ---------------------------------------------------------------------------
// AES-256-GCM
// ---------------------------------------------------------------------------

Future<Uint8List> aesEncrypt(List<int> message, List<int> key, {List<int>? nonce, List<int>? aad}) async {
  final alg = AesGcm.with256bits();
  final n = nonce != null ? Uint8List.fromList(nonce) : alg.newNonce();
  final secretBox = await alg.encrypt(
    message,
    secretKey: SecretKey(key),
    nonce: n,
    aad: aad ?? const [],
  );
  final out = Uint8List(secretBox.cipherText.length + secretBox.mac.bytes.length);
  out.setRange(0, secretBox.cipherText.length, secretBox.cipherText);
  out.setRange(secretBox.cipherText.length, out.length, secretBox.mac.bytes);
  return out;
}

Future<Uint8List> aesDecrypt(List<int> ctWithTag, List<int> key, {List<int>? nonce, List<int>? aad}) async {
  if (ctWithTag.length < gcmTagSize) throw Exception('ciphertext too short');
  final ctLen = ctWithTag.length - gcmTagSize;
  final ct = ctWithTag.sublist(0, ctLen);
  final tag = ctWithTag.sublist(ctLen);
  final secretBox = SecretBox(ct, nonce: nonce ?? Uint8List(nonceSize), mac: Mac(tag));
  final alg = AesGcm.with256bits();
  final plain = await alg.decrypt(secretBox, secretKey: SecretKey(key), aad: aad ?? const []);
  return Uint8List.fromList(plain);
}

// ---------------------------------------------------------------------------
// HMAC-SHA256 / HKDF
// ---------------------------------------------------------------------------

Future<Uint8List> hmacBytes(List<int> key, List<int> data) async {
  final mac = await Hmac.sha256().calculateMac(data, secretKey: SecretKey(key));
  return Uint8List.fromList(mac.bytes);
}

Future<Uint8List> hkdf(List<int> ikm, List<int> salt, List<int> info, int length) async {
  final alg = Hkdf(hmac: Hmac.sha256(), outputLength: length);
  final secretKey = await alg.deriveKey(
      secretKey: SecretKey(ikm), nonce: salt, info: info);
  return Uint8List.fromList(await secretKey.extractBytes());
}

// ---------------------------------------------------------------------------
// PBKDF2-HMAC-SHA256 (key backup)
// ---------------------------------------------------------------------------

Future<Uint8List> pbkdf2(List<int> password, List<int> salt, int iterations, int bits) async {
  // PBKDF2-HMAC-SHA256 is CPU-bound (600k iterations on login/register) and
  // would otherwise block the UI isolate for seconds. Run it in a background
  // isolate so the interface stays responsive.
  return Isolate.run(() => _pbkdf2Derive(password, salt, iterations, bits));
}

Future<Uint8List> _pbkdf2Derive(
    List<int> password, List<int> salt, int iterations, int bits) async {
  final alg = Pbkdf2.hmacSha256(iterations: iterations, bits: bits);
  final secretKey = await alg.deriveKey(secretKey: SecretKey(password), nonce: salt);
  return Uint8List.fromList(await secretKey.extractBytes());
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Canonical JSON matching Python `json.dumps(obj, sort_keys=True, separators=(",",":"))`.
///
/// Keys are sorted recursively and maps/lists are emitted compactly (no spaces
/// after `:` / `,`), so the serialized bytes match the Python client byte-for-byte.
String canonicalJson(Map<String, dynamic> obj) => _canonicalEncode(obj);

String _canonicalEncode(Object? v) {
  if (v is Map) {
    final keys = v.keys.toList()..sort();
    final parts = <String>[];
    for (final k in keys) {
      parts.add('${jsonEncode(k.toString())}:${_canonicalEncode(v[k])}');
    }
    return '{${parts.join(',')}}';
  }
  if (v is List) {
    final items = v.map(_canonicalEncode).toList();
    return '[${items.join(',')}]';
  }
  return jsonEncode(v);
}

/// Deterministic canonical serialization of an arbitrary encodable object.
String serializeCanonical(Object? obj) => _canonicalEncode(obj);

Uint8List randomBytes(int n) {
  final rand = math.Random.secure();
  return Uint8List.fromList(List<int>.generate(n, (_) => rand.nextInt(256)));
}

List<int> randoms(int n) => randomBytes(n);
