/// Shared UI theme helpers (mirrors `client/ui/theme.py`).
library;

import 'package:flutter/material.dart';

class AppColors {
  static const Color primary = Color(0xFF229ED9);
  static const Color surfaceContainer = Color(0xFFFFFFFF);
  static const Color surfaceContainerHigh = Color(0xFFF4F4F5);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color outlineVariant = Color(0xFFDADADA);
  static const Color onSurface = Color(0xFF000000);
  static const Color onSurfaceVariant = Color(0xFF707579);
  static const Color onPrimary = Colors.white;
  static const Color error = Color(0xFFB3261E);

  static const Color darkPrimary = Color(0xFF8E7CE8);
  static const Color darkSurfaceContainer = Color(0xFF0E1621);
  static const Color darkSurfaceContainerHigh = Color(0xFF212121);
  static const Color darkSurface = Color(0xFF212121);
  static const Color darkOutlineVariant = Color(0xFF2B2B2B);
  static const Color darkOnSurface = Color(0xFFF5F5F5);
  static const Color darkOnSurfaceVariant = Color(0xFF8A8A8A);
}

/// Theme-aware color accessors resolving against the current [ColorScheme].
/// Use these instead of the static [AppColors] constants (which are light-only)
/// so every surface adapts to the active light/dark/system theme.
extension ThemeColors on BuildContext {
  Color get primary => Theme.of(this).colorScheme.primary;
  Color get onPrimary => Theme.of(this).colorScheme.onPrimary;
  Color get onError => Theme.of(this).colorScheme.onError;
  Color get surfaceContainer => Theme.of(this).colorScheme.surfaceContainer;
  Color get surfaceContainerHigh =>
      Theme.of(this).colorScheme.surfaceContainerHigh;
  Color get surface => Theme.of(this).colorScheme.surface;
  Color get outlineVariant => Theme.of(this).colorScheme.outlineVariant;
  Color get onSurface => Theme.of(this).colorScheme.onSurface;
  Color get onSurfaceVariant => Theme.of(this).colorScheme.onSurfaceVariant;
  Color get error => Theme.of(this).colorScheme.error;
}

ThemeData lightTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: AppColors.surfaceContainerHigh,
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    );

ThemeData darkTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: AppColors.darkSurfaceContainerHigh,
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    );

/// Round avatar with the first letters of the display name.
Widget initialsAvatar(BuildContext context, String name, {double size = 44}) {
  final parts = name
      .trim()
      .split(RegExp(r'\s+'))
      .where((p) => p.isNotEmpty)
      .toList();
  String initials = '';
  if (parts.isEmpty) {
    initials = '?';
  } else if (parts.length == 1) {
    final p = parts.first;
    initials = p.substring(0, 1).toUpperCase();
  } else {
    initials = (parts[0].substring(0, 1) + parts[1].substring(0, 1))
        .toUpperCase();
  }
  const palette = [
    Color(0xFFE17076),
    Color(0xFF7BC862),
    Color(0xFFE5CA77),
    Color(0xFF65AADD),
    Color(0xFFA695E7),
    Color(0xFFEE7AB6),
    Color(0xFF6EC9CB),
    Color(0xFFFAA774),
  ];
  final bg = palette[name.hashCode.abs() % palette.length];
  return CircleAvatar(
    radius: size / 2,
    backgroundColor: bg,
    child: Text(
      initials,
      style: TextStyle(
        fontSize: size * 0.36,
        fontWeight: FontWeight.w600,
        color: Colors.white,
      ),
    ),
  );
}

FilledButton primaryButton(
  BuildContext context,
  String label, {
  VoidCallback? onPressed,
  IconData? icon,
}) {
  final scheme = Theme.of(context).colorScheme;
  return FilledButton.icon(
    onPressed: onPressed,
    icon: icon == null ? const SizedBox.shrink() : Icon(icon, size: 18),
    label: Text(label),
    style: FilledButton.styleFrom(
      backgroundColor: scheme.primary,
      foregroundColor: scheme.onPrimary,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
    ),
  );
}

InputDecoration themedFieldDecoration({
  String? label,
  String? hintText,
  IconData? prefixIcon,
}) =>
    InputDecoration(
      labelText: label,
      hintText: hintText,
      prefixIcon: prefixIcon == null ? null : Icon(prefixIcon, size: 20),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(20)),
      filled: true,
    );

void showSnack(BuildContext context, String message, {bool ok = true}) {
  final scheme = Theme.of(context).colorScheme;
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: ok ? scheme.primary : scheme.error,
  ));
}

/// Navigate after the current frame so pointer/hover tracking finishes first
/// (avoids mouse_tracker assertions on desktop when leaving a hovered control).
void navigateReplacing(BuildContext context, Widget page) {
  FocusManager.instance.primaryFocus?.unfocus();
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => page),
    );
  });
}

void navigatePush(BuildContext context, Widget page) {
  FocusManager.instance.primaryFocus?.unfocus();
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => page),
    );
  });
}

void navigateClearStack(BuildContext context, Widget page) {
  FocusManager.instance.primaryFocus?.unfocus();
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => page),
      (route) => false,
    );
  });
}
