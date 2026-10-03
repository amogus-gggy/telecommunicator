/// Sender-key group store (persisted encrypted at rest).
///
/// Holds, per room: the local user's sending chain, the roster digest, and a
/// map of (sender handle) -> list of receive chains. Receiving chains keep the
/// last [_keepGenerations] generations so in-flight messages from a
/// just-rotated sender still decrypt (mirrors the Python client's
/// `sender_key_store`).
library;

import 'dart:io';

import 'at_rest.dart';
import 'sender_keys.dart';

const int _keepGenerations = 3;

abstract class SenderKeyStore {
  Future<SenderChainState?> getOwn(int roomId);
  Future<void> putOwn(int roomId, SenderChainState state);
  Future<String?> getRoster(int roomId);
  Future<void> putRoster(int roomId, String digest);
  Future<SenderChainState?> getPeer(int roomId, String sender, int generation);
  Future<void> putPeer(int roomId, String sender, SenderChainState state);
}

class FileSenderKeyStore implements SenderKeyStore {
  FileSenderKeyStore(this._path, this._storageKey);

  final String _path;
  final List<int> _storageKey;

  final Map<int, SenderChainState> _own = {};
  final Map<int, String> _roster = {};
  final Map<String, List<SenderChainState>> _peers = {}; // key: "$roomId|$sender"
  bool _loaded = false;

  static String _peerKey(int roomId, String sender) => '$roomId|$sender';

  Future<void> _ensureLoaded() async {
    if (_loaded) return;
    _loaded = true;
    final f = File(_path);
    if (await f.exists()) {
      final text = await f.readAsString();
      final obj = await openValue(_storageKey, text);
      if (obj is Map) {
        final own = obj['own'] as Map? ?? {};
        for (final e in own.entries) {
          _own[int.parse(e.key as String)] =
              SenderChainState.fromDict(e.value as Map<String, dynamic>);
        }
        final roster = obj['roster'] as Map? ?? {};
        for (final e in roster.entries) {
          _roster[int.parse(e.key as String)] = e.value as String;
        }
        final peers = obj['peers'] as Map? ?? {};
        for (final e in peers.entries) {
          final raw = e.value;
          final loaded = <SenderChainState>[];
          if (raw is List) {
            for (final c in raw) {
              if (c is Map<String, dynamic>) {
                loaded.add(SenderChainState.fromDict(c));
              }
            }
          } else if (raw is Map<String, dynamic>) {
            loaded.add(SenderChainState.fromDict(raw));
          }
          if (loaded.isNotEmpty) _peers[e.key as String] = loaded;
        }
      }
    }
  }

  Future<void> _flush() async {
    final map = {
      'own': {for (final e in _own.entries) e.key.toString(): e.value.toDict()},
      'roster': {for (final e in _roster.entries) e.key.toString(): e.value},
      'peers': {
        for (final e in _peers.entries)
          e.key: [for (final c in e.value) c.toDict()],
      },
    };
    final sealed = await seal(_storageKey, map);
    final f = File(_path);
    await f.parent.create(recursive: true);
    await f.writeAsString(sealed);
  }

  @override
  Future<SenderChainState?> getOwn(int roomId) async {
    await _ensureLoaded();
    return _own[roomId];
  }

  @override
  Future<void> putOwn(int roomId, SenderChainState state) async {
    await _ensureLoaded();
    _own[roomId] = state;
    await _flush();
  }

  @override
  Future<String?> getRoster(int roomId) async {
    await _ensureLoaded();
    return _roster[roomId];
  }

  @override
  Future<void> putRoster(int roomId, String digest) async {
    await _ensureLoaded();
    _roster[roomId] = digest;
    await _flush();
  }

  @override
  Future<SenderChainState?> getPeer(int roomId, String sender, int generation) async {
    await _ensureLoaded();
    for (final c in _peers[_peerKey(roomId, sender)] ?? const []) {
      if (c.generation == generation) return c;
    }
    return null;
  }

  @override
  Future<void> putPeer(int roomId, String sender, SenderChainState state) async {
    await _ensureLoaded();
    final key = _peerKey(roomId, sender);
    final chains = [
      for (final c in _peers[key] ?? const <SenderChainState>[])
        if (c.generation != state.generation) c,
      state,
    ]..sort((a, b) => a.generation.compareTo(b.generation));
    _peers[key] = chains.length > _keepGenerations
        ? chains.sublist(chains.length - _keepGenerations)
        : chains;
    await _flush();
  }
}
