/// Signal-style Double Ratchet (version 2), ported from the Python client.
///
/// Pure state machine + serialization. Transport framing lives in
/// `ratchet_facade.dart`; storage lives in `ratchet_session_store.dart`.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'keys.dart';

const int maxSkip = 1000;
const int _keyLen = 32;

const String _infoInit = 'tlc-ratchet-v2-init';
const String _infoRoot = 'tlc-ratchet-v2-root';

class RatchetError implements Exception {
  final String message;
  RatchetError(this.message);
  @override
  String toString() => 'RatchetError: $message';
}

class KeyConsumedError extends RatchetError {
  KeyConsumedError(super.message);
}

class TooFarAheadError extends RatchetError {
  TooFarAheadError(super.message);
}

class MissingChainError extends RatchetError {
  MissingChainError(super.message);
}

/// Symmetric chain-key ratchet step. Returns [nextChainKey, messageKey].
Future<(Uint8List, Uint8List)> chainStep(Uint8List chainKey) async {
  final messageKey = await hmacBytes(chainKey, [0x01]);
  final nextChainKey = await hmacBytes(chainKey, [0x02]);
  return (nextChainKey, messageKey);
}

/// Root-key ratchet step. Returns [newRootKey, newChainKey].
Future<(Uint8List, Uint8List)> rootStep(Uint8List rootKey, Uint8List dhOutput) async {
  final out = await hkdf(dhOutput, rootKey, utf8.encode(_infoRoot), 64);
  return (out.sublist(0, _keyLen), out.sublist(_keyLen, 2 * _keyLen));
}

Future<(Uint8List, Uint8List)> _generateDh() async {
  final kp = await generateX25519Keypair();
  return (kp.$1, kp.$2);
}

Future<Uint8List> _dh(List<int> privRaw, List<int> peerPubRaw) async =>
    xShared(privRaw, peerPubRaw);

String _skipKey(Uint8List dh, int n) => '${base64Encode(dh)}:$n';

Future<Uint8List> deriveInitialSharedSecret(
    List<int> myX25519PrivRaw, List<int> peerX25519PubRaw) async {
  final dh = await _dh(myX25519PrivRaw, peerX25519PubRaw);
  return hkdf(dh, Uint8List(_keyLen), utf8.encode(_infoInit), _keyLen);
}

class RatchetState {
  RatchetState({
    required this.peerIdentityPub,
    required this.rootKey,
    this.dhPriv,
    this.dhPub,
    this.remoteDh,
    this.ckSend,
    this.ckRecv,
    this.nS = 0,
    this.nR = 0,
    this.pn = 0,
    this.skipped = const {},
  });

  final Uint8List peerIdentityPub;
  Uint8List rootKey;
  Uint8List? dhPriv;
  Uint8List? dhPub;
  Uint8List? remoteDh;
  Uint8List? ckSend;
  Uint8List? ckRecv;
  int nS;
  int nR;
  int pn;
  Map<String, Uint8List> skipped;

  RatchetState clone() => RatchetState(
        peerIdentityPub: Uint8List.fromList(peerIdentityPub),
        rootKey: Uint8List.fromList(rootKey),
        dhPriv: dhPriv == null ? null : Uint8List.fromList(dhPriv!),
        dhPub: dhPub == null ? null : Uint8List.fromList(dhPub!),
        remoteDh: remoteDh == null ? null : Uint8List.fromList(remoteDh!),
        ckSend: ckSend == null ? null : Uint8List.fromList(ckSend!),
        ckRecv: ckRecv == null ? null : Uint8List.fromList(ckRecv!),
        nS: nS,
        nR: nR,
        pn: pn,
        skipped: {
          for (final e in skipped.entries)
            e.key: Uint8List.fromList(e.value)
        },
      );

  Map<String, dynamic> toDict() => {
        'peer_identity_pub': base64Encode(peerIdentityPub),
        'root_key': base64Encode(rootKey),
        'dh_priv': dhPriv == null ? null : base64Encode(dhPriv!),
        'dh_pub': dhPub == null ? null : base64Encode(dhPub!),
        'remote_dh': remoteDh == null ? null : base64Encode(remoteDh!),
        'ck_send': ckSend == null ? null : base64Encode(ckSend!),
        'ck_recv': ckRecv == null ? null : base64Encode(ckRecv!),
        'n_s': nS,
        'n_r': nR,
        'pn': pn,
        'skipped': {
          for (final e in skipped.entries) e.key: base64Encode(e.value)
        },
      };

  factory RatchetState.fromDict(Map<String, dynamic> d) => RatchetState(
        peerIdentityPub: base64Decode(d['peer_identity_pub'] as String),
        rootKey: base64Decode(d['root_key'] as String),
        dhPriv: d['dh_priv'] == null ? null : base64Decode(d['dh_priv'] as String),
        dhPub: d['dh_pub'] == null ? null : base64Decode(d['dh_pub'] as String),
        remoteDh:
            d['remote_dh'] == null ? null : base64Decode(d['remote_dh'] as String),
        ckSend: d['ck_send'] == null ? null : base64Decode(d['ck_send'] as String),
        ckRecv: d['ck_recv'] == null ? null : base64Decode(d['ck_recv'] as String),
        nS: d['n_s'] as int? ?? 0,
        nR: d['n_r'] as int? ?? 0,
        pn: d['pn'] as int? ?? 0,
        skipped: {
          for (final e in (d['skipped'] as Map? ?? {}).entries)
            e.key as String: base64Decode(e.value as String)
        },
      );
}

Future<RatchetState> initAlice(
    List<int> myX25519PrivRaw, List<int> peerX25519PubRaw) async {
  final sk = await deriveInitialSharedSecret(myX25519PrivRaw, peerX25519PubRaw);
  final st = RatchetState(peerIdentityPub: Uint8List.fromList(peerX25519PubRaw), rootKey: sk);
  final dh = await _generateDh();
  st.dhPriv = dh.$1;
  st.dhPub = dh.$2;
  st.remoteDh = Uint8List.fromList(peerX25519PubRaw);
  final (newRoot, newCk) = await rootStep(st.rootKey, await _dh(st.dhPriv!, st.remoteDh!));
  st.rootKey = newRoot;
  st.ckSend = newCk;
  return st;
}

Future<RatchetState> initBob(
  List<int> myX25519PrivRaw,
  List<int> peerIdentityPubRaw,
  List<int> headerDh,
) async {
  final sk = await deriveInitialSharedSecret(myX25519PrivRaw, peerIdentityPubRaw);
  final st = RatchetState(peerIdentityPub: Uint8List.fromList(peerIdentityPubRaw), rootKey: sk);
  st.remoteDh = Uint8List.fromList(headerDh);
  final (newRoot, newCkRecv) = await rootStep(st.rootKey, await _dh(myX25519PrivRaw, st.remoteDh!));
  st.rootKey = newRoot;
  st.ckRecv = newCkRecv;
  final dh = await _generateDh();
  st.dhPriv = dh.$1;
  st.dhPub = dh.$2;
  final (newRoot2, newCkSend) = await rootStep(st.rootKey, await _dh(st.dhPriv!, st.remoteDh!));
  st.rootKey = newRoot2;
  st.ckSend = newCkSend;
  return st;
}

/// Encrypt on the sending chain. Returns the v2 header and the raw message key.
Future<(Map<String, dynamic>, Uint8List)> ratchetEncrypt(RatchetState st, List<int> plaintext) async {
  if (st.ckSend == null) throw MissingChainError('Sending chain not established');
  final (nextCk, messageKey) = await chainStep(st.ckSend!);
  st.ckSend = nextCk;
  final header = {
    'dh': base64Encode(st.dhPub!),
    'pn': st.pn,
    'n': st.nS,
  };
  st.nS += 1;
  return (header, messageKey);
}

Future<void> _skipMessageKeys(RatchetState st, int until) async {
  if (until > st.nR + maxSkip) {
    throw TooFarAheadError('cannot skip to message index $until');
  }
  if (until <= st.nR) return;
  if (st.ckRecv == null) throw MissingChainError('Receiving chain not established');
  while (st.nR < until) {
    final (nextCk, mk) = await chainStep(st.ckRecv!);
    st.ckRecv = nextCk;
    st.skipped[_skipKey(st.remoteDh!, st.nR)] = mk;
    st.nR += 1;
  }
}

/// Resolve the message key for an incoming message, advancing state.
Future<Uint8List> ratchetDecrypt(RatchetState st, Map<String, dynamic> header) async {
  final peerDh = base64Decode(header['dh'] as String);
  final pn = header['pn'] as int;
  final n = header['n'] as int;

  final skKey = _skipKey(peerDh, n);
  if (st.skipped.containsKey(skKey)) {
    final mk = st.skipped.remove(skKey)!;
    return mk;
  }

  if (st.remoteDh == null || !_bytesEq(peerDh, st.remoteDh!)) {
    await _skipMessageKeys(st, pn);
    st.pn = st.nS;
    st.nS = 0;
    st.nR = 0;
    st.remoteDh = peerDh;
    if (st.dhPriv == null) throw MissingChainError('No local ratchet key for DH step');
    final (newRoot, newCkRecv) = await rootStep(st.rootKey, await _dh(st.dhPriv!, st.remoteDh!));
    st.rootKey = newRoot;
    st.ckRecv = newCkRecv;
    final dh = await _generateDh();
    st.dhPriv = dh.$1;
    st.dhPub = dh.$2;
    final (newRoot2, newCkSend) = await rootStep(st.rootKey, await _dh(st.dhPriv!, st.remoteDh!));
    st.rootKey = newRoot2;
    st.ckSend = newCkSend;
  }

  if (n < st.nR) throw KeyConsumedError('message index $n already consumed');
  await _skipMessageKeys(st, n);

  if (st.ckRecv == null) throw MissingChainError('Receiving chain not established');
  final (nextCk, mk) = await chainStep(st.ckRecv!);
  st.ckRecv = nextCk;
  st.nR += 1;
  return mk;
}

bool _bytesEq(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}
