import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';
import 'login_view.dart';

class ProfileView extends StatefulWidget {
  const ProfileView({super.key, required this.state});
  final AppState state;

  @override
  State<ProfileView> createState() => _ProfileViewState();
}

class _ProfileViewState extends State<ProfileView> {
  final _displayNameCtrl = TextEditingController();
  final _currentPwCtrl = TextEditingController();
  final _newPwCtrl = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _displayNameCtrl.dispose();
    _currentPwCtrl.dispose();
    _newPwCtrl.dispose();
    super.dispose();
  }

  Future<void> _updateDisplayName() async {
    final user = widget.state.currentUser;
    if (user == null) return;

    final name = _displayNameCtrl.text.trim();
    if (name.isEmpty || name.length > 64) {
      showSnack(context, L10n.t('profile.display_name_error'), ok: false);
      return;
    }
    setState(() => _busy = true);
    try {
      final me = await ApiClient(state: widget.state).updateProfile(name);
      widget.state.currentUser = UserDTO(
        id: user.id,
        username: user.username,
        email: user.email,
        displayName: me['display_name'] as String?,
        serverName: user.serverName,
      );
      if (!mounted) return;
      setState(() => _busy = false);
      showSnack(context, L10n.t('profile.display_name_updated'));
      _displayNameCtrl.clear();
    } on AuthError {
      if (!mounted) return;
      setState(() => _busy = false);
      await widget.state.logout();
      await widget.state.settings?.remove('auth.token');
      if (!mounted) return;
      showSnack(context, L10n.t('profile.session_expired'), ok: false);
      navigateClearStack(context, LoginView(state: widget.state));
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showSnack(context, e.toString(), ok: false);
    }
  }

  Future<void> _changePassword() async {
    if (_newPwCtrl.text.length < 8) {
      showSnack(context, L10n.t('profile.password_too_short'), ok: false);
      return;
    }
    setState(() => _busy = true);
    try {
      await ApiClient(state: widget.state)
          .changePassword(_currentPwCtrl.text, _newPwCtrl.text);
      if (!mounted) return;
      setState(() => _busy = false);
      _currentPwCtrl.clear();
      _newPwCtrl.clear();
      showSnack(context, L10n.t('profile.password_changed'));
    } on AuthError {
      if (!mounted) return;
      setState(() => _busy = false);
      showSnack(context, L10n.t('profile.password_incorrect'), ok: false);
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      final msg = e.toString().toLowerCase();
      showSnack(
        context,
        msg.contains('incorrect') || msg.contains('current')
            ? L10n.t('profile.password_incorrect')
            : e.toString(),
        ok: false,
      );
    }
  }

  Future<void> _setAlignment(String v) async {
    widget.state.setMessageAlignment(v);
    if (mounted) setState(() {});
  }

  Future<void> _setTheme(String v) async {
    widget.state.setThemeMode(v);
    if (mounted) setState(() {});
  }

  Future<void> _logout() async {
    await widget.state.logout();
    await widget.state.settings?.remove('auth.token');
    if (!mounted) return;
    navigateClearStack(context, LoginView(state: widget.state));
  }

  Widget _radioTile({
    required String title,
    required String value,
    required String groupValue,
    required ValueChanged<String?> onChanged,
  }) {
    return RadioListTile<String>(
      title: Text(title),
      value: value,
      groupValue: groupValue,
      onChanged: onChanged,
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.state.currentUser;
    if (user == null) {
      return Scaffold(
        appBar: AppBar(
          title: Text(L10n.t('profile.title')),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ),
        body: Center(child: Text(L10n.t('profile.session_expired'))),
      );
    }

    final handle = user.serverName.isNotEmpty
        ? '${user.username}@${user.serverName}'
        : user.username;

    return Scaffold(
      appBar: AppBar(
        title: Text(L10n.t('profile.title')),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Center(
            child: Column(
              children: [
                initialsAvatar(
                  user.displayName ?? user.username,
                  size: 64,
                ),
                const SizedBox(height: 8),
                Text(
                  user.displayName ?? user.username,
                  style: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.bold),
                ),
                Text(handle,
                    style: const TextStyle(color: AppColors.onSurfaceVariant)),
              ],
            ),
          ),
          const SizedBox(height: 24),
          Text(L10n.t('profile.account_info'),
              style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              title: Text(L10n.t('profile.username', {'username': user.username})),
            ),
          ),
          Card(
            child: ListTile(
              title: Text(L10n.t('profile.email', {'email': user.email})),
            ),
          ),
          Card(
            child: ListTile(
              title: Text(L10n.t('profile.display_name_label',
                  {'name': user.displayName ?? L10n.t('profile.display_name_not_set')})),
            ),
          ),
          const SizedBox(height: 16),
          Text(L10n.t('profile.update_display_name'),
              style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _displayNameCtrl,
                      decoration: themedFieldDecoration(
                          label: L10n.t('profile.new_display_name')),
                    ),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _busy ? null : _updateDisplayName,
                    child: Text(L10n.t('profile.save')),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(L10n.t('profile.change_password'),
              style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  TextField(
                    controller: _currentPwCtrl,
                    obscureText: true,
                    decoration:
                        themedFieldDecoration(label: L10n.t('profile.current_password')),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _newPwCtrl,
                    obscureText: true,
                    decoration:
                        themedFieldDecoration(label: L10n.t('profile.new_password')),
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton(
                      onPressed: _busy ? null : _changePassword,
                      child: Text(L10n.t('profile.save')),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(L10n.t('profile.message_alignment'),
              style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: Column(
              children: [
                _radioTile(
                  title: L10n.t('profile.alignment_default'),
                  value: 'default',
                  groupValue: widget.state.messageAlignment,
                  onChanged: (v) => _setAlignment(v ?? 'default'),
                ),
                _radioTile(
                  title: L10n.t('profile.alignment_left'),
                  value: 'left',
                  groupValue: widget.state.messageAlignment,
                  onChanged: (v) => _setAlignment(v ?? 'default'),
                ),
                _radioTile(
                  title: L10n.t('profile.alignment_right'),
                  value: 'right',
                  groupValue: widget.state.messageAlignment,
                  onChanged: (v) => _setAlignment(v ?? 'default'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Text(L10n.t('theme.title'),
              style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: Column(
              children: [
                _radioTile(
                  title: L10n.t('theme.system'),
                  value: 'system',
                  groupValue: widget.state.themeMode,
                  onChanged: (v) => _setTheme(v ?? 'system'),
                ),
                _radioTile(
                  title: L10n.t('theme.light'),
                  value: 'light',
                  groupValue: widget.state.themeMode,
                  onChanged: (v) => _setTheme(v ?? 'system'),
                ),
                _radioTile(
                  title: L10n.t('theme.dark'),
                  value: 'dark',
                  groupValue: widget.state.themeMode,
                  onChanged: (v) => _setTheme(v ?? 'system'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          FilledButton.tonal(
            onPressed: _logout,
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.error,
              foregroundColor: Colors.white,
            ),
            child: Text(L10n.t('chat_list.logout')),
          ),
        ],
      ),
    );
  }
}
