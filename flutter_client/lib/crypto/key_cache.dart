/// In-memory cache of peers' public keys (identity Ed25519 + X25519).
library;

class PublicKeyEntry {
  PublicKeyEntry({
    required this.ed25519Pub,
    required this.x25519Pub,
    this.userId,
  });

  final List<int> ed25519Pub;
  final List<int> x25519Pub;
  final String? userId;
}

class PublicKeyCache {
  final Map<String, PublicKeyEntry> _cache = {};

  PublicKeyEntry? get(String username) => _cache[username];

  void set(String username, List<int> ed25519Pub, List<int> x25519Pub,
      [String? userId]) {
    _cache[username] = PublicKeyEntry(
      ed25519Pub: ed25519Pub,
      x25519Pub: x25519Pub,
      userId: userId,
    );
  }

  void clear() => _cache.clear();
}
