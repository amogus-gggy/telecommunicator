import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';

class AdminView extends StatefulWidget {
  const AdminView({super.key, required this.state});
  final AppState state;

  @override
  State<AdminView> createState() => _AdminViewState();
}

class _AdminViewState extends State<AdminView> {
  bool _busy = true;
  String? _error;
  Map<String, dynamic>? _stats;
  List<dynamic> _users = const [];
  List<dynamic> _rooms = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  ApiClient get _client => ApiClient(state: widget.state);

  Future<void> _load() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final stats = await _client.adminStats();
      final users = await _client.adminUsers();
      final rooms = await _client.adminRooms();
      if (!mounted) return;
      setState(() {
        _stats = stats;
        _users = users;
        _rooms = rooms;
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin panel'),
        actions: [IconButton(icon: const Icon(Icons.refresh), onPressed: _load)],
      ),
      body: _busy
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (_stats != null) ...[
                      Text('Server: ${_stats!['server_name']}',
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                      Text('Users: ${_stats!['users']}  '
                          '(local: ${_stats!['local_users']})  '
                          'Rooms: ${_stats!['rooms']}  '
                          'Messages: ${_stats!['messages']}'),
                      const SizedBox(height: 16),
                    ],
                    const Text('Users',
                        style:
                            TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const Divider(),
                    ..._users.map((u) {
                      final user = u as Map<String, dynamic>;
                      final isMe =
                          user['id'] == widget.state.currentUser?.id;
                      return ListTile(
                        leading: initialsAvatar(
                            context, user['username'] as String, size: 40),
                        title: Text(user['username'] as String),
                        subtitle: Text(user['email'] as String),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (user['is_admin'] == true)
                              const Padding(
                                padding: EdgeInsets.only(right: 4),
                                child: Icon(Icons.verified_user, size: 18),
                              ),
                            if (!isMe && user['is_remote'] != true) ...[
                              IconButton(
                                icon: Icon(
                                  user['is_admin'] == true
                                      ? Icons.person_remove
                                      : Icons.admin_panel_settings,
                                  size: 20,
                                ),
                                onPressed: () async {
                                  await _client.adminSetAdmin(
                                      user['id'] as int,
                                      !(user['is_admin'] == true));
                                  await _load();
                                },
                              ),
                              IconButton(
                                icon: const Icon(Icons.delete, size: 20),
                                onPressed: () async {
                                  await _client.adminDeleteUser(user['id'] as int);
                                  await _load();
                                },
                              ),
                            ],
                          ],
                        ),
                      );
                    }),
                    const SizedBox(height: 16),
                    const Text('Rooms',
                        style:
                            TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const Divider(),
                    ..._rooms.map((r) {
                      final room = r as Map<String, dynamic>;
                      return ListTile(
                        leading: initialsAvatar(
                            context, room['name'] as String, size: 40),
                        title: Text(room['name'] as String),
                        subtitle: Text(
                            "${room['room_type']} · ${room['member_count']} members"
                            "${room['owner_username'] != null ? " · ${room['owner_username']}" : ""}"),
                      );
                    }),
                  ],
                ),
    );
  }
}
