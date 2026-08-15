/// REST API client mirroring the Python client's `api/http_client.py`.
library;

import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../state/app_state.dart';

class ApiException implements Exception {
  ApiException(this.message, this.statusCode);
  final String message;
  final int statusCode;
  @override
  String toString() => 'ApiException($statusCode): $message';
}

class AuthError extends ApiException {
  AuthError(String message) : super(message, 401);
}

class ForbiddenError extends ApiException {
  ForbiddenError(String message) : super(message, 403);
}

class ConflictError extends ApiException {
  ConflictError(String message) : super(message, 409);
}

class ValidationError extends ApiException {
  ValidationError(String message) : super(message, 422);
}

String _parseDetail(http.Response response) {
  try {
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final detail = body['detail'];
    if (detail is List) {
      return detail.map((e) => (e as Map)['msg'] ?? e.toString()).join('; ');
    }
    return detail?.toString() ?? response.body;
  } catch (_) {
    return response.body;
  }
}

void _raiseForStatus(http.Response response) {
  if (response.statusCode == 401) throw AuthError(_parseDetail(response));
  if (response.statusCode == 403) throw ForbiddenError(_parseDetail(response));
  if (response.statusCode == 409) throw ConflictError(_parseDetail(response));
  if (response.statusCode == 422) throw ValidationError(_parseDetail(response));
  if (response.statusCode >= 400) {
    throw ApiException(_parseDetail(response), response.statusCode);
  }
}

final Map<String, http.Client> _sharedClients = {};

http.Client _clientFor(String baseUrl) {
  return _sharedClients.putIfAbsent(baseUrl, () => http.Client());
}

Future<void> closeSharedClients() async {
  for (final c in _sharedClients.values) {
    c.close();
  }
  _sharedClients.clear();
}

class ApiClient {
  ApiClient({AppState? state, String? baseUrl})
      : state = state ?? AppState(),
        baseUrl = (baseUrl ?? state?.apiUrl ?? defaultApiUrl).toString().replaceAll(RegExp(r'/$'), '');

  final AppState state;
  final String baseUrl;

  Map<String, String> get _headers {
    final token = state.token;
    return token == null ? {} : {'Authorization': 'Bearer $token'};
  }

  Future<http.Response> _get(String path, {Map<String, String>? query}) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    final r = await _clientFor(baseUrl).get(uri, headers: _headers);
    _raiseForStatus(r);
    return r;
  }

  Future<http.Response> _post(String path, {Object? json, Map<String, String>? headers}) async {
    final uri = Uri.parse('$baseUrl$path');
    final r = await _clientFor(baseUrl).post(uri,
        headers: {..._headers, if (json != null) 'Content-Type': 'application/json', ...?headers},
        body: json == null ? null : jsonEncode(json));
    _raiseForStatus(r);
    return r;
  }

  Future<http.Response> _patch(String path, {Object? json}) async {
    final uri = Uri.parse('$baseUrl$path');
    final r = await _clientFor(baseUrl).patch(uri,
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: jsonEncode(json));
    _raiseForStatus(r);
    return r;
  }

  Future<http.Response> _put(String path, {Object? json}) async {
    final uri = Uri.parse('$baseUrl$path');
    final r = await _clientFor(baseUrl).put(uri,
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: jsonEncode(json));
    _raiseForStatus(r);
    return r;
  }

  Future<http.Response> _delete(String path) async {
    final uri = Uri.parse('$baseUrl$path');
    final r = await _clientFor(baseUrl).delete(uri, headers: _headers);
    _raiseForStatus(r);
    return r;
  }

  // ---- Auth ----
  Future<Map<String, dynamic>> register({
    required String username,
    required String email,
    required String password,
    required String identityPubEd25519,
    required String identityPubX25519,
    required String encryptedBackup,
  }) async {
    final r = await _post('/auth/register', json: {
      'username': username,
      'email': email,
      'password': password,
      'identity_pub_ed25519': identityPubEd25519,
      'identity_pub_x25519': identityPubX25519,
      'encrypted_backup': encryptedBackup,
    });
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> login(String username, String password) async {
    final r = await _post('/auth/login',
        json: {'username': username, 'password': password});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  // ---- Users ----
  Future<Map<String, dynamic>> getMe() async {
    final r = await _get('/users/me');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> getMyRooms() async {
    final r = await _get('/users/me/rooms');
    return jsonDecode(r.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> getUser(String username) async {
    final r = await _get('/users/${Uri.encodeComponent(username)}');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateProfile(String displayName) async {
    final r = await _patch('/users/me',
        json: {'display_name': displayName});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> changePassword(String currentPassword, String newPassword) async {
    await _post('/users/me/password',
        json: {'current_password': currentPassword, 'new_password': newPassword});
  }

  // ---- Rooms ----
  Future<List<dynamic>> listRooms() async {
    final r = await _get('/rooms');
    return jsonDecode(r.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> createRoom(
      String name, String roomType, bool isPrivate) async {
    final r = await _post('/rooms',
        json: {'name': name, 'room_type': roomType, 'is_private': isPrivate});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createPersonalChat(String username) async {
    final r = await _post('/rooms/personal', json: {'username': username});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> joinRoom(int roomId) async {
    final r = await _post('/rooms/$roomId/join');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> leaveRoom(int roomId) async =>
      _post('/rooms/$roomId/leave');

  Future<Map<String, dynamic>> getRoom(int roomId) async {
    final r = await _get('/rooms/$roomId');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> inviteUser(int roomId, String username) async =>
      _post('/rooms/$roomId/invite/${Uri.encodeComponent(username)}');

  Future<void> removeMember(int roomId, String username) async =>
      _delete('/rooms/$roomId/members/${Uri.encodeComponent(username)}');

  Future<Map<String, dynamic>> updatePermissions(int roomId,
      {bool? allowMemberInvite, bool? readOnly}) async {
    final payload = <String, dynamic>{};
    if (allowMemberInvite != null) payload['allow_member_invite'] = allowMemberInvite;
    if (readOnly != null) payload['read_only'] = readOnly;
    final r = await _patch('/rooms/$roomId/permissions', json: payload);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  // ---- Messages ----
  Future<List<dynamic>> getMessages(int roomId,
      {int? beforeId, int limit = 50}) async {
    final query = {'limit': limit.toString()};
    if (beforeId != null) query['before_id'] = beforeId.toString();
    final r = await _get('/rooms/$roomId/messages', query: query);
    return jsonDecode(r.body) as List<dynamic>;
  }

  // ---- E2EE ----
  Future<Map<String, dynamic>> getPublicKeys(String username) async {
    final r = await _get(
        '/users/${Uri.encodeComponent(username)}/public-keys');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updatePublicKeys(
      String ed25519PubB64, String x25519PubB64) async {
    final r = await _put('/users/me/public-keys', json: {
      'identity_pub_ed25519': ed25519PubB64,
      'identity_pub_x25519': x25519PubB64,
    });
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getBackup() async {
    final r = await _get('/backup');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateBackup(String encryptedBackupB64) async {
    final r = await _put('/backup', json: {'encrypted_backup': encryptedBackupB64});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> sendEncryptedMessage({
    required int roomId,
    String? recipientUsername,
    required String encryptedBlobB64,
    required String senderEncryptedBlobB64,
    required String signatureB64,
    List<int> fileIds = const [],
  }) async {
    final r = await _post('/messages', json: {
      'room_id': roomId,
      'recipient_username': recipientUsername,
      'encrypted_blob': encryptedBlobB64,
      'sender_encrypted_blob': senderEncryptedBlobB64,
      'signature': signatureB64,
      'file_ids': fileIds,
    });
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> sendGroupEncryptedMessage({
    required int roomId,
    required String encryptedBlobB64,
    required String senderEncryptedBlobB64,
    required String signatureB64,
    List<int> fileIds = const [],
  }) async {
    final r = await _post('/messages', json: {
      'room_id': roomId,
      'encrypted_blob': encryptedBlobB64,
      'sender_encrypted_blob': senderEncryptedBlobB64,
      'signature': signatureB64,
      'file_ids': fileIds,
    });
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> putSenderKeys(int roomId, List<Map<String, dynamic>> entries) async {
    final r = await _put('/rooms/$roomId/sender-keys', json: {'entries': entries});
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getSenderKeys(int roomId, {String? sender}) async {
    final query = <String, String>{};
    if (sender != null) query['sender'] = sender;
    final r = await _get('/rooms/$roomId/sender-keys', query: query);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> deleteMessage(int messageId) async =>
      _delete('/messages/$messageId');

  // ---- Files ----
  /// Stream-upload a (possibly encrypted) file. Returns parsed JSON.
  Future<Map<String, dynamic>> uploadFile(
    int roomId,
    File file, {
    String? keyBlob,
    String? keySenderBlob,
    String? keySignature,
    void Function(int done, int total)? onProgress,
  }) async {
    final size = await file.length();
    final uri = Uri.parse('$baseUrl/rooms/$roomId/files');
    final request = http.StreamedRequest('POST', uri);
    request.headers.addAll({
      ..._headers,
      'X-Filename': file.path.split('/').last,
      'Content-Type': 'application/octet-stream',
      'Content-Length': size.toString(),
    });
    if (keyBlob != null) request.headers['X-Key-Blob'] = keyBlob;
    if (keySenderBlob != null) request.headers['X-Key-Sender-Blob'] = keySenderBlob;
    if (keySignature != null) request.headers['X-Key-Signature'] = keySignature;

    var done = 0;
    await file.openRead().forEach((chunk) {
      request.sink.add(chunk);
      done += chunk.length;
      onProgress?.call(done, size);
    });
    request.sink.close();
    final response = await http.Response.fromStream(await request.send());
    _raiseForStatus(response);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<void> downloadFile(
    int roomId,
    int fileId,
    File outFile, {
    void Function(int done, int total)? onProgress,
  }) async {
    final uri =
        Uri.parse('$baseUrl/rooms/$roomId/files/$fileId/download');
    final request = http.Request('GET', uri);
    request.headers.addAll(_headers);
    final response = await _clientFor(baseUrl).send(request);
    if (response.statusCode >= 400) {
      throw ApiException(_parseDetail(http.Response(
              'error', response.statusCode, request: request)),
          response.statusCode);
    }
    final total = response.contentLength ?? 0;
    var done = 0;
    final sink = outFile.openWrite();
    await for (final chunk in response.stream) {
      sink.add(chunk);
      done += chunk.length;
      onProgress?.call(done, total);
    }
    await sink.close();
  }
}
