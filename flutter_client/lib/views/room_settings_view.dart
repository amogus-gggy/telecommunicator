import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';

class RoomSettingsView extends StatefulWidget {
  const RoomSettingsView({super.key, required this.state, required this.room});
  final AppState state;
  final RoomDTO room;

  @override
  State<RoomSettingsView> createState() => _RoomSettingsViewState();
}

class _RoomSettingsViewState extends State<RoomSettingsView> {
  late bool _allowInvite = widget.room.allowMemberInvite;
  late bool _readOnly = widget.room.readOnly;
  bool _busy = false;

  bool get _isOwner {
    final user = widget.state.currentUser;
    return user != null && widget.room.ownerUsername == user.username;
  }

  bool get _isPersonal => widget.room.roomType == 'personal';

  Future<void> _save() async {
    if (_isPersonal || !_isOwner) return;
    setState(() => _busy = true);
    try {
      await ApiClient(state: widget.state).updatePermissions(
        widget.room.id,
        allowMemberInvite: _allowInvite,
        readOnly: _readOnly,
      );
      if (!mounted) return;
      setState(() => _busy = false);
      showSnack(context, L10n.t('room_settings.permissions_updated'));
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showSnack(context, e.toString(), ok: false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final Widget body;
    if (_isPersonal) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            L10n.t('room_settings.personal_auto'),
            style: const TextStyle(color: AppColors.onSurfaceVariant),
            textAlign: TextAlign.center,
          ),
        ),
      );
    } else if (!_isOwner) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            L10n.t('room_settings.only_owner_access'),
            style: const TextStyle(color: AppColors.onSurfaceVariant),
            textAlign: TextAlign.center,
          ),
        ),
      );
    } else {
      body = ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(L10n.t('room_settings.permissions'),
              style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: AppColors.onSurfaceVariant)),
          const SizedBox(height: 8),
          Card(
            child: SwitchListTile(
              title: Text(L10n.t('room_settings.allow_invite')),
              value: _allowInvite,
              onChanged: (v) => setState(() => _allowInvite = v),
            ),
          ),
          Card(
            child: SwitchListTile(
              title: Text(L10n.t('room_settings.read_only')),
              value: _readOnly,
              onChanged: (v) => setState(() => _readOnly = v),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _busy ? null : _save,
            icon: const Icon(Icons.save),
            label: Text(_busy ? L10n.t('room.loading') : L10n.t('profile.save')),
          ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(L10n.t('room_settings.title', {'name': widget.room.name})),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: body,
    );
  }
}
