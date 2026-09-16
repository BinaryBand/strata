import 'dart:async';

import 'package:flutter/foundation.dart';

import 'data/strata_cli.dart';
import 'mock_data.dart';
import 'models.dart';

class AppState extends ChangeNotifier {
  List<Runbook> _runbooks = mockRunbooks;
  List<DeviceInfo> _devices = mockDevices;
  List<MachineInfo> _machineList = mockMachines;
  bool usingLiveData = false;
  List<ImportFailure> importFailures = [];

  StrataApi? _api;
  bool get hasLiveApi => _api != null;
  bool needsToken = false;

  List<String> machineIds = mockMachines.map((m) => m.id).toList();
  bool addMachineOpen = false;
  String? confirmingId;

  Screen screen = Screen.runbooks;
  RunbookCategory? selectedCategory;
  String selectedDotted = 'services.install_jellyfin';

  bool runView = false;

  RunbookStatus? _runbookStatus;
  int _statusRequestId = 0;
  bool _hasVaultPassword = false;
  final Map<String, bool> _installedByDotted = {};

  RunHandle? _run;
  Timer? _pollTimer;

  String targetId = 'local';
  bool targetOpen = false;

  String query = '';
  bool sidebarOpen = false;
  bool mobileShowDetail = false;

  TestState testState = TestState.idle;
  String toast = '';

  Timer? _toastTimer;

  @override
  void dispose() {
    _toastTimer?.cancel();
    _pollTimer?.cancel();
    disconnectFromStrata();
    super.dispose();
  }

  void _update(VoidCallback fn) {
    fn();
    notifyListeners();
  }

  /// Runs `fn` against the live API, routing a 401 into the "needs token"
  /// prompt and any other failure into a toast. Returns null on any failure,
  /// so callers can treat a null result as "nothing happened."
  Future<T?> _call<T>(Future<T> Function(StrataApi api) fn) async {
    final api = _api;
    if (api == null) return null;
    try {
      return await fn(api);
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        _update(() => needsToken = true);
      } else {
        showToast(e.message);
      }
      return null;
    } catch (e) {
      showToast('$e');
      return null;
    }
  }

  void submitToken(String value) {
    final api = _api;
    if (api == null || value.trim().isEmpty) return;
    _api = StrataApi(baseUrl: api.baseUrl, token: value.trim());
    _update(() => needsToken = false);
    showToast('Access token set — try again.');
  }

  // ---- navigation ----

  void selectScreenRunbooks() => _update(() {
        screen = Screen.runbooks;
        sidebarOpen = false;
      });

  void selectScreenApps() => _update(() {
        screen = Screen.apps;
        targetOpen = false;
        sidebarOpen = false;
      });

  void selectScreenMachines() => _update(() {
        screen = Screen.machines;
        targetOpen = false;
        sidebarOpen = false;
      });

  void toggleSidebar() => _update(() => sidebarOpen = !sidebarOpen);

  void closeSidebar() => _update(() => sidebarOpen = false);

  void backToListMobile() => _update(() => mobileShowDetail = false);

  void closeOverlays() => _update(() {
        targetOpen = false;
        sidebarOpen = false;
        confirmingId = null;
      });

  // ---- runbooks screen ----

  void selectAllCategories() => _update(() {
        selectedCategory = null;
        sidebarOpen = false;
      });

  void selectCategory(RunbookCategory key) => _update(() {
        selectedCategory = key;
        sidebarOpen = false;
      });

  void selectRunbook(String dotted) {
    _update(() {
      selectedDotted = dotted;
      runView = false;
      mobileShowDetail = true;
    });
    unawaited(refreshRunbookStatus());
  }

  void setQuery(String value) => _update(() => query = value);

  void clearQuery() => _update(() => query = '');

  void backToDetail() => _update(() => runView = false);

  void jumpTo(String dotted) {
    _update(() {
      screen = Screen.runbooks;
      selectedDotted = dotted;
      runView = false;
      mobileShowDetail = true;
      selectedCategory = null;
      query = '';
    });
    unawaited(refreshRunbookStatus());
  }

  /// Jumps to an app's install runbook and, if it turns out to be ready to
  /// run without any input, starts it immediately -- otherwise the operator
  /// lands on the detail view showing what it still needs.
  Future<void> installApp(String dotted) async {
    jumpTo(dotted);
    if (!hasLiveApi) return;
    await refreshRunbookStatus();
    if (canRun) await startRun();
  }

  // ---- target switcher ----

  void toggleTargetMenu() => _update(() => targetOpen = !targetOpen);

  void selectTarget(String id) {
    final device = _devices.firstWhere((d) => d.id == id, orElse: () => _devices.first);
    _update(() {
      targetId = id;
      targetOpen = false;
    });
    showToast('Now running against ${device.name}');
    unawaited(refreshRunbookStatus());
  }

  // ---- runbook readiness (live) ----

  /// The declared guards for the selected runbook paired with their live
  /// status. Falls back to [GuardReadiness.unknown] for every guard when the
  /// live fetch hasn't landed (or failed, or is for a different runbook) --
  /// [statusLoaded] tells a caller which case it's in.
  List<GuardStep> get guardSteps {
    final rb = selectedRunbook;
    final status = _runbookStatus;
    if (status == null ||
        status.dottedName != rb.dotted ||
        status.guards.length != rb.guards.length) {
      return [for (final g in rb.guards) GuardStep(guard: g, status: GuardReadiness.unknown)];
    }
    return [
      for (var i = 0; i < rb.guards.length; i++)
        GuardStep(guard: rb.guards[i], status: status.guards[i].status),
    ];
  }

  bool get statusLoaded => _runbookStatus?.dottedName == selectedRunbook.dotted;

  List<GuardStep> get _missingInputSteps => !statusLoaded
      ? const []
      : guardSteps
          .where((s) => s.needsInputWhenMissing && s.status == GuardReadiness.missing)
          .toList();

  bool get needsVaultPasswordFirst =>
      statusLoaded && !_hasVaultPassword && _missingInputSteps.isNotEmpty;

  bool get canRun =>
      hasLiveApi &&
      !selectedBlockedByTarget &&
      statusLoaded &&
      !needsVaultPasswordFirst &&
      _missingInputSteps.isEmpty &&
      !isRunning;

  Future<void> refreshRunbookStatus() async {
    if (!hasLiveApi) return;
    final requestId = ++_statusRequestId;
    final dotted = selectedDotted;
    final target = targetId;
    final status = await _call((api) => api.fetchRunbookStatus(dotted, target));
    if (status == null || requestId != _statusRequestId) return;
    _update(() => _runbookStatus = status);
  }

  Future<void> submitVaultPassword(String value) async {
    if (value.trim().isEmpty) return;
    final ok = await _call((api) => api.setVaultPassword(value.trim()).then((_) => true));
    if (ok == null) return;
    _hasVaultPassword = true;
    showToast('Vault unlocked.');
    notifyListeners();
  }

  /// Saves a value for a Secret/Storage guard, or the sudo-password
  /// prerequisite -- the only guard kinds a missing status can't self-heal
  /// during a run. `guard.label` is parsed back to a vault key the same way
  /// gui_server.py built it (`"Secret: X"` / `"Storage: X"`); the sudo
  /// prerequisite is special-cased since its label doesn't carry a vault key.
  Future<void> submitGuardValue(Guard guard, String value) async {
    if (value.trim().isEmpty) return;
    final String vaultKey;
    if (guard.type == GuardType.prerequisite && guard.label == 'Sudo password') {
      vaultKey = 'ansible_become_password';
    } else if (guard.type == GuardType.secret || guard.type == GuardType.storage) {
      vaultKey = guard.label.split(': ').last;
    } else {
      showToast('Strata can\'t set a value for "${guard.label}" from here.');
      return;
    }
    final ok = await _call((api) => api.setSecret(vaultKey, value.trim()).then((_) => true));
    if (ok == null) return;
    showToast('Saved.');
    await refreshRunbookStatus();
  }

  // ---- run lifecycle (live) ----

  RunHandle? get run => _run;
  bool get isRunning => _run?.status == RunLifecycle.running;

  Future<void> startRun() async {
    if (!canRun) return;
    _update(() {
      runView = true;
      _run = null;
    });
    final runId = await _call((api) => api.startRun(selectedDotted, targetId, null));
    if (runId == null) {
      _update(() => runView = false);
      return;
    }
    _pollTimer?.cancel();
    await _pollOnce(runId);
    _pollTimer = Timer.periodic(const Duration(milliseconds: 900), (_) => _pollOnce(runId));
  }

  Future<void> _pollOnce(String runId) async {
    final handle = await _call((api) => api.pollRun(runId));
    if (handle == null) return;
    _update(() => _run = handle);
    if (handle.status == RunLifecycle.running) return;
    _pollTimer?.cancel();
    _pollTimer = null;
    if (handle.status == RunLifecycle.succeeded) {
      showToast('Runbook completed on ${activeDevice.name}');
    }
    unawaited(refreshRunbookStatus());
  }

  void finishRun() {
    // The completion toast already fired from _pollOnce when the run ended;
    // this just leaves the run view.
    _update(() {
      runView = false;
      mobileShowDetail = false;
      _run = null;
    });
  }

  Future<void> retryRun() => startRun();

  // ---- machines screen ----

  void openAddMachine() => _update(() {
        addMachineOpen = true;
        confirmingId = null;
        testState = TestState.idle;
      });

  void closeAddMachine() => _update(() {
        addMachineOpen = false;
        testState = TestState.idle;
      });

  void askRemove(String id) => _update(() {
        confirmingId = id;
        addMachineOpen = false;
      });

  void cancelRemove() => _update(() => confirmingId = null);

  Future<bool> testConnection(String host, {int port = 22}) async {
    _update(() => testState = TestState.testing);
    final reachable = await _call((api) => api.checkReachable(host, port: port));
    _update(() => testState = reachable == true ? TestState.ok : TestState.failed);
    return reachable ?? false;
  }

  Future<void> addMachine({
    required String name,
    required String host,
    String user = 'root',
    int? port,
  }) async {
    final ok = await _call(
      (api) => api.addDevice(name: name, host: host, user: user, port: port).then((_) => true),
    );
    if (ok == null) return;
    showToast('Added $name.');
    closeAddMachine();
    await _reloadGuiData();
  }

  Future<void> confirmRemove(String id) async {
    final ok = await _call((api) => api.removeDevice(id).then((_) => true));
    _update(() => confirmingId = null);
    if (ok == null) return;
    if (targetId == id) {
      final controller = _devices.firstWhere((d) => d.isController, orElse: () => _devices.first);
      targetId = controller.id;
    }
    showToast('Removed $id.');
    await _reloadGuiData();
  }

  // ---- toast ----

  void showToast(String msg) {
    _update(() => toast = msg);
    _toastTimer?.cancel();
    _toastTimer = Timer(const Duration(milliseconds: 2600), () {
      _update(() => toast = '');
    });
  }

  // ---- loading real data ----

  Future<void> loadRealData() async {
    try {
      final api = await connectToStrata();
      if (api == null) return;
      final data = await api.fetchGuiData();
      _api = api;
      _applyGuiData(data);
      usingLiveData = true;
      notifyListeners();
      if (importFailures.isNotEmpty) {
        showToast('${importFailures.length} runbook(s) failed to import — see terminal');
      }
      unawaited(refreshRunbookStatus());
      unawaited(_loadVaultStatus());
      unawaited(_loadAppInstallStatus());
    } catch (_) {
      // Real data is a nice-to-have layered on top of a fully usable mock
      // app; a broken `strata` invocation (not on PATH, run outside the
      // repo) should not block the GUI, just quietly keep the sample data.
    }
  }

  void _applyGuiData(GuiData data) {
    final controller = data.devices.firstWhere(
      (d) => d.isController,
      orElse: () => data.devices.first,
    );
    _runbooks = data.runbooks;
    _devices = data.devices.map((d) => d.toDeviceInfo()).toList();
    _machineList = data.devices.map((d) => d.toMachineInfo()).toList();
    machineIds = data.devices.map((d) => d.name).toList();
    if (!machineIds.contains(targetId)) targetId = controller.name;
    if (!_runbooks.any((r) => r.dotted == selectedDotted) && _runbooks.isNotEmpty) {
      selectedDotted = _runbooks.first.dotted;
    }
    importFailures = data.importFailures;
  }

  Future<void> _reloadGuiData() async {
    final data = await _call((api) => api.fetchGuiData());
    if (data == null) return;
    _applyGuiData(data);
    notifyListeners();
  }

  Future<void> _loadVaultStatus() async {
    final result = await _call((api) => api.getVaultStatus());
    if (result == null) return;
    _hasVaultPassword = result;
    notifyListeners();
  }

  Future<void> _loadAppInstallStatus() async {
    for (final app in mockApps) {
      final status = await _call((api) => api.fetchRunbookStatus(app.installDotted, targetId));
      if (status?.installed != null) {
        _installedByDotted[app.installDotted] = status!.installed!;
      }
    }
    notifyListeners();
  }

  // ---- derived data ----

  List<Runbook> get runbooks => _runbooks;

  List<Runbook> get filteredRunbooks {
    final q = query.trim().toLowerCase();
    return runbooks.where((r) {
      if (selectedCategory != null && r.category != selectedCategory) return false;
      if (q.isEmpty) return true;
      return r.alias.toLowerCase().contains(q) ||
          r.dotted.toLowerCase().contains(q) ||
          r.desc.toLowerCase().contains(q);
    }).toList();
  }

  String? get firstMatchDotted {
    final f = filteredRunbooks;
    return f.isEmpty ? null : f.first.dotted;
  }

  Map<RunbookCategory, List<Runbook>> get groupedSections {
    final map = <RunbookCategory, List<Runbook>>{};
    for (final r in filteredRunbooks) {
      map.putIfAbsent(r.category, () => []).add(r);
    }
    return map;
  }

  Runbook get selectedRunbook =>
      runbooks.firstWhere((r) => r.dotted == selectedDotted, orElse: () => runbooks.first);

  bool get selectedBlockedByTarget =>
      selectedRunbook.guards.any((g) => g.type == GuardType.controllerOnly) && !targetIsController;

  DeviceInfo get activeDevice =>
      _devices.firstWhere((d) => d.id == targetId, orElse: () => _devices.first);

  bool get targetIsController => activeDevice.isController;

  List<DeviceInfo> get devices => _devices.where((d) => machineIds.contains(d.id)).toList();

  List<MachineInfo> get machines =>
      _machineList.where((m) => machineIds.contains(m.id)).toList();

  List<ServerApp> get apps => mockApps.map((app) {
        final installed = _installedByDotted[app.installDotted];
        if (installed == null) return app;
        return ServerApp(
          id: app.id,
          name: app.name,
          initial: app.initial,
          port: app.port,
          owner: app.owner,
          isInstalled: installed,
          canOpen: app.canOpen,
          toggleLabel: app.toggleLabel,
          pathList: app.pathList,
          stateLabel: installed ? app.stateLabel : 'Not installed',
          hasMount: app.hasMount,
          mountWarning: app.mountWarning,
          mountText: app.mountText,
          iconGradientStart: app.iconGradientStart,
          iconGradientEnd: app.iconGradientEnd,
          iconTextColor: app.iconTextColor,
          installDotted: app.installDotted,
        );
      }).toList();
}
