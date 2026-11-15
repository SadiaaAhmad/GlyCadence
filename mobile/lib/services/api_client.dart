import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/glycadence_models.dart';

class ApiClient {
  static const String defaultBaseUrl = 'http://10.1.161.120:8010';
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
    final body = res.body.isEmpty ? null : jsonDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return body;
    }
    if (body is Map<String, dynamic> && body['detail'] != null) {
      throw Exception(body['detail'].toString());
    }
    throw Exception('HTTP ${res.statusCode}: ${res.reasonPhrase ?? 'Request failed'}');
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
    return data
        .whereType<Map<String, dynamic>>()
        .map(PatientSummary.fromJson)
        .toList();
  }

  Future<GlucoseSummary> getAnalyticsSummary(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/analytics/summary');
    final res = await _http.get(uri, headers: _headers());
    return GlucoseSummary.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }

  Future<List<MealResponseItem>> getMealResponses(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/analytics/meals');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data
        .whereType<Map<String, dynamic>>()
        .map(MealResponseItem.fromJson)
        .toList();
  }

  Future<List<InvestigationRun>> listInvestigations(String patientId) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/investigations');
    final res = await _http.get(uri, headers: _headers());
    final data = _decodeResponse(res) as List<dynamic>;
    return data
        .whereType<Map<String, dynamic>>()
        .map(InvestigationRun.fromJson)
        .toList();
  }

  Future<InvestigationRun> runInvestigation(
    String patientId, {
    bool simulateBadDraft = false,
  }) async {
    final uri = Uri.parse('$_baseUrl/api/v1/patients/$patientId/investigations');
    final res = await _http.post(
      uri,
      headers: _headers(jsonBody: true),
      body: jsonEncode({
        'trigger_type': 'manual',
        'simulate_bad_draft': simulateBadDraft,
      }),
    );
    return InvestigationRun.fromJson(_decodeResponse(res) as Map<String, dynamic>);
  }
}
