import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_client/config.dart';
import 'package:flutter_client/state/app_state.dart';
import 'package:flutter_client/views/chat_list_view.dart';

Future<void> _hoverBottomBar(WidgetTester tester) async {
  final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
  await gesture.addPointer(location: Offset.zero);
  addTearDown(gesture.removePointer);
  // Park the mouse over the bottom navigation area and let post-frame
  // mouse-tracker updates hit-test it.
  await gesture.moveTo(const Offset(200, 560));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 16));
  await tester.pump(const Duration(milliseconds: 16));
}

void main() {
  testWidgets('BottomAppBar + FAB does not corrupt mouse tracker on hover',
      (tester) async {
    // Regression: Material 3 BottomAppBar uses a _BottomAppBarClipper that
    // reads Scaffold.geometryOf() lazily; a mouse hit-test evaluates getClip()
    // outside the paint phase and throws.
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(useMaterial3: true),
        home: Scaffold(
          floatingActionButton: FloatingActionButton.extended(
            onPressed: () {},
            icon: const Icon(Icons.person_add),
            label: const Text('New chat'),
          ),
          bottomNavigationBar: BottomAppBar(
            color: const Color(0xFFFEF7FF),
            child: const TabBar(
              tabs: [
                Tab(icon: Icon(Icons.person), text: 'Personal'),
                Tab(icon: Icon(Icons.group), text: 'Groups'),
                Tab(icon: Icon(Icons.public), text: 'Public'),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await _hoverBottomBar(tester);

    // The old BottomAppBar layout triggers the framework assertion.
    expect(tester.takeException(), isNotNull);
  });

  testWidgets('ChatListView bottom nav does not throw on hover',
      (tester) async {
    final state = AppState();
    state.token = 'tok';
    state.currentUser = UserDTO(
      id: 1,
      username: 'alice',
      email: 'alice@example.org',
      displayName: 'Alice',
    );

    await tester.pumpWidget(MaterialApp(home: ChatListView(state: state)));
    await tester.pumpAndSettle();

    await _hoverBottomBar(tester);

    expect(tester.takeException(), isNull);
  });
}