import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:glycadence_mobile/main.dart';
import 'package:glycadence_mobile/services/api_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Client _mockApiHttp() {
  return MockClient((req) async {
    final p = req.url.path;
    if (p == '/api/v1/patients') {
      return http.Response(
        jsonEncode([
          {
            'id': 'p1',
            'cohort_type': 'synthetic_demo',
            'external_id': 'SYNTH-DEMO-001',
            'display_name': 'Amina Khan',
            'diabetes_type': 'T2D',
            'source_dataset': 'synthetic_demo',
          }
        ]),
        200,
      );
    }
    if (p == '/api/v1/recipes') {
      return http.Response(jsonEncode([]), 200);
    }
    if (p.endsWith('/overview')) {
      return http.Response(
        jsonEncode({
          'display_name': 'Amina Khan',
          'greeting_line': 'Steady night overall.',
          'hero': {'latest_mg_dl': 124, 'trend': 'steady', 'tir_pct': 88.5},
          'next_up': [],
          'featured_recipe': null,
        }),
        200,
      );
    }
    if (p.endsWith('/glucose/readings')) {
      return http.Response(
        jsonEncode({
          'target_low_mg_dl': 70,
          'target_high_mg_dl': 180,
          'latest_glucose_mg_dl': 124,
          'trend_arrow': 'steady',
          'source_summary': 'Based on 576 sensor readings',
          'readings': [
            {'recorded_at': '2026-11-16T08:00:00Z', 'glucose_mg_dl': 118},
            {'recorded_at': '2026-11-16T09:00:00Z', 'glucose_mg_dl': 124},
          ],
        }),
        200,
      );
    }
    if (p.contains('/analytics/summary')) {
      return http.Response(
        jsonEncode({'mean_glucose_mg_dl': 126, 'tir_pct': 88.5, 'tbr_pct': 1.2, 'tar_pct': 10.3}),
        200,
      );
    }
    if (p.startsWith('/api/v1/recipes/')) {
      return http.Response(
        jsonEncode({
          'recipe': {
            'id': 'r1',
            'name': 'Chana daal with brown rice',
            'slot': 'lunch',
            'cost_tier': 'low',
            'prep_min': 25,
            'image_url': '',
            'guidance_note': 'High fibre meal.',
            'steps': ['Cook daal', 'Serve with rice'],
            'ingredients': [],
            'nutrition': {
              'carbs_g': 48.0,
              'sugar_g': 4.2,
              'fibre_g': 11.4,
              'protein_g': 15.0,
              'fat_g': 6.0,
              'kcal': 310.0,
              'estimated_gl': 13.0,
              'gl_band': 'Medium',
            },
          },
          'recommended_time_window': '1:00 PM - 2:00 PM',
          'best_time_reason': 'Spacing helps stability.',
          'personal_history': {
            'times_observed': 3,
            'summary_text': 'Average rise +38 mg/dL across 3 lunches.',
            'curve_points': [],
          },
          'what_it_may_mean': ['Rich in fibre'],
        }),
        200,
      );
    }
    return http.Response('[]', 200);
  });
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('Saffron & Plum Login/Register screen renders cleanly',
      (WidgetTester tester) async {
    final client = ApiClient(httpClient: _mockApiHttp(), initialBaseUrl: 'http://127.0.0.1:8010');
    await tester.pumpWidget(GlyCadenceApp(apiClient: client));
    await tester.pumpAndSettle();

    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.text('Sign In'), findsOneWidget);

    await tester.tap(find.text('Need an account? Register'));
    await tester.pump();
    expect(find.text('Create GlyCadence Account'), findsOneWidget);
    expect(find.text('Register & Sign In'), findsOneWidget);
  });

  testWidgets('Authenticated 5-tab navigation shell renders Today, Ask Cadie, Glucose, Meals, More',
      (WidgetTester tester) async {
    final client = ApiClient(httpClient: _mockApiHttp(), initialBaseUrl: 'http://127.0.0.1:8010');
    await client.setToken('fake-jwt-for-smoke-test');
    await tester.pumpWidget(GlyCadenceApp(apiClient: client));
    await tester.pumpAndSettle();

    expect(find.text('Today'), findsOneWidget);
    expect(find.text('Ask Cadie'), findsOneWidget);
    expect(find.text('Glucose'), findsOneWidget);
    expect(find.text('Meals'), findsOneWidget);
    expect(find.text('More'), findsOneWidget);
    expect(find.text('Hello, Amina'), findsOneWidget);
  });

  testWidgets('MealDetailScreen displays computed sugar, carbs, and personal response',
      (WidgetTester tester) async {
    final client = ApiClient(httpClient: _mockApiHttp(), initialBaseUrl: 'http://127.0.0.1:8010');
    await client.setToken('fake-jwt-for-smoke-test');
    await tester.pumpWidget(
      GlyCadenceApp(apiClient: client),
    );
    await tester.pumpAndSettle();
    // Push MealDetailScreen via MaterialApp navigator
    await tester.pumpWidget(
      MaterialApp(
        home: MealDetailScreen(apiClient: client, patientId: 'p1', recipeId: 'r1'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Chana daal with brown rice'), findsWidgets);
    expect(find.text('Sugar: 4.2g'), findsOneWidget);
    expect(find.text('Average rise +38 mg/dL across 3 lunches.'), findsOneWidget);
  });
}
