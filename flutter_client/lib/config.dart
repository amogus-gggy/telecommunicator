/// Client configuration and server-address helpers.
library;

import 'dart:typed_data';

const String defaultApiUrl = 'http://127.0.0.1:8000';
const String defaultWsUrl = 'ws://127.0.0.1:8000/ws';
const int defaultHttpPort = 8000;

/// Split 'username@server' into (username, server). Returns (handle, null)
/// when no '@' is present (current/default server is used).
(String, String?) parseHandle(String handle) {
  handle = (handle).trim();
  if (handle.isEmpty) return ('', null);
  if (handle.contains('@')) {
    final idx = handle.lastIndexOf('@');
    final username = handle.substring(0, idx).trim();
    final server = handle.substring(idx + 1).trim();
    return (username, server.isEmpty ? null : server);
  }
  return (handle, null);
}

/// Normalize a server address into (apiUrl, wsUrl).
(String, String) buildApiUrls(String server) {
  server = server.trim();
  if (server.endsWith('/')) server = server.substring(0, server.length - 1);
  if (server.isEmpty) throw ArgumentError('server address is empty');
  var scheme = 'http';
  var rest = server;
  if (server.contains('://')) {
    final split = server.split('://');
    scheme = split[0];
    rest = split[1];
  } else {
    server = 'http://$server';
  }
  // Parse authority/port
  final uri = Uri.parse(scheme == 'http' || scheme == 'ws' ? server : '$scheme://$rest');
  final netloc = uri.host.isEmpty ? rest : uri.host;
  var port = uri.port;
  if (port == 0) {
    port = (scheme == 'http' || scheme == 'ws') ? defaultHttpPort : 443;
    server = '$scheme://$netloc:$port';
  } else {
    server = '$scheme://$netloc:$port';
  }
  final wsProto = scheme == 'https' ? 'wss' : (scheme == 'http' ? 'ws' : scheme);
  final wsUrl = '$wsProto://$netloc:$port/ws';
  return (server, wsUrl);
}

/// Persisted account credentials/keys holder.
class UserDTO {
  UserDTO({
    required this.id,
    required this.username,
    required this.email,
    this.displayName,
    this.serverName = '',
  });

  final int id;
  final String username;
  final String email;
  final String? displayName;
  final String serverName;

  factory UserDTO.fromJson(Map<String, dynamic> j) => UserDTO(
        id: j['id'] as int,
        username: j['username'] as String? ?? '',
        email: j['email'] as String? ?? '',
        displayName: j['display_name'] as String?,
        serverName: (j['server_name'] as String?) ?? '',
      );
}

class RoomDTO {
  RoomDTO({
    required this.id,
    required this.name,
    required this.roomType,
    required this.ownerUsername,
    required this.memberCount,
    required this.isPrivate,
    required this.allowMemberInvite,
    required this.readOnly,
    this.serverName = '',
    this.remoteRoomId,
    this.participants = const [],
  });

  final int id;
  final String name;
  final String roomType;
  final String ownerUsername;
  final int memberCount;
  final bool isPrivate;
  final bool allowMemberInvite;
  final bool readOnly;
  final String serverName;
  final int? remoteRoomId;
  final List<String> participants;

  factory RoomDTO.fromJson(Map<String, dynamic> j) => RoomDTO(
        id: j['id'] as int,
        name: j['name'] as String,
        roomType: j['room_type'] as String,
        ownerUsername: j['owner_username'] as String,
        memberCount: j['member_count'] as int,
        isPrivate: j['is_private'] as bool,
        allowMemberInvite: j['allow_member_invite'] as bool,
        readOnly: j['read_only'] as bool,
        serverName: (j['server_name'] as String?) ?? '',
        remoteRoomId: j['remote_room_id'] as int?,
        participants: (j['participants'] as List? ?? [])
            .map((e) => e as String)
            .toList(),
      );
}

class CryptoKeys {
  CryptoKeys({
    required this.ed25519Private,
    required this.ed25519Public,
    required this.x25519Private,
    required this.x25519Public,
  });

  final Uint8List ed25519Private;
  final Uint8List ed25519Public;
  final Uint8List x25519Private;
  final Uint8List x25519Public;
}
