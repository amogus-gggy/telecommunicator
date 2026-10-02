import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_client/crypto/keys.dart';
import 'package:flutter_client/crypto/ratchet_facade.dart';
import 'package:flutter_client/crypto/ratchet_session_store.dart';
import 'package:flutter_test/flutter_test.dart';

/// Double Ratchet round-trips between two peers.
///
/// Regression cover for the "every message I was offline for shows
/// 'decryption error'" reports: a state that was never round-tripped through
/// [RatchetState.fromDict] used to carry an unmodifiable `skipped` map, and a
/// single failed decrypt used to delete the whole session.
class Peer {
  Peer(this.label) {
    id = generateX25519Keypair();
    ed = generateEd25519Keypair();
  }
  final String label;
  late final Future<(Uint8List, Uint8List)> id;
  late final Future<(Uint8List, Uint8List)> ed;
  RatchetSessionStore store = MemoryRatchetSessionStore();
}

Future<Map<String, String>> send(Peer from, Peer to, String text) async {
  final aId = await from.id;
  final aEd = await from.ed;
  final bId = await to.id;
  return RatchetEncryptor.encryptMessage(
    plaintext: text,
    peerKey: to.label,
    peerIdentityX25519Pub: bId.$2,
    senderEd25519Priv: aEd.$1,
    senderEd25519Pub: aEd.$2,
    senderX25519Priv: aId.$1,
    senderX25519Pub: aId.$2,
    senderId: from.label,
    recipientId: to.label,
    store: from.store,
  );
}

Future<String> recv(Peer by, Peer from, Map<String, String> enc) async {
  final bId = await by.id;
  final aEd = await from.ed;
  final aId = await from.id;
  return RatchetDecryptor.decryptMessage(
    encryptedMsg: {'blob': enc['blob'], 'signature': enc['signature']},
    peerKey: from.label,
    recipientX25519Priv: bId.$1,
    recipientX25519Pub: bId.$2,
    senderEd25519Pub: aEd.$2,
    senderX25519Pub: aId.$2,
    store: by.store,
  );
}

/// A correctly signed message claiming a message index far beyond the
/// recovery window — what a peer that reinstalled its client and rebuilt its
/// ratchet from scratch looks like.
Future<Map<String, String>> farAhead(Peer from, Peer to, int n) async {
  final aEd = await from.ed;
  final state = (await from.store.get(to.label))!;
  final blob = <String, dynamic>{
    'v': 2,
    'dh': base64Encode(state.dhPub!),
    'pn': 0,
    'n': n,
    'nonce': base64Encode(Uint8List(12)),
    'ct': base64Encode(Uint8List(48)),
  };
  final bytes = Uint8List.fromList(utf8.encode(canonicalJson(blob)));
  final sig = await edSign(bytes, aEd.$1);
  return {
    'blob': base64Encode(bytes),
    'signature': base64Encode(sig),
  };
}

/// Flip one byte of the ciphertext so the MAC check fails.
Map<String, String> corrupt(Map<String, String> enc) {
  final blob =
      jsonDecode(utf8.decode(base64Decode(enc['blob']!))) as Map<String, dynamic>;
  final ct = base64Decode(blob['ct'] as String);
  ct[0] ^= 0xFF;
  blob['ct'] = base64Encode(ct);
  return {
    'blob': base64Encode(utf8.encode(canonicalJson(blob))),
    'signature': enc['signature']!,
  };
}

void main() {
  test('both directions work across ratchet steps', () async {
    final a = Peer('alice');
    final b = Peer('bob');

    expect(await recv(b, a, await send(a, b, 'one')), 'one');
    expect(await recv(a, b, await send(b, a, 'reply')), 'reply');
    expect(await recv(b, a, await send(a, b, 'two')), 'two');
    expect(await recv(a, b, await send(b, a, 'reply2')), 'reply2');
    expect(await recv(b, a, await send(a, b, 'three')), 'three');
  });

  test('a gap in delivery is caught up through skipped keys', () async {
    final a = Peer('alice-gap');
    final b = Peer('bob-gap');

    final m1 = await send(a, b, 'one');
    final m2 = await send(a, b, 'two');
    final m3 = await send(a, b, 'three');

    // Reloading history means the newest message arrives before the older ones.
    expect(await recv(b, a, m3), 'three');
    expect(await recv(b, a, m1), 'one');
    expect(await recv(b, a, m2), 'two');
  });

  test('one undecryptable message does not destroy the session', () async {
    final a = Peer('alice-poison');
    final b = Peer('bob-poison');

    expect(await recv(b, a, await send(a, b, 'one')), 'one');
    expect(await recv(a, b, await send(b, a, 'reply')), 'reply');

    await expectLater(recv(b, a, corrupt(await send(a, b, 'garbage'))),
        throwsA(anything));

    expect(await b.store.get(a.label), isNotNull,
        reason: 'the ratchet state must survive an unreadable message');
    expect(await recv(b, a, await send(a, b, 'still works')), 'still works');
  });

  test('a message beyond the recovery window does not destroy the session',
      () async {
    final a = Peer('alice-ahead');
    final b = Peer('bob-ahead');

    expect(await recv(b, a, await send(a, b, 'one')), 'one');
    expect(await recv(a, b, await send(b, a, 'reply')), 'reply');

    await expectLater(recv(b, a, await farAhead(a, b, 5000)), throwsA(anything));

    expect(await b.store.get(a.label), isNotNull,
        reason: 'an unrecoverable message must not wipe the whole session');
    expect(await recv(b, a, await send(a, b, 'two')), 'two');
  });
}
