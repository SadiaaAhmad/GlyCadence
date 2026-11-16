import 'package:flutter/material.dart';

class GlyCadenceTheme {
  static const Color ink = Color(0xFF2B1E2F);
  static const Color cream = Color(0xFFFBF6EF);
  static const Color clay = Color(0xFFE9DCCB);
  static const Color darkPlumBg = Color(0xFF1C1420);
  static const Color darkPlumCard = Color(0xFF2A1F2E);
  static const Color darkBorder = Color(0xFF43324A);
  static const Color coral = Color(0xFFFF4D4D);
  static const Color saffron = Color(0xFFF2A93B);
  static const Color terracotta = Color(0xFFC8553D);
  static const Color berry = Color(0xFF8E2C5A);

  static ThemeData light() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: cream,
      colorScheme: ColorScheme.fromSeed(
        seedColor: coral,
        primary: ink,
        secondary: coral,
        surface: Colors.white,
        brightness: Brightness.light,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: clay, width: 1),
        ),
      ),
    );
  }

  static ThemeData dark() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: darkPlumBg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: coral,
        primary: saffron,
        secondary: coral,
        surface: darkPlumCard,
        brightness: Brightness.dark,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: darkPlumCard,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: darkBorder, width: 1),
        ),
      ),
    );
  }
}
