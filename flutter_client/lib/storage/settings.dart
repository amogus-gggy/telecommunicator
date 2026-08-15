/// Persistent settings storage (SharedPreferences) plus helpers for the
/// on-disk crypto store directory.
library;

import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsStore {
  SettingsStore(this._prefs);

  final SharedPreferences _prefs;

  static Future<SettingsStore> load() async {
    final prefs = await SharedPreferences.getInstance();
    return SettingsStore(prefs);
  }

  String? get(String key) => _prefs.getString(key);
  Future<void> set(String key, String value) => _prefs.setString(key, value);
  Future<void> remove(String key) => _prefs.remove(key);

  Future<String> supportDir() async {
    final dir = await getApplicationSupportDirectory();
    final path = Directory('${dir.path}/crypto');
    await path.create(recursive: true);
    return path.path;
  }
}
