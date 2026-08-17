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
import 'login_view.dart';

class RegisterView extends StatefulWidget {
  const RegisterView({super.key, required this.state});
  final AppState state;

  @override
  State<RegisterView> createState() => _RegisterViewState();
}

class _RegisterViewState extends State<RegisterView> {
  final _usernameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _busy = false;
  String? _usernameError;
  String? _emailError;
  String? _passwordError;
  String? _generalError;

  @override
  void dispose() {
    _usernameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  void _clearErrors() {
    setState(() {
      _usernameError = null;
      _emailError = null;
      _passwordError = null;
      _generalError = null;
    });
  }

  Future<void> _doRegister() async {
    final state = widget.state;
    _clearErrors();
    setState(() => _busy = true);

    final handle = _usernameCtrl.text.trim();
    final (username, server) = parseHandle(handle);
    if (handle.contains('@') && server == null) {
      setState(() {
        _busy = false;
        _generalError = L10n.t('register.error_username_format');
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
          _generalError = L10n.t('register.error_username_format');
        });
        return;
      }
    }

    final client = ApiClient(state: state);
    try {
      final (edPriv, edPub) = await generateEd25519Keypair();
      final (xPriv, xPub) = await generateX25519Keypair();

      final encryptedBackup = await KeyBackupManager.encryptBackup(
        edPriv, xPriv, _passwordCtrl.text);

      await client.register(
        username: username,
        email: _emailCtrl.text,
        password: _passwordCtrl.text,
        identityPubEd25519: base64Encode(edPub),
        identityPubX25519: base64Encode(xPub),
        encryptedBackup: base64Encode(encryptedBackup),
      );

      state.crypto = CryptoKeys(
        ed25519Private: edPriv,
        ed25519Public: edPub,
        x25519Private: xPriv,
        x25519Public: xPub,
      );

      final tokenData = await client.login(username, _passwordCtrl.text);
      state.token = tokenData['access_token'] as String;
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
    } on ConflictError catch (e) {
      final msg = e.message.toLowerCase();
      setState(() {
        _busy = false;
        if (msg.contains('username')) {
          _usernameError = e.message;
        } else if (msg.contains('email')) {
          _emailError = e.message;
        } else {
          _generalError = e.message;
        }
      });
    } on ValidationError catch (e) {
      final msg = e.message.toLowerCase();
      setState(() {
        _busy = false;
        if (msg.contains('password')) {
          _passwordError = e.message;
        } else if (msg.contains('email')) {
          _emailError = e.message;
        } else if (msg.contains('username')) {
          _usernameError = e.message;
        } else {
          _generalError = e.message;
        }
      });
    } on Exception catch (e) {
      final s = e.toString();
      setState(() {
        _busy = false;
        _generalError = s.isEmpty
            ? L10n.t('register.error_server', const {})
            : (s.toLowerCase().contains('cryptographic')
                ? L10n.t('register.error_crypto', {'exc': s})
                : L10n.t('register.error_server', {'exc': s}));
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.surfaceContainer,
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Container(
            width: 360,
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: context.surface,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: context.outlineVariant),
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
                initialsAvatar(context, 'Telecommunicator', size: 64),
                const SizedBox(height: 10),
                const Text('Telecommunicator',
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                Text(
                  L10n.t('register.subtitle'),
                  style: TextStyle(fontSize: 14, color: context.onSurfaceVariant),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _usernameCtrl,
                  autofocus: true,
                  decoration: themedFieldDecoration(
                    label: L10n.t('register.username'),
                    hintText: L10n.t('register.username_hint'),
                  ),
                ),
                if (_usernameError != null)
                  Text(_usernameError!,
                      style: TextStyle(fontSize: 12, color: context.error)),
                const SizedBox(height: 8),
                TextField(
                  controller: _emailCtrl,
                  decoration: themedFieldDecoration(label: L10n.t('register.email')),
                ),
                if (_emailError != null)
                  Text(_emailError!,
                      style: TextStyle(fontSize: 12, color: context.error)),
                const SizedBox(height: 8),
                TextField(
                  controller: _passwordCtrl,
                  obscureText: true,
                  decoration:
                      themedFieldDecoration(label: L10n.t('register.password')),
                  onSubmitted: (_) => _doRegister(),
                ),
                if (_passwordError != null)
                  Text(_passwordError!,
                      style: TextStyle(fontSize: 12, color: context.error)),
                if (_generalError != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(_generalError!,
                        style: TextStyle(color: context.error)),
                  ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    primaryButton(
                      context,
                      L10n.t('register.submit'),
                      onPressed: _busy ? null : _doRegister,
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
                        builder: (_) => LoginView(state: widget.state),
                      ),
                    );
                  },
                  child: Text(L10n.t('register.have_account'),
                      style: TextStyle(color: context.primary)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
