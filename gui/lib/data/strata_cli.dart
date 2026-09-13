import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../models.dart';

const _guardTypeByName = {
  'Prerequisite': GuardType.prerequisite,
  'Secret': GuardType.secret,
  'SystemUser': GuardType.user,
  'LocalPath': GuardType.path,
  'Mount': GuardType.mount,
  'Storage': GuardType.storage,
  'UpstreamRunbook': GuardType.requires,
  'ControllerOnly': GuardType.controllerOnly,
};

const _categoryByKey = {
  'development': RunbookCategory.development,
  'infrastructure': RunbookCategory.infrastructure,
  'package_managers': RunbookCategory.packageManagers,
  'services': RunbookCategory.services,
  'system': RunbookCategory.system,
};

class ImportFailure {
  final String dottedName;
  final String error;

  const ImportFailure({required this.dottedName, required this.error});
}

/// One host from `strata dev gui-data`'s device inventory, before it is
/// projected into the two view-specific shapes the UI wants (the header's
/// [DeviceInfo] target list and the Machines screen's [MachineInfo] cards).
class LoadedDevice {
  final String name;
  final String host;
  final String user;
  final String connection;
  final int? port;
  final bool isController;

  const LoadedDevice({
    required this.name,
    required this.host,
    required this.user,
    required this.connection,
    required this.port,
    required this.isController,
  });

  DeviceInfo toDeviceInfo() => DeviceInfo(
        id: name,
        name: isController ? 'This machine' : name,
        sub: isController ? 'controller · local' : '$host · $connection',
        isController: isController,
      );

  MachineInfo toMachineInfo() => MachineInfo(
        id: name,
        name: isController ? 'This machine' : name,
        address: isController ? 'localhost · controller' : '$user@$host',
        isController: isController,
        removable: !isController,
        status: MachineStatus.unknown,
        applied: '—',
        lastRun: '—',
      );
}

class GuiData {
  final List<Runbook> runbooks;
  final List<LoadedDevice> devices;
  final List<ImportFailure> importFailures;

  const GuiData({required this.runbooks, required this.devices, required this.importFailures});
}

class GuiDataLoadFailure implements Exception {
  final String message;

  const GuiDataLoadFailure(this.message);

  @override
  String toString() => message;
}

Runbook _runbookFromJson(Map<String, dynamic> json) {
  final guards = (json['guards'] as List).map((g) {
    final map = g as Map<String, dynamic>;
    return Guard(
      type: _guardTypeByName[map['type']] ?? GuardType.requires,
      label: map['label'] as String,
    );
  }).toList();

  return Runbook(
    dotted: json['dotted_name'] as String,
    leaf: json['leaf'] as String,
    category: _categoryByKey[json['category']] ?? RunbookCategory.system,
    alias: (json['alias'] as String?) ?? (json['leaf'] as String),
    desc: json['description'] as String,
    hasCheck: json['has_check'] as bool,
    checkState: (json['has_check'] as bool) ? CheckState.unknown : CheckState.notInstalled,
    guards: guards,
  );
}

LoadedDevice _deviceFromJson(Map<String, dynamic> json) {
  return LoadedDevice(
    name: json['name'] as String,
    host: json['host'] as String,
    user: json['user'] as String,
    connection: json['connection'] as String,
    port: json['port'] as int?,
    isController: json['is_controller'] as bool,
  );
}

GuiData _guiDataFromJson(Map<String, dynamic> json) {
  final runbooks = (json['runbooks'] as List)
      .map((r) => _runbookFromJson(r as Map<String, dynamic>))
      .toList();
  final devices =
      (json['devices'] as List).map((d) => _deviceFromJson(d as Map<String, dynamic>)).toList();
  final importFailures = (json['import_failures'] as List)
      .map((f) => ImportFailure(
            dottedName: (f as Map<String, dynamic>)['dotted_name'] as String,
            error: f['error'] as String,
          ))
      .toList();
  return GuiData(runbooks: runbooks, devices: devices, importFailures: importFailures);
}

/// Runs `strata dev gui-data` and parses its JSON into GUI model types.
///
/// Read-only: this shells out to a hidden CLI command that only reads the
/// runbook catalog and device inventory, never runs anything. Tries the
/// current directory first (the common case: launched from `gui/` inside the
/// strata repo, where `uv run` walks up to find the project), then walks
/// upward looking for the repo root so a build launched from elsewhere still
/// finds it.
///
/// Desktop only: needs `dart:io`'s `Process`, which the web build does not
/// have. Use [loadFromHttpApi] there instead.
Future<GuiData> loadFromStrataCli() async {
  final candidates = <Directory>[Directory.current, ..._ancestors(Directory.current)];
  Object? lastError;

  for (final dir in candidates) {
    if (!await _looksLikeStrataRepo(dir)) continue;
    try {
      final result = await Process.run(
        'uv',
        ['run', 'strata', 'dev', 'gui-data'],
        workingDirectory: dir.path,
      );
      if (result.exitCode != 0) {
        lastError = GuiDataLoadFailure('strata dev gui-data exited ${result.exitCode}: ${result.stderr}');
        continue;
      }
      return _guiDataFromJson(jsonDecode(result.stdout as String) as Map<String, dynamic>);
    } catch (e) {
      lastError = e;
    }
  }

  throw GuiDataLoadFailure('Could not run strata dev gui-data: ${lastError ?? 'not found'}');
}

/// Fetches the same snapshot from `GET /api/gui-data` on the current origin.
///
/// This is the web build's counterpart to [loadFromStrataCli]: a browser
/// can't spawn `strata`, so instead this hits the endpoint that
/// `strata dev gui-serve` serves alongside the built app itself -- same
/// JSON, same [_guiDataFromJson] parsing, just fetched instead of shelled
/// out to. Relative so it keeps working under whatever host name reaches the
/// server (localhost, a tailnet IP, or a MagicDNS name).
Future<GuiData> loadFromHttpApi() async {
  final uri = Uri.base.resolve('/api/gui-data');
  http.Response response;
  try {
    response = await http.get(uri);
  } catch (e) {
    throw GuiDataLoadFailure('Could not reach $uri: $e');
  }
  if (response.statusCode != 200) {
    throw GuiDataLoadFailure('$uri returned ${response.statusCode}');
  }
  return _guiDataFromJson(jsonDecode(response.body) as Map<String, dynamic>);
}

Iterable<Directory> _ancestors(Directory start) sync* {
  var dir = start.parent;
  for (var i = 0; i < 5 && dir.path != dir.parent.path; i++) {
    yield dir;
    dir = dir.parent;
  }
}

Future<bool> _looksLikeStrataRepo(Directory dir) async {
  return File('${dir.path}/pyproject.toml').exists().then((exists) async {
    if (!exists) return false;
    final contents = await File('${dir.path}/pyproject.toml').readAsString();
    return contents.contains('name = "strata"');
  }).catchError((_) => false);
}
