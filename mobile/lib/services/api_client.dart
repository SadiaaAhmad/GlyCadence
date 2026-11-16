import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/glycadence_models.dart';

class ApiClient {
  static String get defaultBaseUrl =>
      kIsWeb ? 'http://127.0.0.1:8010' : 'http://10.1.161.120:8010';
  static const String _tokenKey = 'glycadence_access_token';
  static const String _baseUrlKey = 'glycadence_api_base_url';

  final http.Client _http;
  String _baseUrl;
  String? _token;

  ApiClient({http.Client? httpClient, String? initialBaseUrl})
      : _http = httpClient ?? http.Client(),
        _baseUrl = initialBaseUrl ?? defaultBaseUrl;

  String get baseUrl => _baseUrl;
  String? get token => _token;
  bool get isAuthenticated => _token != null && _token!.isNotEmpty;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString(_baseUrlKey) ?? defaultBaseUrl;
    _token = prefs.getString(_tokenKey);
  }

  Future<void> setBaseUrl(String url) async {
    final normalized = url.trim().replaceAll(RegExp(r'/+$'), '');
    _baseUrl = normalized.isEmpty ? defaultBaseUrl : normalized;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_baseUrlKey, _baseUrl);
  }

  Future<void> setToken(String? token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    if (token == null || token.isEmpty) {
      await prefs.remove(_tokenKey);
    } else {
      await prefs.setString(_tokenKey, token);
    }
  }

  Map<String, String> _headers({bool jsonBody = false}) {
    final headers = <String, String>{};
    if (jsonBody) headers['Content-Type'] = 'application/json';
    if (_token != null && _token!.isNotEmpty) {
      headers['Authorization'] = 'Bearer $_token';
    }
    return headers;
  }

  dynamic _decodeResponse(http.Response res) {
    if (res.statusCode == 204) return null;
    final body = res.body.isEmpty ? null : jsonDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return body;
    }
    if (body is Map<String, dynamic> && body['detail'] != null) {
      throw Exception(body['detail'].toString());
    }
    throw Exception('HTTP ${res.statusCode}: ${res.reasonPhrase ?? 'Request failed'}');
  }

  Future<void> register(String email, String password) async {
    final uri = Uri.parse('$_baseUrl/api/v1/auth/register');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({'email': email.trim(), 'password': password}),
    );
    _decodeResponse(res);
    await login(email, password);
  }

  Future<void> login(String email, String password) async {
    final uri = Uri.parse('$_baseUrl/api/v1/auth/login');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({'email': email.trim(), 'password': password}),
    );
    final data = _decodeResponse(res) as Map<String, dynamic>;
    final accessToken = data['access_token'] as String?;
    if (accessToken == null || accessToken.isEmpty) {
      throw Exception('Login succeeded but access_token was missing.');
    }
    await setToken(accessToken);
  }

  Future<void> logout() async {
    await setToken(null);
  }

  Future<List<PatientSummary>> listPatients() async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data.whereType<Map<String, dynamic>>().map(PatientSummary.fromJson).toList();
  }

  Future<TodayOverviewData> getTodayOverview(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/overview');
    final res = await _http.get(uri, headers: _headers());
    return TodayOverviewData.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<GlucoseReadingsData> getGlucoseReadings(String patientId, {int days = 7}) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/glucose/readings?days=$days');
    final res = await _http.get(uri, headers: _headers());
    return GlucoseReadingsData.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<GlucoseSummary> getAnalyticsSummary(String patientId) async {
    final uri = Uri.parse(
        '$_baseUrl/api/v1/patients/$patientId/analytics/summary?native_only=false&include_non_native=true');
    final res = await _http.get(uri, headers: _headers());
    return GlucoseSummary.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<List<RecipeItem>> listRecipes({String? slot}) async {
    final q = slot != null && slot.isNotEmpty ? '?slot=$slot' : '';
    final uri = Uri.parse('$_baseUrl/api/v1/recipes$q');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data.whereType<Map<String, dynamic>>().map(RecipeItem.fromJson).toList();
  }

  Future<MealDetailData> getRecipeDetail(String recipeId, String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/recipes/$recipeId?patient_id=$patientId');
    final res = await _http.get(uri, headers: _headers());
    return MealDetailData.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<List<ChatSessionItem>> listChatSessions(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/chat/sessions');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data.whereType<Map<String, dynamic>>().map(ChatSessionItem.fromJson).toList();
  }

  Future<ChatSessionItem> createChatSession(String patientId, {String? title}) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/chat/sessions');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({'title': title}),
    );
    return ChatSessionItem.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<List<ChatMessageItem>> getChatMessages(String patientId, String sessionId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/chat/sessions/$sessionId/messages');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data.whereType<Map<String, dynamic>>().map(ChatMessageItem.fromJson).toList();
  }

  Future<Map<String, dynamic>> sendChatMessage(
      String patientId, String sessionId, String content) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/chat/sessions/$sessionId/messages');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({'content': content, 'mode': 'auto'}),
    );
    return _decodeResponse(res) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getMedicinesSummary(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/medicines/summary');
    final res = await _http.get(uri, headers: _headers());
    return _decodeResponse(res) as Map<String, dynamic>;
  }

  Future<void> logMedicine(String patientId, String medicationId, String status) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/medicines/log');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({'medication_id': medicationId, 'status': status}),
    );
    _decodeResponse(res);
  }

  Future<Map<String, dynamic>> getWellbeingSummary(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/wellbeing/summary');
    final res = await _http.get(uri, headers: _headers());
    return _decodeResponse(res) as Map<String, dynamic>;
  }

  Future<void> createWellbeingCheckin(
      String patientId, int stress, int fatigue, double sleepHours, int sleepQuality, bool illness) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/wellbeing/checkins');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({
        'stress_score': stress,
        'fatigue_score': fatigue,
        'sleep_hours': sleepHours,
        'sleep_quality': sleepQuality,
        'illness_flag': illness,
      }),
    );
    _decodeResponse(res);
  }

  Future<Map<String, dynamic>> getRamadanPlan(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/fasting/plan');
    final res = await _http.get(uri, headers: _headers());
    return _decodeResponse(res) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getVisitReport(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/visit-report');
    final res = await _http.get(uri, headers: _headers());
    return _decodeResponse(res) as Map<String, dynamic>;
  }

  Future<List<dynamic>> listMemory(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/memory');
    final res = await _http.get(uri, headers: _headers());
    return _decodeResponse(res) as List<dynamic>;
  }

  Future<void> deleteMemory(String patientId, String memId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/memory/$memId');
    final res = await _http.delete(uri, headers: _headers());
    _decodeResponse(res);
  }
}
