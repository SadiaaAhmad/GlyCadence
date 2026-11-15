import 'package:flutter/material.dart';

class GlyCadenceTheme {
  static const Color slateTeal = Color(0xFF0F4C5C);
  static const Color coral = Color(0xFFFF4D4D);
  static const Color lightBg = Color(0xFFFBFBFD);
  static const Color darkBg = Color(0xFF090D16);

  static ThemeData light() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: lightBg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: slateTeal,
        primary: slateTeal,
        secondary: coral,
        surface: Colors.white,
        brightness: Brightness.light,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: Color(0xFFE2E8F0), width: 1),
        ),
      ),
    );
  }

  static ThemeData dark() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: darkBg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: slateTeal,
        primary: const Color(0xFF2B8A9E),
        secondary: coral,
        surface: const Color(0xFF111827),
        brightness: Brightness.dark,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: const Color(0xFF111827),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: Color(0xFF1E293B), width: 1),
        ),
      ),
    );
  }
}
