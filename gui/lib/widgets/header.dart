import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';
import '../theme.dart';

class AppHeader extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const AppHeader({super.key, required this.state, required this.isMobile});

  String get _title => switch (state.screen) {
        Screen.runbooks => 'Runbooks',
        Screen.apps => 'Server apps',
        Screen.machines => 'Machines',
      };

  @override
  Widget build(BuildContext context) {
    return Container(
      height: isMobile ? 60 : 56,
      padding: EdgeInsets.symmetric(horizontal: isMobile ? 12 : 22),
      decoration: BoxDecoration(
        color: AppColors.headerBg,
        border: Border(bottom: BorderSide(color: AppColors.border(0.07))),
      ),
      child: Row(
        children: [
          if (isMobile) ...[
            _IconButton(icon: Icons.menu, onTap: state.toggleSidebar),
            const SizedBox(width: 10),
          ],
          Expanded(
            child: Text(
              _title,
              overflow: TextOverflow.ellipsis,
              style: sans(size: 14, weight: FontWeight.w500, color: AppColors.textSecondary),
            ),
          ),
          _TargetSwitcher(state: state, isMobile: isMobile),
        ],
      ),
    );
  }
}

class _IconButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;

  const _IconButton({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(9),
      child: Container(
        width: 44,
        height: 44,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          border: Border.all(color: AppColors.border(0.12)),
          borderRadius: BorderRadius.circular(9),
        ),
        child: Icon(icon, color: AppColors.textSecondary, size: 20),
      ),
    );
  }
}

class _TargetSwitcher extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const _TargetSwitcher({required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final active = state.activeDevice;
    final showSub = !isMobile && active.id != 'local';
    final sub = active.sub.split(' · ').first;

    return InkWell(
      onTap: state.toggleTargetMenu,
      borderRadius: BorderRadius.circular(isMobile ? 10 : 8),
      child: Container(
        height: isMobile ? 44 : 34,
        padding: EdgeInsets.symmetric(horizontal: isMobile ? 12 : 12),
        decoration: BoxDecoration(
          color: AppColors.surfaceAlt,
          border: Border.all(color: AppColors.border(0.1)),
          borderRadius: BorderRadius.circular(isMobile ? 10 : 8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: active.id == 'local' ? AppColors.cyan : AppColors.indigoStorage,
              ),
            ),
            const SizedBox(width: 8),
            Text(active.name, style: sans(size: 12.5, weight: FontWeight.w600)),
            if (showSub) ...[
              const SizedBox(width: 6),
              Text(sub, style: mono(size: 11, color: AppColors.textDim)),
            ],
            const SizedBox(width: 2),
            Text('▾', style: sans(size: 10, color: AppColors.textDim)),
          ],
        ),
      ),
    );
  }
}

/// Renders the target dropdown overlay; kept separate so [MainShell] can lay
/// it above everything via a [Stack] anchored to the header button.
class TargetMenuOverlay extends StatelessWidget {
  final AppState state;

  const TargetMenuOverlay({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    if (!state.targetOpen) return const SizedBox.shrink();
    return Positioned(
      top: 56,
      right: 16,
      width: 240,
      child: GestureDetector(
        onTap: () {},
        child: Material(
          color: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(9),
          elevation: 12,
          child: Container(
            decoration: BoxDecoration(
              border: Border.all(color: AppColors.border(0.1)),
              borderRadius: BorderRadius.circular(9),
            ),
            padding: const EdgeInsets.all(6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(10, 6, 10, 8),
                  child: Text('Run against', style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textMuted)),
                ),
                ...state.devices.map((d) {
                  final active = d.id == state.targetId;
                  return InkWell(
                    onTap: () => state.selectTarget(d.id),
                    borderRadius: BorderRadius.circular(6),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 8),
                      decoration: BoxDecoration(
                        color: active ? AppColors.border(0.05) : Colors.transparent,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 7,
                            height: 7,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: d.id == 'local' ? AppColors.cyan : AppColors.indigoStorage,
                            ),
                          ),
                          const SizedBox(width: 9),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(d.name, style: sans(size: 12.5, weight: FontWeight.w600)),
                                Text(d.sub, style: mono(size: 10.5, color: AppColors.textDim)),
                              ],
                            ),
                          ),
                          if (active) Text('✓', style: sans(size: 13, color: AppColors.cyan)),
                        ],
                      ),
                    ),
                  );
                }),
                Container(
                  margin: const EdgeInsets.only(top: 4),
                  padding: const EdgeInsets.only(top: 5),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: AppColors.border(0.07))),
                  ),
                  child: InkWell(
                    onTap: state.selectScreenMachines,
                    borderRadius: BorderRadius.circular(7),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
                      child: Text('Manage machines…', style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textMuted)),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
