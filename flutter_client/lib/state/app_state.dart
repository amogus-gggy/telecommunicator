/// Global application state (mirrors the Python client's `state.py`).
library;

import 'package:flutter/foundation.dart';

import '../api/ws_client.dart';
import '../config.dart';
import '../crypto/at_rest.dart';
import '../crypto/key_cache.dart';
import '../crypto/message_store.dart';
import '../crypto/ratchet_session_store.dart';
import '../crypto/sender_key_store.dart';
import '../storage/settings.dart';

class AppState extends ChangeNotifier {
  AppState({
    this.apiUrl = defaultApiUrl,
    this.wsUrl = defaultWsUrl,
    this.themeMode = 'system',
    this.messageAlignment = 'default',
    this.settings,
  });

  String apiUrl;
  String wsUrl;
  String? token;
  UserDTO? currentUser;
  RoomDTO? activeRoom;
  String themeMode;
  String messageAlignment;
  final SettingsStore? settings;

  UnifiedWsClient? ws;
  CryptoKeys? crypto;
  PublicKeyCache? publicKeyCache;
  RatchetSessionStore? ratchetStore;
  SenderKeyStore? senderKeyStore;
  MessageStore? messageStore;

  /// Aliases (single unified connection).
  UnifiedWsClient? get roomWs => ws;
  set roomWs(UnifiedWsClient? v) => ws = v;
  UnifiedWsClient? get notifWs => ws;
  set notifWs(UnifiedWsClient? v) => ws = v;

  void Function(String)? onAlignmentChange;

  bool get hasE2ee =>
      crypto != null &&
      ratchetStore != null &&
      senderKeyStore != null &&
      publicKeyCache != null &&
      currentUser != null;

  set messageAlignmentSet(String v) {
    messageAlignment = v;
    onAlignmentChange?.call(v);
    settings?.set('settings.message_alignment', v);
    notifyListeners();
  }

  void setThemeMode(String v) {
    themeMode = v;
    settings?.set('settings.theme_mode', v);
    notifyListeners();
  }

  void setMessageAlignment(String v) {
    messageAlignment = v;
    settings?.set('settings.message_alignment', v);
    notifyListeners();
  }

  /// Build the encrypted-at-rest crypto stores for this account.
  Future<void> initCryptoStores(String supportDir, String account) async {
    if (crypto == null) return;
    final key = await deriveStorageKey(crypto!.x25519Private, account, 'store');
    final k = key.toList();
    ratchetStore = FileRatchetSessionStore('$supportDir/ratchet.json', k);
    senderKeyStore = FileSenderKeyStore('$supportDir/sender_keys.json', k);
    messageStore = FileMessageStore('$supportDir/messages.json', k);
    publicKeyCache = PublicKeyCache();
  }

  void clearCryptoKeys() {
    crypto = null;
    publicKeyCache = null;
    ratchetStore = null;
    senderKeyStore = null;
    messageStore = null;
  }

  void closeWs() {
    ws?.close();
    ws = null;
  }

  Future<void> logout() async {
    closeWs();
    clearCryptoKeys();
    token = null;
    currentUser = null;
    activeRoom = null;
  }
}
