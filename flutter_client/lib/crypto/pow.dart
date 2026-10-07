import 'dart:convert';

import 'package:crypto/crypto.dart';

import '../api/api_client.dart';

/// Solve a PoW challenge: find a nonce such that
/// `sha256('<challenge>:<nonce>')` hex starts with [difficulty] zero chars.
int solvePow(String challenge, int difficulty) {
  final prefix = '0' * difficulty;
  var nonce = 0;
  while (true) {
    final hash = sha256.convert(utf8.encode('$challenge:$nonce')).toString();
    if (hash.startsWith(prefix)) return nonce;
    nonce++;
  }
}

/// Fetch a fresh challenge from the server and solve it.
/// Returns (challenge, nonce) or null if the server does not require PoW.
Future<(String, String)?> obtainPow(ApiClient client) async {
  try {
    final ch = await client.getPowChallenge();
    final challenge = ch['challenge'] as String;
    final difficulty = ch['difficulty'] as int;
    final nonce = solvePow(challenge, difficulty);
    return (challenge, nonce.toString());
  } catch (_) {
    return null;
  }
}
