import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'models/glycadence_models.dart';
import 'services/api_client.dart';
import 'theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final apiClient = ApiClient();
  await apiClient.init();
  runApp(GlyCadenceApp(apiClient: apiClient));
}

class GlyCadenceApp extends StatefulWidget {
  final ApiClient apiClient;
  const GlyCadenceApp({super.key, required this.apiClient});

  @override
  State<GlyCadenceApp> createState() => _GlyCadenceAppState();
}

class _GlyCadenceAppState extends State<GlyCadenceApp> {
  ThemeMode _themeMode = ThemeMode.system;

  void _toggleTheme() {
    setState(() {
      _themeMode = _themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GlyCadence',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.light,
        scaffoldBackgroundColor: GlyCadenceTheme.lightBg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: GlyCadenceTheme.slateTeal,
          primary: GlyCadenceTheme.slateTeal,
          secondary: GlyCadenceTheme.coral,
        ),
      ),
      darkTheme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: GlyCadenceTheme.darkBg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: GlyCadenceTheme.slateTeal,
          primary: const Color(0xFF2B8A9E),
          secondary: GlyCadenceTheme.coral,
          brightness: Brightness.dark,
        ),
      ),
      themeMode: _themeMode,
      home: GlyCadenceHome(
        apiClient: widget.apiClient,
        onToggleTheme: _toggleTheme,
      ),
    );
  }
}

class GlyCadenceHome extends StatefulWidget {
  final ApiClient apiClient;
  final VoidCallback onToggleTheme;

  const GlyCadenceHome({
    super.key,
    required this.apiClient,
    required this.onToggleTheme,
  });

  @override
  State<GlyCadenceHome> createState() => _GlyCadenceHomeState();
}

class _GlyCadenceHomeState extends State<GlyCadenceHome> {
  int _tabIndex = 0;
  bool _loading = false;
  String? _error;

  List<PatientSummary> _patients = [];
  PatientSummary? _selectedPatient;
  GlucoseSummary? _summary;
  List<MealResponseItem> _meals = [];
  List<InvestigationRun> _investigations = [];
  InvestigationRun? _activeRun;

  @override
  void initState() {
    super.initState();
    if (widget.apiClient.isAuthenticated) {
      _loadPatients();
    }
  }

  Future<void> _loadPatients() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await widget.apiClient.listPatients();
      setState(() {
        _patients = list;
        _selectedPatient = list.isNotEmpty ? list.first : null;
      });
      if (_selectedPatient != null) {
        await _loadPatientData(_selectedPatient!.id);
      }
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadPatientData(String patientId) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        widget.apiClient.getAnalyticsSummary(patientId),
        widget.apiClient.getMealResponses(patientId),
        widget.apiClient.listInvestigations(patientId),
      ]);
      final invs = results[2] as List<InvestigationRun>;
      setState(() {
        _summary = results[0] as GlucoseSummary;
        _meals = results[1] as List<MealResponseItem>;
        _investigations = invs;
        _activeRun = invs.isNotEmpty ? invs.first : null;
      });
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _runInvestigation({bool simulateBadDraft = false}) async {
    if (_selectedPatient == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final run = await widget.apiClient.runInvestigation(
        _selectedPatient!.id,
        simulateBadDraft: simulateBadDraft,
      );
      setState(() {
        _activeRun = run;
        _investigations = [run, ..._investigations];
        _tabIndex = 1;
      });
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.apiClient.isAuthenticated) {
      return LoginScreen(
        apiClient: widget.apiClient,
        onLoggedIn: () {
          setState(() {});
          _loadPatients();
        },
        onOpenSettings: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => SettingsScreen(apiClient: widget.apiClient),
          ),
        ),
      );
    }

    final pages = [
      _DashboardTab(
        patients: _patients,
        selectedPatient: _selectedPatient,
        summary: _summary,
        meals: _meals,
        loading: _loading,
        error: _error,
        onSelectPatient: (p) {
          setState(() => _selectedPatient = p);
          _loadPatientData(p.id);
        },
        onRefresh: () =>
            _selectedPatient != null ? _loadPatientData(_selectedPatient!.id) : _loadPatients(),
        onRunInvestigation: () => _runInvestigation(),
      ),
      _InvestigationTab(
        patient: _selectedPatient,
        activeRun: _activeRun,
        history: _investigations,
        loading: _loading,
        onRunNormal: () => _runInvestigation(simulateBadDraft: false),
        onRunBadDraft: () => _runInvestigation(simulateBadDraft: true),
        onSelectRun: (run) => setState(() => _activeRun = run),
      ),
      SettingsScreen(
        apiClient: widget.apiClient,
        embedded: true,
        onLogout: () async {
          await widget.apiClient.logout();
          setState(() {
            _patients = [];
            _selectedPatient = null;
            _summary = null;
            _activeRun = null;
          });
        },
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: const BoxDecoration(
                color: GlyCadenceTheme.coral,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            const Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: 'Gly',
                    style: TextStyle(
                      color: GlyCadenceTheme.slateTeal,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  TextSpan(
                    text: 'Cadence',
                    style: TextStyle(
                      color: GlyCadenceTheme.coral,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.brightness_6_outlined),
            tooltip: 'Toggle theme',
            onPressed: widget.onToggleTheme,
          ),
        ],
      ),
      body: pages[_tabIndex],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) => setState(() => _tabIndex = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: 'Dashboard',
          ),
          NavigationDestination(
            icon: Icon(Icons.psychology_outlined),
            selectedIcon: Icon(Icons.psychology),
            label: 'Investigation',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}

class LoginScreen extends StatefulWidget {
  final ApiClient apiClient;
  final VoidCallback onLoggedIn;
  final VoidCallback onOpenSettings;

  const LoginScreen({
    super.key,
    required this.apiClient,
    required this.onLoggedIn,
    required this.onOpenSettings,
  });

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isRegister = false;
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_isRegister) {
        await widget.apiClient.register(_emailController.text, _passwordController.text);
      } else {
        await widget.apiClient.login(_emailController.text, _passwordController.text);
      }
      widget.onLoggedIn();
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('GlyCadence'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'API Settings',
            onPressed: widget.onOpenSettings,
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      _isRegister ? 'Create GlyCadence Account' : 'Sign in to GlyCadence',
                      style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'API: ${widget.apiClient.baseUrl}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 20),
                    TextField(
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(
                        labelText: 'Email',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _passwordController,
                      obscureText: true,
                      decoration: const InputDecoration(
                        labelText: 'Password',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _error!,
                        style: const TextStyle(color: GlyCadenceTheme.coral, fontSize: 13),
                      ),
                    ],
                    const SizedBox(height: 18),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      style: FilledButton.styleFrom(
                        backgroundColor: GlyCadenceTheme.coral,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                      ),
                      child: _busy
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : Text(
                              _isRegister ? 'Register & Sign In' : 'Sign In',
                              style: const TextStyle(fontWeight: FontWeight.bold),
                            ),
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _busy ? null : () => setState(() => _isRegister = !_isRegister),
                      child: Text(
                        _isRegister
                            ? 'Already have an account? Sign in'
                            : 'Need an account? Register',
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DashboardTab extends StatelessWidget {
  final List<PatientSummary> patients;
  final PatientSummary? selectedPatient;
  final GlucoseSummary? summary;
  final List<MealResponseItem> meals;
  final bool loading;
  final String? error;
  final ValueChanged<PatientSummary> onSelectPatient;
  final VoidCallback onRefresh;
  final VoidCallback onRunInvestigation;

  const _DashboardTab({
    required this.patients,
    required this.selectedPatient,
    required this.summary,
    required this.meals,
    required this.loading,
    required this.error,
    required this.onSelectPatient,
    required this.onRefresh,
    required this.onRunInvestigation,
  });

  String _fmt(double? v, {String suffix = ''}) {
    if (v == null) return '—';
    return '${v.toStringAsFixed(1)}$suffix';
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => onRefresh(),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (patients.isNotEmpty)
            Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: selectedPatient?.id,
                    items: patients
                        .map(
                          (p) => DropdownMenuItem(
                            value: p.id,
                            child: Text(
                              '${p.displayName} (${p.cohortType})',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: (id) {
                      if (id == null) return;
                      final match = patients.firstWhere((p) => p.id == id);
                      onSelectPatient(match);
                    },
                  ),
                ),
              ),
            ),
          if (selectedPatient?.isResearchDataset == true) ...[
            const SizedBox(height: 8),
            Chip(
              avatar: const Icon(Icons.science_outlined, size: 18, color: GlyCadenceTheme.coral),
              label: const Text('Research Dataset (Read-Only) · dataset_documented'),
            ),
          ],
          if (error != null) ...[
            const SizedBox(height: 12),
            Card(
              color: Colors.red.shade50,
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(error!, style: TextStyle(color: Colors.red.shade900)),
              ),
            ),
          ],
          if (loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 20),
              child: Center(child: CircularProgressIndicator()),
            ),
          if (summary != null) ...[
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.55,
              children: [
                _MetricCard('TIR (70–180)', _fmt(summary!.tirPct, suffix: '%'), Colors.teal),
                _MetricCard('TBR (<70)', _fmt(summary!.tbrPct, suffix: '%'), GlyCadenceTheme.coral),
                _MetricCard('TAR (>180)', _fmt(summary!.tarPct, suffix: '%'), Colors.amber.shade800),
                _MetricCard('CV%', _fmt(summary!.cvPct, suffix: '%'), GlyCadenceTheme.slateTeal),
              ],
            ),
            const SizedBox(height: 12),
            Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Provenance & Coverage',
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        Chip(label: Text('Coverage: ${summary!.periodCoveragePct.toStringAsFixed(1)}%')),
                        ...summary!.provenanceCounts.entries.map(
                          (e) => Chip(label: Text('${e.key}: ${e.value}')),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Meal Excursion Preview (mg/dL)',
                      style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 180,
                      child: _GlucoseBarChart(meals: meals, meanGlucose: summary!.meanGlucoseMgDl),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: loading ? null : onRunInvestigation,
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Text('Run Multi-Agent Investigation'),
              style: FilledButton.styleFrom(
                backgroundColor: GlyCadenceTheme.slateTeal,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _MetricCard(this.label, this.value, this.color);

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(label, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 6),
            Text(
              value,
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: color),
            ),
          ],
        ),
      ),
    );
  }
}

class _GlucoseBarChart extends StatelessWidget {
  final List<MealResponseItem> meals;
  final double? meanGlucose;

  const _GlucoseBarChart({required this.meals, required this.meanGlucose});

  @override
  Widget build(BuildContext context) {
    final validMeals = meals
        .where((m) => m.peakGlucoseMgDl != null)
        .take(6)
        .toList();
    if (validMeals.isEmpty) {
      final baseline = meanGlucose ?? 120.0;
      return LineChart(
        LineChartData(
          gridData: const FlGridData(show: true),
          titlesData: const FlTitlesData(show: false),
          borderData: FlBorderData(show: false),
          lineBarsData: [
            LineChartBarData(
              spots: [
                FlSpot(0, baseline - 8),
                FlSpot(1, baseline + 6),
                FlSpot(2, baseline + 12),
                FlSpot(3, baseline),
              ],
              isCurved: true,
              color: GlyCadenceTheme.slateTeal,
              barWidth: 3,
            ),
          ],
        ),
      );
    }

    return BarChart(
      BarChartData(
        gridData: const FlGridData(show: true),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              getTitlesWidget: (val, _) {
                final idx = val.toInt();
                if (idx < 0 || idx >= validMeals.length) return const SizedBox.shrink();
                return Text('M${idx + 1}', style: const TextStyle(fontSize: 10));
              },
            ),
          ),
        ),
        barGroups: List.generate(validMeals.length, (i) {
          return BarChartGroupData(
            x: i,
            barRods: [
              BarChartRodData(
                toY: validMeals[i].peakGlucoseMgDl ?? 0,
                color: GlyCadenceTheme.coral,
                width: 16,
                borderRadius: BorderRadius.circular(6),
              ),
            ],
          );
        }),
      ),
    );
  }
}

class _InvestigationTab extends StatelessWidget {
  final PatientSummary? patient;
  final InvestigationRun? activeRun;
  final List<InvestigationRun> history;
  final bool loading;
  final VoidCallback onRunNormal;
  final VoidCallback onRunBadDraft;
  final ValueChanged<InvestigationRun> onSelectRun;

  const _InvestigationTab({
    required this.patient,
    required this.activeRun,
    required this.history,
    required this.loading,
    required this.onRunNormal,
    required this.onRunBadDraft,
    required this.onSelectRun,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: patient == null || loading ? null : onRunNormal,
                icon: const Icon(Icons.play_arrow),
                label: const Text('Run Investigation'),
                style: FilledButton.styleFrom(backgroundColor: GlyCadenceTheme.slateTeal),
              ),
            ),
            const SizedBox(width: 10),
            OutlinedButton(
              onPressed: patient == null || loading ? null : onRunBadDraft,
              child: const Text('Bad Draft Demo'),
            ),
          ],
        ),
        const SizedBox(height: 14),
        if (activeRun == null)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(20),
              child: Text('No investigation run selected yet. Tap Run Investigation above.'),
            ),
          )
        else ...[
          Card(
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    children: [
                      Chip(label: Text('mode: ${activeRun!.executionMode}')),
                      Chip(label: Text('model: ${activeRun!.modelUsed}')),
                      Chip(
                        backgroundColor: activeRun!.safetyPassed
                            ? Colors.teal.shade50
                            : Colors.red.shade50,
                        label: Text(
                          activeRun!.safetyPassed ? 'Verifier: PASSED' : 'Verifier: REJECTED',
                        ),
                      ),
                    ],
                  ),
                  if (activeRun!.executionMode == 'deterministic_fallback') ...[
                    const SizedBox(height: 10),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.amber.shade50,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Text(
                        'Not AI-Generated: Deterministic Template Fallback active.',
                        style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12),
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  const Text('Patient Summary', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text(
                    activeRun!.isSafeToDisplay && activeRun!.primarySummaryPatient != null
                        ? activeRun!.primarySummaryPatient!
                        : 'Narrative suppressed by Safety Verifier (${activeRun!.verifierReport.failedReasons.join(', ')}).',
                  ),
                  if (activeRun!.isSafeToDisplay && activeRun!.clinicianQuestions.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    const Text(
                      'Suggested Questions for Clinician',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 4),
                    ...activeRun!.clinicianQuestions.map(
                      (q) => Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Text('• $q'),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          if (activeRun!.trace.isNotEmpty) ...[
            const SizedBox(height: 12),
            Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Agent Trace Timeline', style: TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    ...activeRun!.trace.map(
                      (step) => ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          step.status == 'rejected' ? Icons.error_outline : Icons.check_circle_outline,
                          color: step.status == 'rejected' ? GlyCadenceTheme.coral : Colors.teal,
                        ),
                        title: Text(step.node, style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text(step.summary),
                        trailing: Text('${step.evidenceCount} ev'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          if (history.length > 1) ...[
            const SizedBox(height: 12),
            const Text('Recent Runs', style: TextStyle(fontWeight: FontWeight.bold)),
            ...history.take(5).map(
                  (r) => ListTile(
                    title: Text('${r.executionMode} · ${r.modelUsed}'),
                    subtitle: Text(r.safetyPassed ? 'PASSED' : 'REJECTED'),
                    onTap: () => onSelectRun(r),
                  ),
                ),
          ],
        ],
      ],
    );
  }
}

class SettingsScreen extends StatefulWidget {
  final ApiClient apiClient;
  final bool embedded;
  final VoidCallback? onLogout;

  const SettingsScreen({
    super.key,
    required this.apiClient,
    this.embedded = false,
    this.onLogout,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _urlController;
  String? _savedMessage;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.apiClient.baseUrl);
  }

  Future<void> _save() async {
    await widget.apiClient.setBaseUrl(_urlController.text);
    setState(() => _savedMessage = 'Saved API URL: ${widget.apiClient.baseUrl}');
  }

  @override
  Widget build(BuildContext context) {
    final body = ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Backend API Base URL',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _urlController,
                  decoration: InputDecoration(
                    hintText: ApiClient.defaultBaseUrl,
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _save,
                  style: FilledButton.styleFrom(backgroundColor: GlyCadenceTheme.slateTeal),
                  child: const Text('Save API URL'),
                ),
                if (_savedMessage != null) ...[
                  const SizedBox(height: 8),
                  Text(_savedMessage!, style: const TextStyle(color: Colors.teal)),
                ],
              ],
            ),
          ),
        ),
        if (widget.onLogout != null) ...[
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: widget.onLogout,
            icon: const Icon(Icons.logout),
            label: const Text('Sign Out'),
          ),
        ],
      ],
    );

    if (widget.embedded) return body;
    return Scaffold(
      appBar: AppBar(title: const Text('API Settings')),
      body: body,
    );
  }
}
