import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/ws_client.dart';
import '../config.dart';
import '../l10n/strings.dart';
import '../state/app_state.dart';
import '../ui/theme.dart';
import 'login_view.dart';
import 'profile_view.dart';
import 'room_view.dart';

class ChatListView extends StatefulWidget {
  const ChatListView({super.key, required this.state});
  final AppState state;

  @override
  State<ChatListView> createState() => _ChatListViewState();
}

class _ChatListViewState extends State<ChatListView>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController =
      TabController(length: 3, vsync: this);
  late final TextEditingController _searchCtrl = TextEditingController();

  final List<Map<String, dynamic>> _personal = [];
  final List<Map<String, dynamic>> _groups = [];
  final List<Map<String, dynamic>> _public = [];

  Timer? _searchDebounce;
  UnifiedWsClient? _ws;

  final _usernameCtrl = TextEditingController();
  final _groupNameCtrl = TextEditingController();
  bool _publicGroup = false;
  String? _personalError;
  String? _groupError;

  @override
  void initState() {
    super.initState();
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) setState(() {});
    });
    _loadChats();
    _startNotifications();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _searchCtrl.dispose();
    _usernameCtrl.dispose();
    _groupNameCtrl.dispose();
    _searchDebounce?.cancel();
    // Don't close the WS — room_view reuses it. Just clear callbacks.
    _ws?.onNotification = null;
    _ws?.onRoomMessage = null;
    super.dispose();
  }

  String _displayName(Map<String, dynamic> room) {
    if (room['room_type'] == 'personal') {
      final my = widget.state.currentUser?.username ?? '';
      final counterpart = (room['participants'] as List? ?? []).cast<String>()
          .where((p) => p.split('@').first != my)
          .firstOrNull;
      if (counterpart != null) return counterpart;
      final name = room['name'] as String? ?? '';
      if (my.isNotEmpty && name.contains(my)) {
        final parts = name.split(', ');
        return parts.where((p) => p != my).firstOrNull ?? name;
      }
      return name;
    }
    return room['name'] as String? ?? '';
  }

  Future<void> _loadChats() async {
    final client = ApiClient(state: widget.state);
    try {
      final myChats = await client.getMyRooms();
      final public = await client.listRooms();
      if (!mounted) return;
      setState(() {
        _personal
          ..clear()
          ..addAll(myChats.whereType<Map<String, dynamic>>().where(
              (r) => r['room_type'] == 'personal'));
        _groups
          ..clear()
          ..addAll(myChats.whereType<Map<String, dynamic>>().where(
              (r) => r['room_type'] == 'group'));
        _public
          ..clear()
          ..addAll(public.whereType<Map<String, dynamic>>());
      });
    } catch (e) {
      if (mounted) showSnack(context, e.toString(), ok: false);
    }
  }

  Future<void> _createPersonalChat() async {
    setState(() => _personalError = null);
    final client = ApiClient(state: widget.state);
    try {
      final data = await client.createPersonalChat(_usernameCtrl.text.trim());
      final room = RoomDTO.fromJson(Map<String, dynamic>.from(data as Map));
      if (!mounted) return;
      Navigator.of(context).pop(); // close dialog
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => RoomView(state: widget.state, room: room),
      ));
    } catch (e) {
      if (!mounted) return;
      setState(() => _personalError = e.toString());
    }
  }

  Future<void> _createGroupChat() async {
    setState(() => _groupError = null);
    final client = ApiClient(state: widget.state);
    try {
      final roomType = _publicGroup ? 'public' : 'group';
      final data = await client.createRoom(
        _groupNameCtrl.text.trim(),
        roomType,
        !_publicGroup,
      );
      final room = RoomDTO.fromJson(Map<String, dynamic>.from(data as Map));
      if (!mounted) return;
      Navigator.of(context).pop();
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => RoomView(state: widget.state, room: room),
      ));
    } catch (e) {
      if (!mounted) return;
      setState(() => _groupError = e.toString());
    }
  }

  void _openRoom(Map<String, dynamic> r) {
    final room = RoomDTO.fromJson(Map<String, dynamic>.from(r));
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => RoomView(state: widget.state, room: room),
    ));
  }

  void _startNotifications() {
    if (widget.state.ws != null) {
      widget.state.ws!.onNotification = _onNotification;
      _ws = widget.state.ws;
      return;
    }
    final ws = UnifiedWsClient(
      token: widget.state.token ?? '',
      onNotification: _onNotification,
      wsUrl: widget.state.wsUrl,
    );
    widget.state.ws = ws;
    _ws = ws;
    ws.connect(widget.state.wsUrl).catchError((_) {});
  }

  void _onNotification(Map<String, dynamic> payload) {
    if (!mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final type = payload['type'];
      if (type == 'invite') {
        final name = (payload['payload'] as Map? ?? {})['name'] ?? '';
        showSnack(context, L10n.t('chat_list.invited', {'room': name}));
        _loadChats();
      } else if (type == 'member_joined') {
        final data = payload['payload'] as Map? ?? {};
        final username = data['username'] ?? '';
        final roomName = data['room_name'] ?? '';
        showSnack(context,
            L10n.t('chat_list.member_joined', {'username': username, 'room': roomName}));
        _loadChats();
      }
    });
  }

  Future<void> _logout() async {
    await widget.state.logout();
    await widget.state.settings?.remove('auth.token');
    if (!mounted) return;
    navigateClearStack(context, LoginView(state: widget.state));
  }

  Widget _buildTile(Map<String, dynamic> room) {
    final name = _displayName(room);
    final type = room['room_type'] as String? ?? 'public';
    final icon = type == 'personal'
        ? Icons.person
        : type == 'group'
            ? Icons.group
            : Icons.public;

    final parts = <String>[];
    if (type != 'personal') {
      parts.add(L10n.t('chat_list.members_count', {'count': room['member_count'] ?? 0}));
    }
    if (room['is_private'] == true) parts.add(L10n.t('chat_list.private'));
    final subtitle = parts.isNotEmpty
        ? parts.join(' • ')
        : L10n.t('chat_list.chat');

    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () => _openRoom(room),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Stack(
              clipBehavior: Clip.none,
              children: [
                initialsAvatar(name, size: 44),
                Positioned(
                  right: 0,
                  bottom: 0,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Icon(icon, size: 12, color: Colors.white),
                  ),
                ),
              ],
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name,
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600)),
                  Text(subtitle,
                      style: const TextStyle(
                          fontSize: 12.5, color: AppColors.onSurfaceVariant)),
                ],
              ),
            ),
            const Icon(Icons.chevron_right,
                size: 20, color: AppColors.onSurfaceVariant),
          ],
        ),
      ),
    );
  }

  Widget _tabBody(List<Map<String, dynamic>> rooms, String emptyKey) {
    final q = _searchCtrl.text.trim().toLowerCase();
    final filtered = rooms.where((r) {
      if (q.isEmpty) return true;
      return _displayName(r).toLowerCase().contains(q) ||
          (r['name'] as String? ?? '').toLowerCase().contains(q);
    }).toList();

    if (filtered.isEmpty) {
      return Center(
        child: Text(
          L10n.t(emptyKey),
          style: const TextStyle(color: AppColors.onSurfaceVariant),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: filtered.length,
      itemBuilder: (_, i) => _buildTile(filtered[i]),
    );
  }

  String _loggedAs() {
    final user = widget.state.currentUser;
    if (user == null) return '';
    final handle = user.serverName.isNotEmpty
        ? '${user.username}@${user.serverName}'
        : user.username;
    return L10n.t('chat_list.logged_as', {'user': handle});
  }

  @override
  Widget build(BuildContext context) {
    final actions = _tabController.index == 0
        ? Icons.person_add
        : _tabController.index == 1
            ? Icons.group_add
            : null;

    return Scaffold(
      backgroundColor: AppColors.surfaceContainer,
      appBar: AppBar(
        backgroundColor: AppColors.surface,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Chats',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            Text(_loggedAs(),
                style: const TextStyle(
                    fontSize: 12, color: AppColors.onSurfaceVariant)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: L10n.t('chat_list.refresh'),
            onPressed: _loadChats,
          ),
          IconButton(
            icon: const Icon(Icons.person),
            tooltip: L10n.t('chat_list.profile'),
            onPressed: () {
              navigatePush(context, ProfileView(state: widget.state));
            },
          ),
          TextButton(
            onPressed: _logout,
            child: Text(L10n.t('chat_list.logout')),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: TextField(
              controller: _searchCtrl,
              decoration: themedFieldDecoration(
                hintText: L10n.t('chat_list.search'),
                prefixIcon: Icons.search,
              ),
              onChanged: (v) {
                _searchDebounce?.cancel();
                _searchDebounce =
                    Timer(const Duration(milliseconds: 300), () {
                  if (mounted) setState(() {});
                });
              },
            ),
          ),
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _tabBody(_personal, 'chat_list.no_personal'),
          _tabBody(_groups, 'chat_list.no_groups'),
          _tabBody(_public, 'chat_list.no_public'),
        ],
      ),
      bottomNavigationBar: Material(
        color: AppColors.surface,
        child: SafeArea(
          child: TabBar(
            controller: _tabController,
            tabs: [
              Tab(
                icon: const Icon(Icons.person),
                text: L10n.t('chat_list.tab_personal'),
              ),
              Tab(
                icon: const Icon(Icons.group),
                text: L10n.t('chat_list.tab_groups'),
              ),
              Tab(
                icon: const Icon(Icons.public),
                text: L10n.t('chat_list.tab_public'),
              ),
            ],
          ),
        ),
      ),
      floatingActionButton: actions == null
          ? null
          : FloatingActionButton.extended(
              onPressed: () {
                if (_tabController.index == 0) {
                  showDialog(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: Text(L10n.t('chat_list.new_personal_chat')),
                      content: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          TextField(
                            controller: _usernameCtrl,
                            autofocus: true,
                            decoration: themedFieldDecoration(
                                label: L10n.t('chat_list.username_field')),
                          ),
                          if (_personalError != null)
                            Text(_personalError!,
                                style: const TextStyle(
                                    color: AppColors.error, fontSize: 12)),
                        ],
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.of(ctx).pop(),
                          child: Text(L10n.t('chat_list.cancel')),
                        ),
                        FilledButton(
                          onPressed: _createPersonalChat,
                          child: Text(L10n.t('chat_list.create')),
                        ),
                      ],
                    ),
                  );
                } else if (_tabController.index == 1) {
                  showDialog(
                    context: context,
                    builder: (ctx) => StatefulBuilder(
                      builder: (ctx, setDialogState) => AlertDialog(
                        title: Text(L10n.t('chat_list.new_group_chat')),
                        content: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            TextField(
                              controller: _groupNameCtrl,
                              autofocus: true,
                              decoration: themedFieldDecoration(
                                  label:
                                      L10n.t('chat_list.group_name_field')),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(L10n.t('chat_list.public_group')),
                              value: _publicGroup,
                              onChanged: (v) =>
                                  setDialogState(() => _publicGroup = v),
                            ),
                            if (_groupError != null)
                              Text(_groupError!,
                                  style: const TextStyle(
                                      color: AppColors.error, fontSize: 12)),
                          ],
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.of(ctx).pop(),
                            child: Text(L10n.t('chat_list.cancel')),
                          ),
                          FilledButton(
                            onPressed: _createGroupChat,
                            child: Text(L10n.t('chat_list.create')),
                          ),
                        ],
                      ),
                    ),
                  );
                }
              },
              icon: Icon(actions),
              label: Text(_tabController.index == 0
                  ? L10n.t('chat_list.new_chat')
                  : L10n.t('chat_list.new_group')),
            ),
    );
  }
}