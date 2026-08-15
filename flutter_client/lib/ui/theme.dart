/// Shared UI theme helpers (mirrors `client/ui/theme.py`).
library;

import 'package:flutter/material.dart';

class AppColors {
  static const Color primary = Color(0xFF6750A4);
  static const Color surfaceContainer = Color(0xFFF3EDF7);
  static const Color surfaceContainerHigh = Color(0xFFECE6F0);
  static const Color surface = Color(0xFFFEF7FF);
  static const Color outlineVariant = Color(0xFFCAC4D0);
  static const Color onSurface = Color(0xFF1D1B20);
  static const Color onSurfaceVariant = Color(0xFF49454F);
  static const Color onPrimary = Colors.white;
  static const Color error = Color(0xFFB3261E);

  static const Color darkPrimary = Color(0xFFD0BCFF);
  static const Color darkSurfaceContainer = Color(0xFF211F26);
  static const Color darkSurfaceContainerHigh = Color(0xFF2B2930);
  static const Color darkSurface = Color(0xFF141218);
  static const Color darkOutlineVariant = Color(0xFF49454F);
  static const Color darkOnSurface = Color(0xFFE6E0E9);
  static const Color darkOnSurfaceVariant = Color(0xFFCAC4D0);
}

ThemeData lightTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: AppColors.surfaceContainer,
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    );

ThemeData darkTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: AppColors.darkSurfaceContainer,
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    );

/// Round avatar with the first letters of the display name.
Widget initialsAvatar(String name, {double size = 44}) {
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
  return CircleAvatar(
    radius: size / 2,
    backgroundColor: AppColors.primary.withValues(alpha: 0.15),
    child: Text(
      initials,
      style: TextStyle(
        fontSize: size * 0.36,
        fontWeight: FontWeight.w600,
        color: AppColors.primary,
      ),
    ),
  );
}

FilledButton primaryButton(
  String label, {
  VoidCallback? onPressed,
  IconData? icon,
}) =>
    FilledButton.icon(
      onPressed: onPressed,
      icon: icon == null ? const SizedBox.shrink() : Icon(icon, size: 18),
      label: Text(label),
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.primary,
        foregroundColor: AppColors.onPrimary,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
      ),
    );

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
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: ok ? AppColors.primary : AppColors.error,
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
