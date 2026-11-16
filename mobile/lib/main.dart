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
  ThemeMode _themeMode = ThemeMode.light;

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
      theme: GlyCadenceTheme.light(),
      darkTheme: GlyCadenceTheme.dark(),
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
  TodayOverviewData? _overview;
  GlucoseReadingsData? _readings;
  GlucoseSummary? _summary;
  List<RecipeItem> _recipes = [];
  String? _initialChatPrompt;

  @override
  void initState() {
    super.initState();
    if (widget.apiClient.isAuthenticated) {
      _loadInitial();
    }
  }

  Future<void> _loadInitial() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await widget.apiClient.listPatients();
      final recs = await widget.apiClient.listRecipes();
      setState(() {
        _patients = list;
        _recipes = recs;
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

  Future<void> _loadPatientData(String patientId, {int days = 7}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        widget.apiClient.getTodayOverview(patientId),
        widget.apiClient.getGlucoseReadings(patientId, days: days),
        widget.apiClient.getAnalyticsSummary(patientId),
      ]);
      setState(() {
        _overview = results[0] as TodayOverviewData;
        _readings = results[1] as GlucoseReadingsData;
        _summary = results[2] as GlucoseSummary;
      });
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _openMealDetail(String recipeId) {
    if (_selectedPatient == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => MealDetailScreen(
          apiClient: widget.apiClient,
          patientId: _selectedPatient!.id,
          recipeId: recipeId,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.apiClient.isAuthenticated) {
      return LoginScreen(
        apiClient: widget.apiClient,
        onLoggedIn: () {
          setState(() {});
          _loadInitial();
        },
        onOpenSettings: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => SettingsScreen(apiClient: widget.apiClient),
          ),
        ),
      );
    }

    final tabs = [
      _TodayTab(
        patient: _selectedPatient,
        overview: _overview,
        readings: _readings,
        loading: _loading,
        error: _error,
        onRefresh: () => _selectedPatient != null
            ? _loadPatientData(_selectedPatient!.id)
            : _loadInitial(),
        onOpenMeal: _openMealDetail,
        onAskCadie: (prompt) {
          setState(() {
            _initialChatPrompt = prompt;
            _tabIndex = 1;
          });
        },
      ),
      _AskCadieTab(
        apiClient: widget.apiClient,
        patientId: _selectedPatient?.id,
        initialPrompt: _initialChatPrompt,
        onConsumePrompt: () => _initialChatPrompt = null,
        onOpenMeal: _openMealDetail,
      ),
      _GlucoseTab(
        readings: _readings,
        summary: _summary,
        onChangeDays: (d) {
          if (_selectedPatient != null) _loadPatientData(_selectedPatient!.id, days: d);
        },
      ),
      _MealsTab(
        recipes: _recipes,
        onOpenRecipe: _openMealDetail,
      ),
      _MoreTab(
        apiClient: widget.apiClient,
        patients: _patients,
        selectedPatient: _selectedPatient,
        onSelectPatient: (p) {
          setState(() => _selectedPatient = p);
          _loadPatientData(p.id);
        },
        onLogout: () async {
          await widget.apiClient.logout();
          setState(() {
            _patients = [];
            _selectedPatient = null;
            _overview = null;
          });
        },
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text.rich(
          TextSpan(
            children: [
              TextSpan(
                text: 'Gly',
                style: TextStyle(fontWeight: FontWeight.w800),
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
        actions: [
          IconButton(
            icon: const Icon(Icons.brightness_6_outlined),
            tooltip: 'Toggle Saffron/Plum theme',
            onPressed: widget.onToggleTheme,
          ),
        ],
      ),
      body: tabs[_tabIndex],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (i) => setState(() => _tabIndex = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Today',
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            selectedIcon: Icon(Icons.chat_bubble),
            label: 'Ask Cadie',
          ),
          NavigationDestination(
            icon: Icon(Icons.show_chart),
            label: 'Glucose',
          ),
          NavigationDestination(
            icon: Icon(Icons.restaurant_menu_outlined),
            selectedIcon: Icon(Icons.restaurant_menu),
            label: 'Meals',
          ),
          NavigationDestination(
            icon: Icon(Icons.grid_view_outlined),
            selectedIcon: Icon(Icons.grid_view),
            label: 'More',
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
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      _isRegister ? 'Create GlyCadence Account' : 'Welcome back',
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
                        style: const TextStyle(color: GlyCadenceTheme.berry, fontSize: 13),
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

class _TodayTab extends StatelessWidget {
  final PatientSummary? patient;
  final TodayOverviewData? overview;
  final GlucoseReadingsData? readings;
  final bool loading;
  final String? error;
  final VoidCallback onRefresh;
  final ValueChanged<String> onOpenMeal;
  final ValueChanged<String> onAskCadie;

  const _TodayTab({
    required this.patient,
    required this.overview,
    required this.readings,
    required this.loading,
    required this.error,
    required this.onRefresh,
    required this.onOpenMeal,
    required this.onAskCadie,
  });

  @override
  Widget build(BuildContext context) {
    final askController = TextEditingController();
    final latest = overview?.latestMgDl ?? readings?.latestMgDl;
    final pts = (readings?.readings ?? []).take(48).toList();

    return RefreshIndicator(
      onRefresh: () async => onRefresh(),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (patient != null) ...[
            Text(
              'Hello, ${patient!.displayName.split(' ').first}',
              style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            Text(
              overview?.greetingLine ?? 'Your daily diabetes summary is ready.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 14),
          ],
          if (error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(error!, style: const TextStyle(color: GlyCadenceTheme.berry)),
              ),
            ),
          if (loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Center(child: CircularProgressIndicator()),
            ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Latest Glucose', style: TextStyle(fontSize: 13)),
                  const SizedBox(height: 4),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Text(
                        latest != null ? '${latest.round()}' : '—',
                        style: const TextStyle(fontSize: 44, fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(width: 6),
                      const Text('mg/dL'),
                      const Spacer(),
                      if (overview?.tirPct != null)
                        Chip(
                          backgroundColor: GlyCadenceTheme.saffron.withValues(alpha: 0.2),
                          label: Text('In target: ${overview!.tirPct!.toStringAsFixed(1)}%'),
                        ),
                    ],
                  ),
                  if (pts.length >= 2) ...[
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 130,
                      child: _SaffronLineChart(
                        points: pts,
                        low: readings?.targetLow ?? 70,
                        high: readings?.targetHigh ?? 180,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          if (overview?.featuredRecipe != null) ...[
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.all(12),
                leading: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.network(
                    overview!.featuredRecipe!['image_url'] as String? ?? '',
                    width: 60,
                    height: 60,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) => const Icon(Icons.restaurant, size: 36),
                  ),
                ),
                title: Text(overview!.featuredRecipe!['name'] as String? ?? ''),
                subtitle: Text(
                  '${overview!.featuredRecipe!['carbs_g']}g carbs · ${overview!.featuredRecipe!['sugar_g']}g sugar',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => onOpenMeal(overview!.featuredRecipe!['recipe_id'] as String),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: askController,
                      decoration: const InputDecoration(
                        hintText: 'Ask Cadie about meals, lows, or Ramadan...',
                        border: InputBorder.none,
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.send, color: GlyCadenceTheme.coral),
                    onPressed: () {
                      final q = askController.text.trim();
                      onAskCadie(q.isEmpty ? 'How has my glucose been this week?' : q);
                    },
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SaffronLineChart extends StatelessWidget {
  final List<GlucoseReadingPoint> points;
  final double low;
  final double high;

  const _SaffronLineChart({
    required this.points,
    required this.low,
    required this.high,
  });

  @override
  Widget build(BuildContext context) {
    final spots = List.generate(
      points.length,
      (i) => FlSpot(i.toDouble(), points[i].glucoseMgDl),
    );
    return LineChart(
      LineChartData(
        minY: 50,
        maxY: 230,
        gridData: const FlGridData(show: true),
        titlesData: const FlTitlesData(show: false),
        borderData: FlBorderData(show: false),
        rangeAnnotations: RangeAnnotations(
          horizontalRangeAnnotations: [
            HorizontalRangeAnnotation(
              y1: low,
              y2: high,
              color: GlyCadenceTheme.saffron.withValues(alpha: 0.18),
            ),
          ],
        ),
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            color: GlyCadenceTheme.coral,
            barWidth: 2.5,
            dotData: const FlDotData(show: false),
          ),
        ],
      ),
    );
  }
}

class _AskCadieTab extends StatefulWidget {
  final ApiClient apiClient;
  final String? patientId;
  final String? initialPrompt;
  final VoidCallback onConsumePrompt;
  final ValueChanged<String> onOpenMeal;

  const _AskCadieTab({
    required this.apiClient,
    required this.patientId,
    required this.initialPrompt,
    required this.onConsumePrompt,
    required this.onOpenMeal,
  });

  @override
  State<_AskCadieTab> createState() => _AskCadieTabState();
}

class _AskCadieTabState extends State<_AskCadieTab> {
  final _ctrl = TextEditingController();
  List<ChatSessionItem> _sessions = [];
  String? _activeSessionId;
  List<ChatMessageItem> _messages = [];
  List<dynamic> _lastHelpers = [];
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _initSessions();
  }

  Future<void> _initSessions() async {
    if (widget.patientId == null) return;
    final list = await widget.apiClient.listChatSessions(widget.patientId!);
    setState(() {
      _sessions = list;
      _activeSessionId = list.isNotEmpty ? list.first.id : null;
    });
    if (_activeSessionId != null) {
      await _loadMessages();
    }
    if (widget.initialPrompt != null && widget.initialPrompt!.isNotEmpty) {
      final p = widget.initialPrompt!;
      widget.onConsumePrompt();
      await _send(p);
    }
  }

  Future<void> _loadMessages() async {
    if (widget.patientId == null || _activeSessionId == null) return;
    final msgs = await widget.apiClient.getChatMessages(widget.patientId!, _activeSessionId!);
    setState(() => _messages = msgs);
  }

  Future<void> _send(String text) async {
    if (widget.patientId == null || text.trim().isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      String sid = _activeSessionId ?? '';
      if (sid.isEmpty) {
        final created = await widget.apiClient.createChatSession(
          widget.patientId!,
          title: text.trim().substring(0, text.trim().length > 40 ? 40 : text.trim().length),
        );
        sid = created.id;
        _activeSessionId = sid;
      }
      final turn = await widget.apiClient.sendChatMessage(widget.patientId!, sid, text.trim());
      final pMsg = ChatMessageItem.fromJson(turn['patient_message'] as Map<String, dynamic>);
      final cMsg = ChatMessageItem.fromJson(turn['cadie_message'] as Map<String, dynamic>);
      setState(() {
        _messages = [..._messages, pMsg, cMsg];
        _lastHelpers = turn['helpers_used'] as List<dynamic>? ?? [];
      });
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            children: [
              Expanded(
                child: DropdownButton<String>(
                  isExpanded: true,
                  hint: const Text('Saved conversations'),
                  value: _activeSessionId,
                  items: _sessions
                      .map((s) => DropdownMenuItem(value: s.id, child: Text(s.title, overflow: TextOverflow.ellipsis)))
                      .toList(),
                  onChanged: (id) {
                    setState(() => _activeSessionId = id);
                    _loadMessages();
                  },
                ),
              ),
              IconButton(
                icon: const Icon(Icons.add_comment_outlined, color: GlyCadenceTheme.coral),
                onPressed: () async {
                  if (widget.patientId == null) return;
                  final created = await widget.apiClient.createChatSession(widget.patientId!);
                  setState(() {
                    _sessions = [created, ..._sessions];
                    _activeSessionId = created.id;
                    _messages = [];
                  });
                },
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: _messages.length,
            itemBuilder: (_, i) {
              final m = _messages[i];
              final isMe = m.role == 'patient';
              return Align(
                alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  margin: const EdgeInsets.only(bottom: 10),
                  padding: const EdgeInsets.all(14),
                  constraints: const BoxConstraints(maxWidth: 340),
                  decoration: BoxDecoration(
                    color: isMe ? GlyCadenceTheme.ink : Theme.of(context).cardColor,
                    borderRadius: BorderRadius.circular(18),
                    border: isMe ? null : Border.all(color: GlyCadenceTheme.clay),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        m.content,
                        style: TextStyle(color: isMe ? Colors.white : null),
                      ),
                      for (final card in m.cards)
                        if (card['type'] == 'meal_card')
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: ActionChip(
                              label: Text(card['name'] as String? ?? 'View Meal'),
                              onPressed: () => widget.onOpenMeal(card['recipe_id'] as String),
                            ),
                          )
                        else if (card['type'] == 'urgent_card')
                          Container(
                            margin: const EdgeInsets.only(top: 8),
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: GlyCadenceTheme.berry.withValues(alpha: 0.14),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: const Text(
                              'Urgent 15-15 Rule Active — Take 15g fast sugar and recheck in 15 min.',
                              style: TextStyle(fontWeight: FontWeight.bold, color: GlyCadenceTheme.berry),
                            ),
                          ),
                      if (!isMe) ...[
                        const SizedBox(height: 6),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text(
                              'Checked by Safety Check',
                              style: TextStyle(fontSize: 11, color: Colors.teal),
                            ),
                            if (_lastHelpers.isNotEmpty)
                              TextButton(
                                onPressed: () => showDialog(
                                  context: context,
                                  builder: (_) => AlertDialog(
                                    title: const Text('Behind this answer'),
                                    content: Column(
                                      mainAxisSize: MainAxisSize.min,
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: _lastHelpers
                                          .map((h) => Text('• ${h['helper']}: ${h['summary']}'))
                                          .toList(),
                                    ),
                                  ),
                                ),
                                child: const Text('Behind this answer', style: TextStyle(fontSize: 11)),
                              ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
              );
            },
          ),
        ),
        if (_sending) const LinearProgressIndicator(color: GlyCadenceTheme.coral),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _ctrl,
                  decoration: const InputDecoration(
                    hintText: 'Ask Cadie...',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _sending
                    ? null
                    : () {
                        final t = _ctrl.text;
                        _ctrl.clear();
                        _send(t);
                      },
                style: FilledButton.styleFrom(backgroundColor: GlyCadenceTheme.coral),
                child: const Icon(Icons.send, color: Colors.white),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _GlucoseTab extends StatelessWidget {
  final GlucoseReadingsData? readings;
  final GlucoseSummary? summary;
  final ValueChanged<int> onChangeDays;

  const _GlucoseTab({
    required this.readings,
    required this.summary,
    required this.onChangeDays,
  });

  @override
  Widget build(BuildContext context) {
    final pts = readings?.readings ?? [];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(
          spacing: 8,
          children: [1, 7, 14, 30]
              .map(
                (d) => ChoiceChip(
                  label: Text(d == 1 ? 'Today' : '${d}d'),
                  selected: false,
                  onSelected: (_) => onChangeDays(d),
                ),
              )
              .toList(),
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(readings?.sourceSummary ?? 'Sensor Curve',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                SizedBox(
                  height: 200,
                  child: pts.length >= 2
                      ? _SaffronLineChart(
                          points: pts,
                          low: readings?.targetLow ?? 70,
                          high: readings?.targetHigh ?? 180,
                        )
                      : const Center(child: Text('No readings loaded yet.')),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        if (summary != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Time in Range', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 12,
                    children: [
                      Text('Below 70: ${summary!.tbrPct?.toStringAsFixed(1) ?? '—'}%',
                          style: const TextStyle(color: GlyCadenceTheme.berry, fontWeight: FontWeight.w600)),
                      Text('In target: ${summary!.tirPct?.toStringAsFixed(1) ?? '—'}%',
                          style: const TextStyle(color: GlyCadenceTheme.saffron, fontWeight: FontWeight.w700)),
                      Text('Above 180: ${summary!.tarPct?.toStringAsFixed(1) ?? '—'}%',
                          style: const TextStyle(color: GlyCadenceTheme.terracotta, fontWeight: FontWeight.w600)),
                    ],
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _MealsTab extends StatefulWidget {
  final List<RecipeItem> recipes;
  final ValueChanged<String> onOpenRecipe;

  const _MealsTab({required this.recipes, required this.onOpenRecipe});

  @override
  State<_MealsTab> createState() => _MealsTabState();
}

class _MealsTabState extends State<_MealsTab> {
  String _slot = 'all';

  @override
  Widget build(BuildContext context) {
    final filtered = _slot == 'all'
        ? widget.recipes
        : widget.recipes.where((r) => r.slot == _slot).toList();

    return Column(
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.all(12),
          child: Row(
            children: ['all', 'breakfast', 'lunch', 'dinner', 'snack', 'suhoor', 'iftar']
                .map(
                  (s) => Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(s.toUpperCase()),
                      selected: _slot == s,
                      onSelected: (_) => setState(() => _slot = s),
                    ),
                  ),
                )
                .toList(),
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            itemCount: filtered.length,
            itemBuilder: (_, i) {
              final r = filtered[i];
              return Card(
                margin: const EdgeInsets.only(bottom: 10),
                child: ListTile(
                  leading: ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.network(
                      r.imageUrl,
                      width: 56,
                      height: 56,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const Icon(Icons.restaurant_menu),
                    ),
                  ),
                  title: Text(r.name),
                  subtitle: Text(
                      '${r.nutrition.carbsG}g carbs · ${r.nutrition.sugarG}g sugar · ${r.nutrition.glBand} GL'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => widget.onOpenRecipe(r.id),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class MealDetailScreen extends StatefulWidget {
  final ApiClient apiClient;
  final String patientId;
  final String recipeId;

  const MealDetailScreen({
    super.key,
    required this.apiClient,
    required this.patientId,
    required this.recipeId,
  });

  @override
  State<MealDetailScreen> createState() => _MealDetailScreenState();
}

class _MealDetailScreenState extends State<MealDetailScreen> {
  MealDetailData? _detail;
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.apiClient.getRecipeDetail(widget.recipeId, widget.patientId).then((d) {
      if (mounted) setState(() => _detail = d);
    }).catchError((e) {
      if (mounted) setState(() => _error = e.toString());
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_detail?.recipe.name ?? 'Meal Details')),
      body: _error != null
          ? Center(child: Text(_error!))
          : _detail == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(20),
                      child: Image.network(
                        _detail!.recipe.imageUrl,
                        height: 200,
                        width: double.infinity,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) => const SizedBox(height: 120),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(_detail!.recipe.name,
                        style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 4),
                    Text('Best time: ${_detail!.recommendedTimeWindow} — ${_detail!.bestTimeReason}'),
                    const SizedBox(height: 12),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Nutrition per portion',
                                style: TextStyle(fontWeight: FontWeight.bold)),
                            const SizedBox(height: 8),
                            Wrap(
                              spacing: 10,
                              runSpacing: 8,
                              children: [
                                Chip(label: Text('Carbs: ${_detail!.recipe.nutrition.carbsG}g')),
                                Chip(label: Text('Sugar: ${_detail!.recipe.nutrition.sugarG}g')),
                                Chip(label: Text('Fibre: ${_detail!.recipe.nutrition.fibreG}g')),
                                Chip(label: Text('Protein: ${_detail!.recipe.nutrition.proteinG}g')),
                                Chip(label: Text('${_detail!.recipe.nutrition.glBand} GL')),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('How this meal has gone for you',
                                style: TextStyle(fontWeight: FontWeight.bold)),
                            const SizedBox(height: 6),
                            Text(_detail!.personalSummary),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Recipe Steps', style: TextStyle(fontWeight: FontWeight.bold)),
                            const SizedBox(height: 6),
                            ..._detail!.recipe.steps.asMap().entries.map(
                                  (e) => Padding(
                                    padding: const EdgeInsets.only(bottom: 4),
                                    child: Text('${e.key + 1}. ${e.value}'),
                                  ),
                                ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}

class _MoreTab extends StatelessWidget {
  final ApiClient apiClient;
  final List<PatientSummary> patients;
  final PatientSummary? selectedPatient;
  final ValueChanged<PatientSummary> onSelectPatient;
  final VoidCallback onLogout;

  const _MoreTab({
    required this.apiClient,
    required this.patients,
    required this.selectedPatient,
    required this.onSelectPatient,
    required this.onLogout,
  });

  @override
  Widget build(BuildContext context) {
    final pid = selectedPatient?.id;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (patients.isNotEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  isExpanded: true,
                  value: selectedPatient?.id,
                  items: patients
                      .map((p) => DropdownMenuItem(value: p.id, child: Text(p.displayName)))
                      .toList(),
                  onChanged: (id) {
                    if (id == null) return;
                    onSelectPatient(patients.firstWhere((p) => p.id == id));
                  },
                ),
              ),
            ),
          ),
        const SizedBox(height: 10),
        ListTile(
          leading: const Icon(Icons.medication_outlined, color: GlyCadenceTheme.coral),
          title: const Text('Medicines (Dose Diary)'),
          onTap: pid == null
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(
                        builder: (_) => _GenericCareScreen(
                              title: 'Medicines',
                              loader: () => apiClient.getMedicinesSummary(pid),
                            )),
                  ),
        ),
        ListTile(
          leading: const Icon(Icons.favorite_border, color: GlyCadenceTheme.coral),
          title: const Text('Wellbeing (Kindred)'),
          onTap: pid == null
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(
                        builder: (_) => _GenericCareScreen(
                              title: 'Wellbeing',
                              loader: () => apiClient.getWellbeingSummary(pid),
                            )),
                  ),
        ),
        ListTile(
          leading: const Icon(Icons.nights_stay_outlined, color: GlyCadenceTheme.saffron),
          title: const Text('Ramadan & Fasting (Roza Guide)'),
          onTap: pid == null
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(
                        builder: (_) => _GenericCareScreen(
                              title: 'Roza Guide',
                              loader: () => apiClient.getRamadanPlan(pid),
                            )),
                  ),
        ),
        ListTile(
          leading: const Icon(Icons.assignment_outlined, color: GlyCadenceTheme.coral),
          title: const Text('Doctor Visit Questions'),
          onTap: pid == null
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(
                        builder: (_) => _GenericCareScreen(
                              title: 'Doctor Visit',
                              loader: () => apiClient.getVisitReport(pid),
                            )),
                  ),
        ),
        ListTile(
          leading: const Icon(Icons.settings_outlined),
          title: const Text('API Settings & Sign Out'),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => SettingsScreen(apiClient: apiClient, onLogout: onLogout),
            ),
          ),
        ),
      ],
    );
  }
}

class _GenericCareScreen extends StatelessWidget {
  final String title;
  final Future<Map<String, dynamic>> Function() loader;

  const _GenericCareScreen({required this.title, required this.loader});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: FutureBuilder<Map<String, dynamic>>(
        future: loader(),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) return Center(child: Text('${snap.error}'));
          final data = snap.data ?? {};
          final lines = <String>[];
          if (data['personal_summary'] is List) {
            lines.addAll((data['personal_summary'] as List).map((e) => e.toString()));
          }
          if (data['questions'] is List) {
            for (final q in data['questions'] as List) {
              if (q is Map) lines.add('• ${q['question']} (Why: ${q['why']})');
            }
          }
          if (data['medications'] is List) {
            for (final m in data['medications'] as List) {
              if (m is Map) lines.add('${m['name']} ${m['dose'] ?? ''} — ${m['plain_explanation']}');
            }
          }
          if (data['roza'] is Map) {
            final findings = (data['roza'] as Map)['findings'] as List? ?? [];
            for (final f in findings) {
              if (f is Map) lines.add(f['rendered_text']?.toString() ?? '');
            }
          }
          if (data['agent_summary'] is Map) {
            final findings = (data['agent_summary'] as Map)['findings'] as List? ?? [];
            for (final f in findings) {
              if (f is Map) lines.add(f['rendered_text']?.toString() ?? '');
            }
          }
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: lines.length,
            itemBuilder: (_, i) => Card(
              margin: const EdgeInsets.only(bottom: 10),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(lines[i]),
              ),
            ),
          );
        },
      ),
    );
  }
}

class SettingsScreen extends StatefulWidget {
  final ApiClient apiClient;
  final VoidCallback? onLogout;

  const SettingsScreen({super.key, required this.apiClient, this.onLogout});

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
    return Scaffold(
      appBar: AppBar(title: const Text('API Settings')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('Backend API Base URL',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
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
                    style: FilledButton.styleFrom(backgroundColor: GlyCadenceTheme.coral),
                    child: const Text('Save API URL', style: TextStyle(color: Colors.white)),
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
              onPressed: () {
                widget.onLogout!();
                Navigator.of(context).pop();
              },
              icon: const Icon(Icons.logout),
              label: const Text('Sign Out'),
            ),
          ],
        ],
      ),
    );
  }
}
