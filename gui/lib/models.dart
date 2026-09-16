enum Screen { runbooks, apps, machines }

/// A guard's live readiness, as reported by `GET /api/runbook-status`.
enum GuardReadiness { satisfied, missing, unknown }

/// A started run's live status, as reported by `GET /api/run/<id>`.
enum RunLifecycle { running, succeeded, failed }

enum TestState { idle, testing, ok, failed }

enum CheckState { installed, notInstalled, unknown }

enum GuardType {
  prerequisite,
  secret,
  user,
  path,
  mount,
  storage,
  requires,
  controllerOnly,
}

enum RunbookCategory { development, infrastructure, packageManagers, services, system }

extension CategoryLabel on RunbookCategory {
  String get label => switch (this) {
        RunbookCategory.development => 'Development',
        RunbookCategory.infrastructure => 'Infrastructure',
        RunbookCategory.packageManagers => 'Package Managers',
        RunbookCategory.services => 'Services',
        RunbookCategory.system => 'System',
      };

  String get key => switch (this) {
        RunbookCategory.development => 'development',
        RunbookCategory.infrastructure => 'infrastructure',
        RunbookCategory.packageManagers => 'package_managers',
        RunbookCategory.services => 'services',
        RunbookCategory.system => 'system',
      };
}

class Guard {
  final GuardType type;
  final String label;

  const Guard({required this.type, required this.label});
}

class Runbook {
  final String dotted;
  final String leaf;
  final RunbookCategory category;
  final String alias;
  final String desc;
  final bool hasCheck;
  final CheckState checkState;
  final List<Guard> guards;
  final String? fakeOutput;

  const Runbook({
    required this.dotted,
    required this.leaf,
    required this.category,
    required this.alias,
    required this.desc,
    this.hasCheck = false,
    this.checkState = CheckState.notInstalled,
    this.guards = const [],
    this.fakeOutput,
  });
}

class DeviceInfo {
  final String id;
  final String name;
  final String sub;
  final bool isController;

  const DeviceInfo({
    required this.id,
    required this.name,
    required this.sub,
    required this.isController,
  });
}

enum MachineStatus { online, unreachable, unknown }

class MachineInfo {
  final String id;
  final String name;
  final String address;
  final bool isController;
  final bool removable;
  final MachineStatus status;
  final String applied;
  final String lastRun;

  const MachineInfo({
    required this.id,
    required this.name,
    required this.address,
    required this.isController,
    required this.removable,
    required this.status,
    required this.applied,
    required this.lastRun,
  });
}

class ServerApp {
  final String id;
  final String name;
  final String initial;
  final int? port;
  final String owner;
  final bool isInstalled;
  final bool canOpen;
  final String toggleLabel;
  final List<String> pathList;
  final String stateLabel;
  final bool hasMount;
  final bool mountWarning;
  final String? mountText;
  final int iconGradientStart;
  final int iconGradientEnd;
  final int iconTextColor;
  final String installDotted;

  const ServerApp({
    required this.id,
    required this.name,
    required this.initial,
    this.port,
    required this.owner,
    required this.isInstalled,
    required this.canOpen,
    required this.toggleLabel,
    this.pathList = const [],
    required this.stateLabel,
    this.hasMount = false,
    this.mountWarning = false,
    this.mountText,
    required this.iconGradientStart,
    required this.iconGradientEnd,
    required this.iconTextColor,
    required this.installDotted,
  });
}

/// One guard in the pre-run readiness checklist: a declared [Guard] paired
/// with its live [GuardReadiness] from `GET /api/runbook-status`.
class GuardStep {
  final Guard guard;
  final GuardReadiness status;

  const GuardStep({required this.guard, required this.status});

  /// Secret-like guards are the only ones a missing status can't self-heal
  /// during a run -- Path/Mount/SystemUser/UpstreamRunbook are provisioned
  /// automatically by guard_executor.execute(), but a Secret, Storage or
  /// Prerequisite needs a value from the operator before the run can start.
  bool get needsInputWhenMissing =>
      guard.type == GuardType.secret ||
      guard.type == GuardType.storage ||
      guard.type == GuardType.prerequisite;
}

class Readiness {
  final String key;
  final String text;
  final String title;
  final int color;
  final int background;

  const Readiness({
    required this.key,
    required this.text,
    required this.title,
    required this.color,
    required this.background,
  });
}
