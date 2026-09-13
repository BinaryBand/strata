import 'models.dart';

const List<Runbook> mockRunbooks = [
  Runbook(
    dotted: 'development.install_antigravity',
    leaf: 'install_antigravity',
    category: RunbookCategory.development,
    alias: 'install Antigravity',
    desc: 'Install Google Antigravity CLI via the local Homebrew tap.',
    hasCheck: true,
    checkState: CheckState.notInstalled,
    guards: [
      Guard(type: GuardType.controllerOnly, label: 'Controller only — desktop app'),
      Guard(type: GuardType.requires, label: 'Requires package_managers.install_homebrew'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.backup',
    leaf: 'backup',
    category: RunbookCategory.infrastructure,
    alias: 'back up app data',
    desc: 'Back up server app data to the Restic repository, tagged per app.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.install_restic'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.enable_rclone',
    leaf: 'enable_rclone',
    category: RunbookCategory.infrastructure,
    alias: 'enable rclone mounts',
    desc: 'Mount the configured rclone remotes under diot.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.user, label: 'System user: diot'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.enable_rclone_http',
    leaf: 'enable_rclone_http',
    category: RunbookCategory.infrastructure,
    alias: 'enable rclone HTTP serve',
    desc: 'Serve registered rclone paths over local HTTP via rclone serve http.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.enable_rclone'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.enable_tailscale',
    leaf: 'enable_tailscale',
    category: RunbookCategory.infrastructure,
    alias: 'join Tailscale network',
    desc: 'Join this host to the Tailscale tailnet for off-LAN reachability.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.secret, label: 'Vault secret: tailscale_auth_key'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.install_podman',
    leaf: 'install_podman',
    category: RunbookCategory.infrastructure,
    alias: 'install Podman',
    desc: 'Install Podman and the rootless container toolchain for diot.',
    hasCheck: true,
    checkState: CheckState.installed,
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.user, label: 'System user: diot'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.install_restic',
    leaf: 'install_restic',
    category: RunbookCategory.infrastructure,
    alias: 'install Restic',
    desc: 'Initialize a Restic repository for backing up server app data.',
    hasCheck: true,
    checkState: CheckState.installed,
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.install_podman'),
      Guard(type: GuardType.secret, label: 'Vault secret: restic_password'),
      Guard(type: GuardType.storage, label: 'Storage: restic_repository'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.restore',
    leaf: 'restore',
    category: RunbookCategory.infrastructure,
    alias: 'restore from backup',
    desc: "Restore the latest Restic snapshot per tag into each app's data dir.",
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.install_restic'),
    ],
  ),
  Runbook(
    dotted: 'infrastructure.sync_rclone_remote',
    leaf: 'sync_rclone_remote',
    category: RunbookCategory.infrastructure,
    alias: 'sync rclone credentials',
    desc: 'Copy registered rclone remote credentials onto a target host.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
    ],
  ),
  Runbook(
    dotted: 'package_managers.install_flatpak',
    leaf: 'install_flatpak',
    category: RunbookCategory.packageManagers,
    alias: 'install Flatpak',
    desc: 'Install Flatpak and add the Flathub remote.',
    hasCheck: true,
    checkState: CheckState.notInstalled,
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
    ],
  ),
  Runbook(
    dotted: 'package_managers.install_homebrew',
    leaf: 'install_homebrew',
    category: RunbookCategory.packageManagers,
    alias: 'install Homebrew',
    desc: 'Install Homebrew and core dev tools (node, pipx, uv, openjdk, rust).',
    hasCheck: true,
    checkState: CheckState.installed,
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
    ],
  ),
  Runbook(
    dotted: 'services.install_baikal',
    leaf: 'install_baikal',
    category: RunbookCategory.services,
    alias: 'install Baïkal',
    desc: 'Deploy Baikal CalDAV/CardDAV as a rootless Podman container owned by diot.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.install_podman'),
      Guard(type: GuardType.path, label: 'Path: /srv/baikal'),
      Guard(type: GuardType.path, label: 'Path: /srv/baikal/config'),
      Guard(type: GuardType.path, label: 'Path: /srv/baikal/Specific'),
    ],
  ),
  Runbook(
    dotted: 'services.install_from_git',
    leaf: 'install_from_git',
    category: RunbookCategory.services,
    alias: 'install git apps',
    desc: 'Install CLI apps from local git repos via pipx.',
    hasCheck: true,
    checkState: CheckState.installed,
  ),
  Runbook(
    dotted: 'services.install_jellyfin',
    leaf: 'install_jellyfin',
    category: RunbookCategory.services,
    alias: 'install Jellyfin',
    desc: 'Deploy Jellyfin as a rootless Podman container owned by diot.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
      Guard(type: GuardType.requires, label: 'Requires infrastructure.install_podman'),
      Guard(type: GuardType.path, label: 'Path: /srv/jellyfin/config'),
      Guard(type: GuardType.path, label: 'Path: /srv/jellyfin/cache'),
      Guard(type: GuardType.mount, label: 'Mount: pcloud:Media'),
    ],
    fakeOutput: 'PLAY [install Jellyfin] ***********************************\n'
        'TASK [Ensure config/cache dirs] ................ ok\n'
        'TASK [Render jellyfin.container Quadlet] ....... changed\n'
        'TASK [Reload diot systemd user units] .......... changed\n'
        'TASK [Start jellyfin.service] .................. changed\n\n'
        'PLAY RECAP *********************************************\n'
        'localhost : ok=5 changed=3 unreachable=0 failed=0',
  ),
  Runbook(
    dotted: 'system.enable_crash_recovery',
    leaf: 'enable_crash_recovery',
    category: RunbookCategory.system,
    alias: 'enable crash recovery',
    desc: 'Recover from kernel panics/freezes and keep crash evidence readable.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
    ],
  ),
  Runbook(
    dotted: 'system.enable_security_autoupdates',
    leaf: 'enable_security_autoupdates',
    category: RunbookCategory.system,
    alias: 'enable security autoupdates',
    desc: 'Enable automatic security updates via unattended-upgrades.',
    guards: [
      Guard(type: GuardType.prerequisite, label: 'Sudo password'),
    ],
  ),
];

const List<DeviceInfo> mockDevices = [
  DeviceInfo(id: 'local', name: 'This machine', sub: 'controller · local', isController: true),
  DeviceInfo(id: 'rpi4', name: 'Rpi4', sub: '192.168.1.42 · ssh', isController: false),
  DeviceInfo(id: 'nasbox', name: 'NasBox', sub: '192.168.1.50 · ssh', isController: false),
];

const List<MachineInfo> mockMachines = [
  MachineInfo(
    id: 'local',
    name: 'This machine',
    address: 'localhost · controller',
    isController: true,
    removable: false,
    status: MachineStatus.online,
    applied: '7 of 16',
    lastRun: '4 minutes ago',
  ),
  MachineInfo(
    id: 'rpi4',
    name: 'Rpi4',
    address: 'diot@192.168.1.42',
    isController: false,
    removable: true,
    status: MachineStatus.online,
    applied: '5 of 16',
    lastRun: 'Yesterday, 21:14',
  ),
  MachineInfo(
    id: 'nasbox',
    name: 'NasBox',
    address: 'diot@192.168.1.50',
    isController: false,
    removable: true,
    status: MachineStatus.unreachable,
    applied: '3 of 16',
    lastRun: '6 days ago',
  ),
];

final List<ServerApp> mockApps = [
  ServerApp(
    id: 'jellyfin',
    name: 'Jellyfin',
    initial: 'J',
    port: 8096,
    owner: 'diot:jellyfin',
    isInstalled: true,
    canOpen: true,
    toggleLabel: 'Restart',
    pathList: const ['/srv/jellyfin/config', '/srv/jellyfin/cache'],
    stateLabel: 'Running',
    hasMount: true,
    mountWarning: false,
    mountText: 'pcloud:Media live',
    iconGradientStart: 0xFFA78BFA,
    iconGradientEnd: 0xFF7C6CE0,
    iconTextColor: 0xFF1A1030,
    installDotted: 'services.install_jellyfin',
  ),
  ServerApp(
    id: 'baikal',
    name: 'Baikal',
    initial: 'B',
    port: 8080,
    owner: 'diot:baikal',
    isInstalled: true,
    canOpen: false,
    toggleLabel: 'Start',
    pathList: const ['/srv/baikal/config', '/srv/baikal/Specific'],
    stateLabel: 'Stopped',
    hasMount: false,
    iconGradientStart: 0xFF38BDF8,
    iconGradientEnd: 0xFF0EA5A5,
    iconTextColor: 0xFF04222A,
    installDotted: 'services.install_baikal',
  ),
];

const Map<GuardType, bool> knownGuards = {
  GuardType.prerequisite: true,
  GuardType.user: true,
  GuardType.storage: false,
  GuardType.secret: false,
  GuardType.mount: true,
  GuardType.path: true,
};

Readiness computeReadiness(Runbook r, bool targetIsController) {
  if (r.guards.any((g) => g.type == GuardType.controllerOnly) && !targetIsController) {
    return const Readiness(
      key: 'blocked',
      text: 'Blocked',
      title: 'Controller-only — switch target to This machine',
      color: 0xFFFDA4AF,
      background: 0x1FFB7185,
    );
  }
  final asks = r.guards.where((g) => knownGuards[g.type] == false).length;
  if (asks > 0) {
    return Readiness(
      key: 'asks',
      text: asks == 1 ? 'Asks 1 thing' : 'Asks $asks things',
      title: 'Will prompt you before running',
      color: 0xFFFCD34D,
      background: 0x1FFBBF24,
    );
  }
  return const Readiness(
    key: 'ready',
    text: 'Ready',
    title: 'Everything it needs is on hand',
    color: 0xFF6EE7B7,
    background: 0x1F34D399,
  );
}
