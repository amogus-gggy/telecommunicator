import 'package:flutter_client/views/room_view.dart';
import 'package:flutter_test/flutter_test.dart';

/// Regression cover for the chat list jumping around: decryption is async, so
/// messages arrived in completion order and were appended as-is.
void main() {
  Map<String, dynamic> msg({
    int? id,
    String? createdAt,
    bool optimistic = false,
    int? seq,
  }) =>
      <String, dynamic>{
        if (id != null) 'id': id,
        if (createdAt != null) 'created_at': createdAt,
        if (optimistic) 'is_optimistic': true,
        if (seq != null) '_seq': seq,
      };

  group('compareRoomMessages', () {
    test('orders by server id, not by arrival order', () {
      final list = [
        msg(id: 3, seq: 0),
        msg(id: 1, seq: 1),
        msg(id: 2, seq: 2),
      ]..sort(compareRoomMessages);

      expect(list.map((m) => m['id']), [1, 2, 3]);
    });

    test('keeps a pending send below everything the server confirmed', () {
      final list = [
        msg(id: 9, seq: 0),
        msg(optimistic: true, seq: 1),
        msg(id: 1, seq: 2),
      ]..sort(compareRoomMessages);

      expect(list.map((m) => m['id'] ?? 'pending'), [1, 9, 'pending']);
    });

    test('falls back to created_at when ids are missing', () {
      final list = [
        msg(createdAt: '2026-10-02T15:00:02Z', seq: 0),
        msg(createdAt: '2026-10-02T15:00:01Z', seq: 1),
      ]..sort(compareRoomMessages);

      expect(list.first['created_at'], '2026-10-02T15:00:01Z');
    });

    test('prefers id over created_at when both are present', () {
      // A mirrored room can carry clocks that disagree; the server id wins.
      final list = [
        msg(id: 2, createdAt: '2020-01-01T00:00:00Z', seq: 0),
        msg(id: 1, createdAt: '2030-01-01T00:00:00Z', seq: 1),
      ]..sort(compareRoomMessages);

      expect(list.map((m) => m['id']), [1, 2]);
    });

    test('ties fall back to insertion order instead of shuffling', () {
      final list = [
        msg(seq: 0),
        msg(seq: 1),
        msg(seq: 2),
      ]..sort(compareRoomMessages);

      expect(list.map((m) => m['_seq']), [0, 1, 2]);
      // Re-sorting an already sorted list must not move anything.
      list.sort(compareRoomMessages);
      expect(list.map((m) => m['_seq']), [0, 1, 2]);
    });
  });
}
