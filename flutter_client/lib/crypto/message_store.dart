/// Plaintext message store (encrypted at rest) — caches decrypted message
/// bodies so history re-renders without re-consuming ratchet message keys.
library;

import 'dart:io';

import 'at_rest.dart';

abstract class MessageStore {
  Future<String?> get(int messageId);
  Future<void> put(int messageId, String plaintext);
}

class FileMessageStore implements MessageStore {
  FileMessageStore(this._path, this._storageKey);

  final String _path;
  final List<int> _storageKey;
  final Map<int, String> _cache = {};
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
          _cache[int.parse(e.key as String)] = e.value as String;
        }
      }
    }
  }

  Future<void> _flush() async {
    final sealed = await seal(_storageKey,
        {for (final e in _cache.entries) e.key.toString(): e.value});
    final f = File(_path);
    await f.parent.create(recursive: true);
    await f.writeAsString(sealed);
  }

  @override
  Future<String?> get(int messageId) async {
    await _ensureLoaded();
    return _cache[messageId];
  }

  @override
  Future<void> put(int messageId, String plaintext) async {
    await _ensureLoaded();
    _cache[messageId] = plaintext;
    await _flush();
  }
}
