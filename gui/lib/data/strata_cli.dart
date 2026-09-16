import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
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

const _guardStatusByName = {
  'satisfied': GuardReadiness.satisfied,
  'missing': GuardReadiness.missing,
  'unknown': GuardReadiness.unknown,
};

class ImportFailure {
  final String dottedName;
  final String error;

  const ImportFailure({required this.dottedName, required this.error});
}

/// One host from the snapshot's device inventory, before it is projected
/// into the two view-specific shapes the UI wants (the header's [DeviceInfo]
/// target list and the Machines screen's [MachineInfo] cards).
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

/// One guard's live readiness, from `GET /api/runbook-status`.
class GuardReadinessEntry {
  final GuardType type;
  final GuardReadiness status;

  const GuardReadinessEntry({required this.type, required this.status});
}

/// A runbook's live readiness: per-guard status plus install status, if known.
class RunbookStatus {
  final String dottedName;
  final List<GuardReadinessEntry> guards;
  final bool? installed;

  const RunbookStatus({required this.dottedName, required this.guards, required this.installed});
}

/// One run's live state, from `GET /api/run/<id>`.
class RunHandle {
  final String runId;
  final RunLifecycle status;
  final int? exitCode;
  final List<String> lines;

  const RunHandle({
    required this.runId,
    required this.status,
    required this.exitCode,
    required this.lines,
  });
}

class ApiException implements Exception {
  final int statusCode;
  final String message;

  const ApiException(this.statusCode, this.message);

  @override
  String toString() => message;
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

RunbookStatus _runbookStatusFromJson(Map<String, dynamic> json) {
  final guards = (json['guards'] as List).map((g) {
    final map = g as Map<String, dynamic>;
    return GuardReadinessEntry(
      type: _guardTypeByName[map['type']] ?? GuardType.requires,
      status: _guardStatusByName[map['status']] ?? GuardReadiness.unknown,
    );
  }).toList();
  return RunbookStatus(
    dottedName: json['dotted_name'] as String,
    guards: guards,
    installed: json['installed'] as bool?,
  );
}

RunHandle _runHandleFromJson(String runId, Map<String, dynamic> json) {
  const byName = {
    'running': RunLifecycle.running,
    'succeeded': RunLifecycle.succeeded,
    'failed': RunLifecycle.failed,
  };
  return RunHandle(
    runId: runId,
    status: byName[json['status']] ?? RunLifecycle.failed,
    exitCode: json['exit_code'] as int?,
    lines: (json['lines'] as List).cast<String>(),
  );
}

/// A client for one `strata gui` server's read snapshot and action API.
///
/// Both the web build (which fetches from the origin it was served from) and
/// the desktop build (which spawns its own `strata gui --no-browser`, see
/// [connectToStrata]) end up with one of these -- there is exactly one HTTP
/// code path for actions, not a shell-out-per-action desktop path and a
/// fetch-per-action web path.
class StrataApi {
  final Uri baseUrl;
  final String? token;

  const StrataApi({required this.baseUrl, this.token});

  Map<String, String> get _authHeader =>
      token == null ? const {} : {'Authorization': 'Bearer $token'};

  Uri _uri(String path) => baseUrl.resolve(path);

  Future<http.Response> _get(String path, [Map<String, String>? query]) {
    final uri = query == null ? _uri(path) : _uri(path).replace(queryParameters: query);
    return http.get(uri, headers: _authHeader);
  }

  Future<http.Response> _post(String path, Map<String, dynamic> body) {
    return http.post(
      _uri(path),
      headers: {..._authHeader, 'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
  }

  Future<http.Response> _delete(String path) {
    return http.Client().send(http.Request('DELETE', _uri(path))..headers.addAll(_authHeader)).then(
          http.Response.fromStream,
        );
  }

  Map<String, dynamic> _decodeOrThrow(http.Response response) {
    final body = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, (body['error'] as String?) ?? 'request failed');
    }
    return body;
  }

  Future<GuiData> fetchGuiData() async {
    final response = await _get('/api/gui-data');
    return _guiDataFromJson(_decodeOrThrow(response));
  }

  Future<RunbookStatus> fetchRunbookStatus(String dottedName, String? target) async {
    final response = await _get('/api/runbook-status', {
      'dotted_name': dottedName,
      'target': ?target,
    });
    return _runbookStatusFromJson(_decodeOrThrow(response));
  }

  Future<bool> getVaultStatus() async {
    final response = await _get('/api/vault-status');
    return _decodeOrThrow(response)['has_vault_password'] as bool;
  }

  Future<void> setVaultPassword(String value) async {
    _decodeOrThrow(await _post('/api/vault-password', {'value': value}));
  }

  Future<void> setSecret(String vaultKey, String value) async {
    _decodeOrThrow(await _post('/api/secrets', {'vault_key': vaultKey, 'value': value}));
  }

  Future<String> startRun(String dottedName, String? target, List<String>? tags) async {
    final body = _decodeOrThrow(await _post('/api/run', {
      'dotted_name': dottedName,
      'target': ?target,
      'tags': ?tags,
    }));
    return body['run_id'] as String;
  }

  Future<RunHandle> pollRun(String runId) async {
    final response = await _get('/api/run/$runId');
    return _runHandleFromJson(runId, _decodeOrThrow(response));
  }

  Future<void> addDevice({
    required String name,
    required String host,
    String user = 'root',
    String connection = 'ssh',
    int? port,
  }) async {
    _decodeOrThrow(await _post('/api/devices', {
      'name': name,
      'host': host,
      'user': user,
      'connection': connection,
      'port': ?port,
    }));
  }

  Future<void> removeDevice(String name) async {
    final response = await _delete('/api/devices/$name');
    _decodeOrThrow(response);
  }

  Future<bool> checkReachable(String host, {int port = 22}) async {
    final response = await _get('/api/reachable', {'host': host, 'port': '$port'});
    return _decodeOrThrow(response)['reachable'] as bool;
  }
}

Process? _desktopServer;

/// Connects to a `strata gui` server, spawning one for the desktop build.
///
/// Web has one for free -- the origin it was served from -- so this just
/// reads the access token embedded in the page's URL. Desktop has none, so
/// this spawns `strata gui --no-browser` (same repo-root search
/// [loadFromStrataCli] used to do) and parses the URL/token it announces on
/// stdout. Returns null if no server could be reached either way, so the
/// caller can fall back to sample data.
Future<StrataApi?> connectToStrata() async {
  if (kIsWeb) {
    final token = Uri.base.queryParameters['token'];
    return StrataApi(baseUrl: Uri.base, token: token);
  }

  final candidates = <Directory>[Directory.current, ..._ancestors(Directory.current)];
  for (final dir in candidates) {
    if (!await _looksLikeStrataRepo(dir)) continue;
    final api = await _spawnDesktopServer(dir);
    if (api != null) return api;
  }
  return null;
}

/// Stops the desktop-spawned server, if one was started. A no-op on web.
void disconnectFromStrata() {
  _desktopServer?.kill();
  _desktopServer = null;
}

Future<StrataApi?> _spawnDesktopServer(Directory dir) async {
  try {
    final process = await Process.start(
      'uv',
      ['run', 'strata', 'gui', '--no-browser', '--port', '0'],
      workingDirectory: dir.path,
    );
    String? url;
    String? token;
    final ready = Completer<void>();
    final sub = process.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      url ??= RegExp(r'on (http://\S+)').firstMatch(line)?.group(1);
      token ??= RegExp(r'Access token: (\S+)').firstMatch(line)?.group(1);
      if (url != null && token != null && !ready.isCompleted) ready.complete();
    });
    unawaited(process.stderr.drain());

    await ready.future.timeout(const Duration(seconds: 8));
    await sub.cancel();
    if (url == null || token == null) {
      process.kill();
      return null;
    }
    _desktopServer = process;
    return StrataApi(baseUrl: Uri.parse(url!), token: token);
  } catch (_) {
    return null;
  }
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
