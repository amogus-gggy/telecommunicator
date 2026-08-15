/// Sender-key group store (persisted encrypted at rest).
///
/// Holds, per room: the local user's sending chain, the roster digest, and a
/// map of (sender handle, generation) -> receive chain.
library;

import 'dart:io';

import 'at_rest.dart';
import 'sender_keys.dart';

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
  final Map<String, SenderChainState> _peers = {}; // key: "$roomId|$sender|$gen"
  bool _loaded = false;

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
          _peers[e.key as String] =
              SenderChainState.fromDict(e.value as Map<String, dynamic>);
        }
      }
    }
  }

  Future<void> _flush() async {
    final map = {
      'own': {for (final e in _own.entries) e.key.toString(): e.value.toDict()},
      'roster': {for (final e in _roster.entries) e.key.toString(): e.value},
      'peers': {for (final e in _peers.entries) e.key: e.value.toDict()},
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
    return _peers['$roomId|$sender|$generation'];
  }

  @override
  Future<void> putPeer(int roomId, String sender, SenderChainState state) async {
    await _ensureLoaded();
    _peers['$roomId|$sender|${state.generation}'] = state;
    await _flush();
  }
}
