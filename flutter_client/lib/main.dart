import 'package:flutter/material.dart';

import 'l10n/strings.dart';
import 'state/app_state.dart';
import 'storage/settings.dart';
import 'ui/theme.dart';
import 'views/login_view.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = await SettingsStore.load();

  final apiUrl = settings.get('settings.api_url');
  final wsUrl = settings.get('settings.ws_url');
  final themeMode = settings.get('settings.theme_mode') ?? 'system';
  final messageAlignment =
      settings.get('settings.message_alignment') ?? 'default';
  final locale = settings.get('settings.locale');
  if (locale != null) L10n.setLocale(locale);

  final state = AppState(
    apiUrl: apiUrl ?? stateDefaultApiUrl,
    wsUrl: wsUrl ?? stateDefaultWsUrl,
    themeMode: themeMode,
    messageAlignment: messageAlignment,
    settings: settings,
  );

  runApp(TelecommunicatorApp(state: state));
}

const String stateDefaultApiUrl = 'http://127.0.0.1:8000';
const String stateDefaultWsUrl = 'ws://127.0.0.1:8000/ws';

class TelecommunicatorApp extends StatefulWidget {
  const TelecommunicatorApp({super.key, required this.state});

  final AppState state;

  @override
  State<TelecommunicatorApp> createState() => _TelecommunicatorAppState();
}

class _TelecommunicatorAppState extends State<TelecommunicatorApp> {
  @override
  void initState() {
    super.initState();
    widget.state.addListener(_onStateChanged);
  }

  @override
  void dispose() {
    widget.state.removeListener(_onStateChanged);
    super.dispose();
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final themeMode = widget.state.themeMode;
    return MaterialApp(
      title: 'Telecommunicator',
      debugShowCheckedModeBanner: false,
      theme: lightTheme(),
      darkTheme: darkTheme(),
      themeMode: themeMode == 'dark'
          ? ThemeMode.dark
          : themeMode == 'light'
              ? ThemeMode.light
              : ThemeMode.system,
      home: LoginView(state: widget.state),
    );
  }
}
