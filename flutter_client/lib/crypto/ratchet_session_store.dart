/// Per-peer Double Ratchet session store (persisted encrypted at rest).
library;

import 'dart:io';

import 'at_rest.dart';
import 'double_ratchet.dart';

abstract class RatchetSessionStore {
  Future<RatchetState?> get(String peerKey);
  Future<void> put(String peerKey, RatchetState state);
  Future<void> delete(String peerKey);
}

/// In-memory store (kept for tests / transient sessions).
class MemoryRatchetSessionStore implements RatchetSessionStore {
  final Map<String, RatchetState> _m = {};
  @override
  Future<RatchetState?> get(String k) async => _m[k];
  @override
  Future<void> put(String k, RatchetState s) async => _m[k] = s;
  @override
  Future<void> delete(String k) async => _m.remove(k);
}

/// Encrypted-on-disk store. The in-memory map is the source of truth; every
/// mutation is flushed (sealed) to a JSON file under the identity key.
class FileRatchetSessionStore implements RatchetSessionStore {
  FileRatchetSessionStore(this._path, this._storageKey);

  final String _path;
  final List<int> _storageKey;
  final Map<String, RatchetState> _cache = {};
  bool _loaded = false;

  Future<void> _ensureLoaded() async {
    if (_loaded) return;
    _loaded = true;
    final f = File(_path);
    if (await f.exists()) {
      final text = await f.readAsString();
      final obj = await openValue(_storageKey, text);
      if (obj is Map) {
        for (final e in obj.entries) {
          try {
            _cache[e.key as String] = RatchetState.fromDict(e.value as Map<String, dynamic>);
          } catch (_) {
            // skip corrupt entry
          }
        }
      }
    }
  }

  Future<void> _flush() async {
    final map = {
      for (final e in _cache.entries) e.key: e.value.toDict(),
    };
    final sealed = await seal(_storageKey, map);
    final f = File(_path);
    await f.parent.create(recursive: true);
    await f.writeAsString(sealed);
  }

  @override
  Future<RatchetState?> get(String peerKey) async {
    await _ensureLoaded();
    return _cache[peerKey];
  }

  @override
  Future<void> put(String peerKey, RatchetState state) async {
    await _ensureLoaded();
    _cache[peerKey] = state;
    await _flush();
  }

  @override
  Future<void> delete(String peerKey) async {
    await _ensureLoaded();
    _cache.remove(peerKey);
    await _flush();
  }
}
