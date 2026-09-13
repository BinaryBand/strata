import 'dart:async';

import 'package:flutter/foundation.dart';

import 'data/strata_cli.dart';
import 'mock_data.dart';
import 'models.dart';
import 'theme.dart';

class AppState extends ChangeNotifier {
  List<Runbook> _runbooks = mockRunbooks;
  List<DeviceInfo> _devices = mockDevices;
  List<MachineInfo> _machineList = mockMachines;
  bool usingLiveData = false;
  List<ImportFailure> importFailures = [];

  List<String> machineIds = mockMachines.map((m) => m.id).toList();
  bool addMachineOpen = false;
  String? confirmingId;

  Screen screen = Screen.runbooks;
  RunbookCategory? selectedCategory;
  String selectedDotted = 'services.install_jellyfin';

  bool runView = false;
  RunScenario runScenario = RunScenario.progress;

  String targetId = 'local';
  bool targetOpen = false;

  String query = '';
  bool sidebarOpen = false;
  bool mobileShowDetail = false;

  TestState testState = TestState.idle;
  String toast = '';

  Timer? _toastTimer;
  Timer? _testTimer;

  @override
  void dispose() {
    _toastTimer?.cancel();
    _testTimer?.cancel();
    super.dispose();
  }

  void _update(VoidCallback fn) {
    fn();
    notifyListeners();
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

  void selectRunbook(String dotted) => _update(() {
        selectedDotted = dotted;
        runView = false;
        mobileShowDetail = true;
      });

  void setQuery(String value) => _update(() => query = value);

  void clearQuery() => _update(() => query = '');

  void startRun() => _update(() {
        runView = true;
        runScenario = RunScenario.progress;
      });

  void backToDetail() => _update(() => runView = false);

  void setScenario(RunScenario scenario) => _update(() => runScenario = scenario);

  void jumpTo(String dotted) => _update(() {
        screen = Screen.runbooks;
        selectedDotted = dotted;
        runView = false;
        mobileShowDetail = true;
        selectedCategory = null;
        query = '';
      });

  void finishRun() {
    final device = _devices.firstWhere((d) => d.id == targetId, orElse: () => _devices.first);
    _update(() {
      runView = false;
      mobileShowDetail = false;
    });
    showToast('Runbook completed on ${device.name}');
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
  }

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

  void confirmRemove(String id) => _update(() {
        machineIds = machineIds.where((m) => m != id).toList();
        confirmingId = null;
        if (targetId == id) targetId = 'local';
      });

  void testConnection() {
    _update(() => testState = TestState.testing);
    _testTimer?.cancel();
    _testTimer = Timer(const Duration(milliseconds: 1100), () {
      _update(() => testState = TestState.ok);
    });
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
      final data = kIsWeb ? await loadFromHttpApi() : await loadFromStrataCli();
      final controller = data.devices.firstWhere(
        (d) => d.isController,
        orElse: () => data.devices.first,
      );
      _runbooks = data.runbooks;
      _devices = data.devices.map((d) => d.toDeviceInfo()).toList();
      _machineList = data.devices.map((d) => d.toMachineInfo()).toList();
      machineIds = data.devices.map((d) => d.name).toList();
      targetId = controller.name;
      if (!_runbooks.any((r) => r.dotted == selectedDotted) && _runbooks.isNotEmpty) {
        selectedDotted = _runbooks.first.dotted;
      }
      importFailures = data.importFailures;
      usingLiveData = true;
      notifyListeners();
      if (importFailures.isNotEmpty) {
        showToast('${importFailures.length} runbook(s) failed to import — see terminal');
      }
    } catch (_) {
      // Real data is a nice-to-have layered on top of a fully usable mock
      // app; a broken `strata` invocation (not on PATH, run outside the
      // repo) should not block the GUI, just quietly keep the sample data.
    }
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

  List<ServerApp> get apps => mockApps;

  List<GuardStep> buildRunSteps(Runbook runbook, RunScenario scenario) {
    final guards = runbook.guards;
    if (guards.isEmpty) return [];

    if (scenario == RunScenario.complete) {
      return guards.map((g) => GuardStep(guard: g, status: GuardStepStatus.satisfied)).toList();
    }

    if (scenario == RunScenario.failed) {
      var failIdx = guards.indexWhere((g) => g.type == GuardType.requires);
      if (failIdx == -1) failIdx = guards.indexWhere((g) => g.type == GuardType.mount);
      if (failIdx == -1) failIdx = 0;
      return guards.asMap().entries.map((entry) {
        final i = entry.key;
        final g = entry.value;
        if (i < failIdx) return GuardStep(guard: g, status: GuardStepStatus.satisfied);
        if (i == failIdx) {
          return GuardStep(guard: g, status: GuardStepStatus.failed, reason: failReasons[g.type]);
        }
        return GuardStep(guard: g, status: GuardStepStatus.pending);
      }).toList();
    }

    // progress
    return guards.asMap().entries.map((entry) {
      final i = entry.key;
      final g = entry.value;
      if (i < guards.length - 1) return GuardStep(guard: g, status: GuardStepStatus.satisfied);
      final needsInput = g.type == GuardType.secret || g.type == GuardType.storage;
      return GuardStep(
        guard: g,
        status: needsInput ? GuardStepStatus.prompting : GuardStepStatus.resolving,
      );
    }).toList();
  }
}
