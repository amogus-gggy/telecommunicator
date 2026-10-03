/// Sender-key group encryption (Signal-style) for group rooms.
///
/// Each member keeps one sending chain per room; the chain key is wrapped
/// under each member's long-term X25519 identity key for distribution. Message
/// blobs are version 3; their plaintext is a JSON payload carrying the body
/// plus per-file keys (see `ratchet_facade` / room send path).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'keys.dart';

const int rotationInterval = 500;
const int maxSkip = 1000;

const int msgVersion = 3;
const int distVersion = 1;

const String _infoDist = 'tlc-sender-key-dist-v1';

class SenderKeyError implements Exception {
  final String message;
  SenderKeyError(this.message);
  @override
  String toString() => 'SenderKeyError: $message';
}

class KeyConsumedError extends SenderKeyError {
  KeyConsumedError(super.message);
}

class TooFarAheadError extends SenderKeyError {
  TooFarAheadError(super.message);
}

class UnknownGenerationError extends SenderKeyError {
  UnknownGenerationError(super.message);
}

class DistributionError extends SenderKeyError {
  DistributionError(super.message);
}

class SenderChainState {
  SenderChainState({
    required this.generation,
    required this.iteration,
    required this.chainKey,
  });

  final int generation;
  int iteration;
  Uint8List chainKey;

  Map<String, dynamic> toDict() => {
        'generation': generation,
        'iteration': iteration,
        'chain_key': base64Encode(chainKey),
      };

  factory SenderChainState.fromDict(Map<String, dynamic> d) => SenderChainState(
        generation: d['generation'] as int,
        iteration: d['iteration'] as int,
        chainKey: base64Decode(d['chain_key'] as String),
      );
}

/// Stable digest of a roster — any join/leave changes it. Used only to detect
/// roster changes within the client (rotation trigger), so the exact hash
/// algorithm is irrelevant as long as it is deterministic.
String rosterDigest(List<String> participants) {
  final joined = participants.map((p) => p.trim()).toSet().toList()..sort();
  return base64Encode(utf8.encode(joined.join('\n')));
}

SenderChainState createChain({int generation = 0}) =>
    SenderChainState(generation: generation, iteration: 0, chainKey: randomBytes(keyLen));

SenderChainState rotateChain(SenderChainState? current) {
  final generation = current == null ? 0 : current.generation + 1;
  return createChain(generation: generation);
}

/// Ratchet the chain to [target] and consume that iteration.
Future<(Uint8List, SenderChainState)> advanceChain(
    SenderChainState state, int target) async {
  if (target < state.iteration) {
    throw KeyConsumedError(
        'iteration $target already consumed (chain at ${state.iteration})');
  }
  if (target - state.iteration > maxSkip) {
    throw TooFarAheadError('iteration $target is more than $maxSkip ahead');
  }
  var chainKey = state.chainKey;
  for (var i = state.iteration; i < target; i++) {
    chainKey = await hmacBytes(chainKey, [0x02]);
  }
  final messageKey = await hmacBytes(chainKey, [0x01]);
  final nextChainKey = await hmacBytes(chainKey, [0x02]);
  return (
    messageKey,
    SenderChainState(
        generation: state.generation, iteration: target + 1, chainKey: nextChainKey)
  );
}

Uint8List _messageAd({required int generation, required int n}) =>
    utf8.encode(canonicalJson({'v': msgVersion, 'gen': generation, 'n': n}));

Future<(Map<String, dynamic>, Uint8List, SenderChainState)> encryptGroupMessage(
  SenderChainState state,
  List<int> payloadBytes,
) async {
  final n = state.iteration;
  final (messageKey, newState) = await advanceChain(state, n);
  final nonce = randomBytes(nonceSize);
  final ad = _messageAd(generation: state.generation, n: n);
  final ct = await aesEncrypt(payloadBytes, messageKey, nonce: nonce, aad: ad);
  final blobDict = {
    'v': msgVersion,
    'gen': state.generation,
    'n': n,
    'nonce': base64Encode(nonce),
    'ct': base64Encode(ct),
  };
  return (blobDict, messageKey, newState);
}

Future<(Uint8List, SenderChainState)> decryptGroupMessage(
  String blobB64,
  SenderChainState chain,
) async {
  late Map<String, dynamic> blob;
  try {
    blob = jsonDecode(utf8.decode(base64Decode(blobB64))) as Map<String, dynamic>;
  } catch (e) {
    throw SenderKeyError('malformed group message blob');
  }
  if ((blob['v'] as int? ?? 0) != msgVersion) {
    throw SenderKeyError('not a group (v3) blob');
  }
  final generation = blob['gen'] as int;
  if (generation != chain.generation) {
    throw UnknownGenerationError('blob generation $generation, chain at ${chain.generation}');
  }
  final n = blob['n'] as int;
  final (messageKey, newChain) = await advanceChain(chain, n);
  final nonce = base64Decode(blob['nonce'] as String);
  final ct = base64Decode(blob['ct'] as String);
  final ad = _messageAd(generation: generation, n: n);
  try {
    final payload = await aesDecrypt(ct, messageKey, nonce: nonce, aad: ad);
    return (payload, newChain);
  } catch (e) {
    throw SenderKeyError('group message authentication failed');
  }
}

/// The bytes that get signed (canonical blob dict).
String serializeBlob(Map<String, dynamic> blobDict) => canonicalJson(blobDict);

int? peekGroupGeneration(String blobB64) {
  try {
    final blob = jsonDecode(utf8.decode(base64Decode(blobB64))) as Map<String, dynamic>;
    if ((blob['v'] as int? ?? 0) != msgVersion) return null;
    return blob['gen'] as int?;
  } catch (_) {
    return null;
  }
}

Future<String> wrapDistribution(
  SenderChainState chain,
  List<int> recipientX25519Pub,
) async {
  final payload = utf8.encode(canonicalJson({
    'v': distVersion,
    't': 'sender-key',
    'gen': chain.generation,
    'ck': base64Encode(chain.chainKey),
  }));
  final ephemeral = await generateX25519Keypair();
  final ephemeralPub = ephemeral.$2;
  final shared = await xShared(ephemeral.$1, recipientX25519Pub);
  final wrapKey = await hkdf(
      shared, <int>[...ephemeralPub, ...recipientX25519Pub], utf8.encode(_infoDist), keyLen);
  final nonce = randomBytes(nonceSize);
  final ct = await aesEncrypt(payload, wrapKey, nonce: nonce);
  final blob = {
    'v': distVersion,
    'ephemeral_pub': base64Encode(ephemeralPub),
    'ct': base64Encode(<int>[...nonce, ...ct]),
  };
  return base64Encode(utf8.encode(canonicalJson(blob)));
}

Future<SenderChainState> unwrapDistribution(
  String blobB64,
  List<int> recipientX25519Priv,
) async {
  late Map<String, dynamic> blob;
  try {
    blob = jsonDecode(utf8.decode(base64Decode(blobB64))) as Map<String, dynamic>;
  } catch (e) {
    throw DistributionError('malformed distribution blob');
  }
  final ephemeralPubBytes = base64Decode(blob['ephemeral_pub'] as String);
  final raw = base64Decode(blob['ct'] as String);
  final nonce = raw.sublist(0, nonceSize);
  final ct = raw.sublist(nonceSize);
  final shared = await xShared(recipientX25519Priv, ephemeralPubBytes);
  final wrapKey = await hkdf(shared, <int>[...ephemeralPubBytes, ...await x25519PublicBytes(recipientX25519Priv)], utf8.encode(_infoDist), keyLen);
  late Uint8List payload;
  try {
    payload = await aesDecrypt(ct, wrapKey, nonce: nonce);
  } catch (e) {
    throw DistributionError('distribution blob unwrap failed');
  }
  late Map<String, dynamic> data;
  try {
    data = jsonDecode(utf8.decode(payload)) as Map<String, dynamic>;
  } catch (e) {
    throw DistributionError('distribution blob unwrap failed');
  }
  if ((data['v'] as int? ?? 0) != distVersion || data['t'] != 'sender-key') {
    throw DistributionError('not a sender-key distribution blob');
  }
  return SenderChainState(
    generation: data['gen'] as int,
    iteration: 0,
    chainKey: base64Decode(data['ck'] as String),
  );
}
