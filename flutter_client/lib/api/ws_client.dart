/// Unified WebSocket client (mirrors the Python client's `ws_client.py`).
///
/// A single persistent connection handles both room messages and user-level
/// notifications. The server subscribes the socket to a room from the room_id
/// query param at connect time.
library;

import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

typedef WsRoomMessageHandler = void Function(Map<String, dynamic> payload);
typedef WsNotificationHandler = void Function(Map<String, dynamic> payload);
typedef WsReconnectingHandler = void Function(double delay);

class UnifiedWsClient {
  UnifiedWsClient({
    required this.token,
    this.onRoomMessage,
    this.onNotification,
    this.onReconnecting,
    this.wsUrl,
  });

  final String token;
  WsRoomMessageHandler? onRoomMessage;
  WsNotificationHandler? onNotification;
  WsReconnectingHandler? onReconnecting;
  final String? wsUrl;

  static const double _initialDelay = 1.0;
  static const double _maxDelay = 30.0;

  WebSocketChannel? _channel;
  int? _roomId;
  bool _closed = false;

  int? get roomId => _roomId;

  void setRoom(int? roomId) => _roomId = roomId;

  Future<void> connect(String baseWsUrl) async {
    var delay = _initialDelay;
    while (!_closed) {
      var url = '$baseWsUrl?token=$token';
      if (_roomId != null) url += '&room_id=$_roomId';
      try {
        final channel = WebSocketChannel.connect(Uri.parse(url));
        _channel = channel;
        delay = _initialDelay;
        await for (final raw in channel.stream) {
          if (_closed) break;
          _dispatch(raw.toString());
        }
      } catch (_) {
        // connection lost; fall through to backoff
      } finally {
        _channel = null;
      }
      if (_closed) break;
      onReconnecting?.call(delay);
      await Future.delayed(Duration(milliseconds: (delay * 1000).toInt()));
      delay = (delay * 2).clamp(_initialDelay, _maxDelay);
    }
  }

  void _dispatch(String raw) {
    Map<String, dynamic>? payload;
    try {
      payload = jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final type = payload['type'] as String? ?? '';
    if (type == 'message' || type == 'encrypted_message') {
      onRoomMessage?.call(payload);
    } else {
      onNotification?.call(payload);
    }
  }

  void sendMessage(int roomId, String body, {List<Map<String, dynamic>>? files}) {
    if (_channel == null) return;
    final frame = {
      'type': 'message',
      'room_id': roomId,
      'body': body,
      if (files != null) 'files': files,
    };
    _channel!.sink.add(jsonEncode(frame));
  }

  void close() {
    _closed = true;
    _channel?.sink.close();
  }
}
