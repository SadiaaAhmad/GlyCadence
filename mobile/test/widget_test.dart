import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:glycadence_mobile/main.dart';
import 'package:glycadence_mobile/services/api_client.dart';

void main() {
  testWidgets('GlyCadence mobile app renders login screen when unauthenticated',
      (WidgetTester tester) async {
    final client = ApiClient(initialBaseUrl: 'http://127.0.0.1:8010');
    await tester.pumpWidget(GlyCadenceApp(apiClient: client));
    await tester.pumpAndSettle();

    expect(find.text('Sign in to GlyCadence'), findsOneWidget);
    expect(find.text('Sign In'), findsOneWidget);
    expect(find.byIcon(Icons.settings_outlined), findsOneWidget);
  });
}
