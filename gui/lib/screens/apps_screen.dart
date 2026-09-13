import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/common.dart';

class AppsScreen extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const AppsScreen({super.key, required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final s = state;
    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 30, isMobile ? 18 : 26, isMobile ? 16 : 30, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Server apps', style: sans(size: 21, weight: FontWeight.w600, letterSpacing: -0.1)),
          const SizedBox(height: 5),
          Padding(
            padding: const EdgeInsets.only(bottom: 20),
            child: Text('Containers running on ${s.activeDevice.name}.', style: sans(size: 13, color: AppColors.textMuted)),
          ),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final app in s.apps)
                SizedBox(
                  width: isMobile ? double.infinity : 340,
                  child: _AppCard(app: app, state: s),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AppCard extends StatelessWidget {
  final ServerApp app;
  final AppState state;

  const _AppCard({required this.app, required this.state});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 20),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border(0.07)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 34,
                    height: 34,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: [Color(app.iconGradientStart), Color(app.iconGradientEnd)],
                      ),
                    ),
                    child: Text(app.initial, style: sans(size: 14, weight: FontWeight.w700, color: Color(app.iconTextColor))),
                  ),
                  const SizedBox(width: 10),
                  Text(app.name, style: sans(size: 15, weight: FontWeight.w600)),
                ],
              ),
              _stateBadge(),
            ],
          ),
          if (app.isInstalled) ..._installedBody(context) else ..._notInstalledBody(context),
        ],
      ),
    );
  }

  Widget _stateBadge() {
    final running = app.stateLabel == 'Running';
    if (running) return StatusBadge.installed(true);
    return StatusBadge(
      text: app.stateLabel,
      color: const Color(0xFF94A3B8),
      background: const Color(0x24949494),
      borderColor: const Color(0x4D94A3B8),
    );
  }

  List<Widget> _installedBody(BuildContext context) {
    return [
      const SizedBox(height: 16),
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Port', style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textMuted)),
          Row(
            children: [
              Text('${app.port}', style: mono(size: 12.5, weight: FontWeight.w600, color: AppColors.textPrimary)),
              if (app.canOpen) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    border: Border.all(color: AppColors.cyan.withValues(alpha: 0.35)),
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: Text('Open ↗', style: sans(size: 11.5, weight: FontWeight.w600, color: AppColors.cyan)),
                ),
              ],
            ],
          ),
        ],
      ),
      const SizedBox(height: 9),
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Data', style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textMuted)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              for (final p in app.pathList) Text(p, style: mono(size: 11.5, weight: FontWeight.w500, color: AppColors.textSecondary)),
              Text(app.owner, style: sans(size: 11, color: AppColors.textDim)),
            ],
          ),
        ],
      ),
      if (app.hasMount) ...[
        const SizedBox(height: 9),
        Container(
          padding: const EdgeInsets.only(top: 9),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border(0.06)))),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Media mount', style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textMuted)),
              Row(
                children: [
                  Container(width: 7, height: 7, decoration: const BoxDecoration(shape: BoxShape.circle, color: AppColors.green)),
                  const SizedBox(width: 6),
                  Text(app.mountText ?? '', style: mono(size: 12, weight: FontWeight.w600, color: AppColors.greenText)),
                ],
              ),
            ],
          ),
        ),
        if (app.mountWarning)
          Container(
            margin: const EdgeInsets.only(top: 8),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AppColors.amber.withValues(alpha: 0.3)),
            ),
            child: Text(
              "Container is running but its read-only mount is down — restarts will fail until it's back.",
              style: sans(size: 11.5, height: 1.5, color: AppColors.amberText),
            ),
          ),
      ],
      Container(
        margin: const EdgeInsets.only(top: 10),
        padding: const EdgeInsets.only(top: 10),
        decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border(0.06)))),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            GhostButton(label: app.toggleLabel),
            GhostButton(label: 'Re-run install runbook', onTap: () => state.jumpTo(app.installDotted)),
          ],
        ),
      ),
    ];
  }

  List<Widget> _notInstalledBody(BuildContext context) {
    return [
      Padding(
        padding: const EdgeInsets.only(top: 16, bottom: 2),
        child: Column(
          children: [
            Text("Install runbook hasn't been run yet.", style: sans(size: 12.5, color: AppColors.textDim)),
            const SizedBox(height: 10),
            OutlinedButton(
              onPressed: () => state.jumpTo(app.installDotted),
              style: OutlinedButton.styleFrom(
                backgroundColor: AppColors.surfaceAlt,
                side: BorderSide(color: AppColors.cyan.withValues(alpha: 0.3)),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              ),
              child: Text('Install →', style: sans(size: 12.5, weight: FontWeight.w600, color: AppColors.cyan)),
            ),
          ],
        ),
      ),
    ];
  }
}
