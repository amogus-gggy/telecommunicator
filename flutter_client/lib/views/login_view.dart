import 'dart:convert';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../crypto/key_backup.dart';
import '../crypto/keys.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';
import 'chat_list_view.dart';
import 'register_view.dart';

class LoginView extends StatefulWidget {
  const LoginView({super.key, required this.state});
  final AppState state;

  @override
  State<LoginView> createState() => _LoginViewState();
}

class _LoginViewState extends State<LoginView> {
  final _usernameCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _usernameCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _doLogin() async {
    final state = widget.state;
    setState(() {
      _busy = true;
      _error = null;
    });

    final handle = _usernameCtrl.text.trim();
    final (username, server) = parseHandle(handle);
    if (handle.contains('@') && server == null) {
      setState(() {
        _busy = false;
        _error = L10n.t('login.error_handle_format');
      });
      return;
    }

    if (server != null) {
      try {
        final (api, ws) = buildApiUrls(server);
        if (api != state.apiUrl) {
          state.apiUrl = api;
          state.wsUrl = ws;
          await state.settings?.set('settings.api_url', api);
          await state.settings?.set('settings.ws_url', ws);
          await closeSharedClients();
        }
      } catch (_) {
        setState(() {
          _busy = false;
          _error = L10n.t('login.error_handle_format');
        });
        return;
      }
    }

    final client = ApiClient(state: state);
    try {
      final tokenData = await client.login(username, _passwordCtrl.text);
      state.token = tokenData['access_token'] as String;

      final backupB64 = tokenData['encrypted_backup'] as String?;
      if (backupB64 != null && backupB64.isNotEmpty) {
        try {
          final (ed25519Priv, x25519Priv) = await KeyBackupManager.decryptBackup(
            base64Decode(backupB64),
            _passwordCtrl.text,
          );
          state.crypto = CryptoKeys(
            ed25519Private: ed25519Priv,
            ed25519Public: await ed25519PublicBytes(ed25519Priv),
            x25519Private: x25519Priv,
            x25519Public: await x25519PublicBytes(x25519Priv),
          );
        } catch (_) {
          setState(() {
            _busy = false;
            _error = L10n.t('login.error_backup_decrypt');
          });
          return;
        }
      } else {
        setState(() {
          _busy = false;
          _error = L10n.t('login.error_no_backup');
        });
        return;
      }

      final me = await client.getMe();
      state.currentUser = UserDTO.fromJson(me);

      await state.settings?.set('auth.token', state.token!);

      final settings = state.settings;
      if (settings != null) {
        final supportDir = await settings.supportDir();
        await state.initCryptoStores(supportDir, state.currentUser!.username);
      }

      if (!mounted) return;
      navigateReplacing(context, ChatListView(state: state));
    } on AuthError {
      setState(() {
        _busy = false;
        _error = L10n.t('login.error_invalid');
      });
    } catch (e) {
      final s = e.toString();
      setState(() {
        _busy = false;
        _error = s.isEmpty
            ? L10n.t('login.error_unknown')
            : (s.contains('SocketException') || s.contains('Connection')
                ? L10n.t('login.error_connect')
                : L10n.t('login.error_server', {'exc': s}));
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.surfaceContainer,
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Container(
            width: 360,
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppColors.outlineVariant),
              boxShadow: const [
                BoxShadow(
                  blurRadius: 24,
                  spreadRadius: -4,
                  color: Color(0x1A000000),
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                initialsAvatar('Telecommunicator', size: 72),
                const SizedBox(height: 12),
                const Text('Telecommunicator',
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                Text(
                  L10n.t('login.subtitle'),
                  style: const TextStyle(fontSize: 14, color: AppColors.onSurfaceVariant),
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: _usernameCtrl,
                  autofocus: true,
                  decoration: themedFieldDecoration(
                    label: L10n.t('login.username'),
                    hintText: L10n.t('login.username_hint'),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _passwordCtrl,
                  obscureText: true,
                  decoration: themedFieldDecoration(label: L10n.t('login.password')),
                  onSubmitted: (_) => _doLogin(),
                ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      _error!,
                      style: const TextStyle(fontSize: 13, color: AppColors.error),
                    ),
                  ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    primaryButton(
                      L10n.t('login.submit'),
                      onPressed: _busy ? null : _doLogin,
                    ),
                    const SizedBox(width: 12),
                    if (_busy)
                      const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                  ],
                ),
                TextButton(
                  onPressed: () {
                    Navigator.of(context).pushReplacement(
                      MaterialPageRoute(
                        builder: (_) =>
                            RegisterView(state: widget.state),
                      ),
                    );
                  },
                  child: Text(L10n.t('login.no_account'),
                      style: const TextStyle(color: AppColors.primary)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
