import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/common.dart';

class MachinesScreen extends StatefulWidget {
  final AppState state;
  final bool isMobile;

  const MachinesScreen({super.key, required this.state, required this.isMobile});

  @override
  State<MachinesScreen> createState() => _MachinesScreenState();
}

class _MachinesScreenState extends State<MachinesScreen> {
  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final isMobile = widget.isMobile;

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 30, isMobile ? 18 : 26, isMobile ? 16 : 30, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.end,
            runSpacing: 12,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Machines', style: sans(size: 21, weight: FontWeight.w600, letterSpacing: -0.1)),
                  const SizedBox(height: 5),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 480),
                    child: Text(
                      'Hosts Strata can run runbooks against. Adding one only stores how to reach it.',
                      style: sans(size: 13.5, color: AppColors.textMuted),
                    ),
                  ),
                ],
              ),
              SizedBox(
                width: isMobile ? double.infinity : null,
                child: ElevatedButton(
                  onPressed: s.openAddMachine,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.surfaceAlt,
                    side: BorderSide(color: AppColors.cyan.withValues(alpha: 0.3)),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    minimumSize: Size(0, isMobile ? 44 : 38),
                  ),
                  child: Text('+ Add machine', style: sans(size: 13, weight: FontWeight.w600, color: AppColors.cyan)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          if (s.addMachineOpen) _AddMachineForm(state: s),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 820),
            child: Column(
              children: [
                for (final m in s.machines) _MachineCard(machine: m, state: s, isMobile: isMobile),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AddMachineForm extends StatefulWidget {
  final AppState state;

  const _AddMachineForm({required this.state});

  @override
  State<_AddMachineForm> createState() => _AddMachineFormState();
}

class _AddMachineFormState extends State<_AddMachineForm> {
  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final testOk = s.testState == TestState.ok;
    final testIdle = s.testState == TestState.idle;
    final testing = s.testState == TestState.testing;

    return Container(
      margin: const EdgeInsets.only(bottom: 18),
      constraints: const BoxConstraints(maxWidth: 560),
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 20),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.cyan.withValues(alpha: 0.22)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Add a machine', style: sans(size: 15, weight: FontWeight.w600)),
          const SizedBox(height: 3),
          Text(
            'Strata connects over SSH using your existing key. Nothing is installed until you run a runbook.',
            style: sans(size: 12.5, height: 1.5, color: AppColors.textMuted),
          ),
          const SizedBox(height: 18),
          _field('Name', 'e.g. NasBox'),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: _field('Address', '192.168.1.50 or host.local')),
              const SizedBox(width: 12),
              Expanded(child: _field('SSH user', 'diot')),
            ],
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
            decoration: BoxDecoration(
              color: AppColors.border(0.03),
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppColors.border(0.07)),
            ),
            child: Row(
              children: [
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: testIdle ? const Color(0xFF3A4150) : (testing ? AppColors.amber : AppColors.green),
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    testIdle ? 'Not tested yet' : (testing ? 'Connecting over SSH…' : 'Reachable — SSH key accepted'),
                    style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textSecondary),
                  ),
                ),
                if (testOk) Text('Ubuntu 24.04 · arm64', style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textDim)),
                if (testIdle) GhostButton(label: 'Test connection', onTap: s.testConnection),
              ],
            ),
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              ElevatedButton(
                onPressed: testOk ? s.closeAddMachine : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: testOk ? AppColors.cyan : const Color(0xFF2A3040),
                  disabledBackgroundColor: const Color(0xFF2A3040),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
                  padding: const EdgeInsets.symmetric(horizontal: 18),
                  minimumSize: const Size(0, 38),
                ),
                child: Text(
                  'Add machine',
                  style: sans(size: 13, weight: FontWeight.w600, color: testOk ? const Color(0xFF04222A) : AppColors.textDim),
                ),
              ),
              GhostButton(label: 'Cancel', onTap: s.closeAddMachine),
            ],
          ),
        ],
      ),
    );
  }

  Widget _field(String label, String hint) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: sans(size: 12, weight: FontWeight.w500, color: AppColors.textMuted)),
        const SizedBox(height: 6),
        TextField(
          style: sans(size: 13, weight: FontWeight.w500),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: sans(size: 13, weight: FontWeight.w500, color: AppColors.textDim),
            filled: true,
            fillColor: AppColors.bg,
            isDense: true,
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(9),
              borderSide: BorderSide(color: AppColors.border(0.1)),
            ),
          ),
        ),
      ],
    );
  }
}

class _MachineCard extends StatelessWidget {
  final MachineInfo machine;
  final AppState state;
  final bool isMobile;

  const _MachineCard({required this.machine, required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final m = machine;
    final isTarget = m.id == state.targetId;
    final confirming = state.confirmingId == m.id;
    final (statusDotColor, statusText, statusColor) = switch (m.status) {
      MachineStatus.online => (AppColors.green, 'Online', AppColors.greenText),
      MachineStatus.unreachable => (AppColors.amber, 'Not reachable right now', AppColors.amberText),
      MachineStatus.unknown => (AppColors.textDim, 'Not checked yet', AppColors.textMuted),
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: EdgeInsets.symmetric(horizontal: isMobile ? 16 : 20, vertical: isMobile ? 16 : 18),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: isTarget ? AppColors.cyan.withValues(alpha: 0.24) : AppColors.border(0.07)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 13,
            runSpacing: 8,
            children: [
              Container(
                width: 9,
                height: 9,
                decoration: BoxDecoration(shape: BoxShape.circle, color: statusDotColor),
              ),
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 9,
                children: [
                  Text(m.name, style: sans(size: 15, weight: FontWeight.w600)),
                  if (m.isController) _tag('controller', false),
                  if (isTarget) _tag('current target', true),
                ],
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(top: 3, left: 22),
            child: Text(m.address, style: mono(size: 12, color: AppColors.textMuted)),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (!isTarget) GhostButton(label: 'Use as target', onTap: () => state.selectTarget(m.id)),
              if (isTarget) GhostButton(label: 'Browse runbooks', onTap: state.selectScreenRunbooks),
              if (m.removable)
                OutlinedButton(
                  onPressed: () => state.askRemove(m.id),
                  style: OutlinedButton.styleFrom(
                    side: BorderSide(color: AppColors.pink.withValues(alpha: 0.28)),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    padding: const EdgeInsets.symmetric(horizontal: 13),
                    minimumSize: const Size(0, 34),
                  ),
                  child: Text('Drop', style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.pinkText)),
                ),
            ],
          ),
          Container(
            margin: const EdgeInsets.only(top: 14),
            padding: const EdgeInsets.only(top: 14),
            decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border(0.06)))),
            child: GridView.count(
              crossAxisCount: isMobile ? 2 : 3,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: isMobile ? 12 : 16,
              crossAxisSpacing: isMobile ? 16 : 16,
              childAspectRatio: 4,
              children: [
                _metaCell('Status', statusText, statusColor),
                _metaCell('Runbooks applied', m.applied, AppColors.textSecondary),
                _metaCell('Last run', m.lastRun, AppColors.textSecondary),
              ],
            ),
          ),
          if (confirming)
            Container(
              margin: const EdgeInsets.only(top: 14),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: BoxDecoration(
                color: AppColors.pink.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppColors.pink.withValues(alpha: 0.24)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Drop ${m.name} from Strata?', style: sans(size: 13, weight: FontWeight.w600, color: AppColors.pinkText)),
                  const SizedBox(height: 4),
                  Text(
                    'This forgets the connection details and run history. Nothing on the machine is uninstalled or deleted — you can add it back any time.',
                    style: sans(size: 12.5, height: 1.6, color: AppColors.textSecondary),
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 9,
                    runSpacing: 9,
                    children: [
                      DangerButton(label: 'Drop machine', onTap: () => state.confirmRemove(m.id)),
                      GhostButton(label: 'Keep it', onTap: state.cancelRemove),
                    ],
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _tag(String label, bool active) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: active ? AppColors.cyan.withValues(alpha: 0.12) : AppColors.border(0.05),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(label, style: sans(size: 11, weight: FontWeight.w500, color: active ? AppColors.cyanSoft : AppColors.textMuted)),
    );
  }

  Widget _metaCell(String label, String value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textDim)),
        const SizedBox(height: 3),
        Text(value, style: sans(size: 12.5, weight: FontWeight.w500, color: color), overflow: TextOverflow.ellipsis),
      ],
    );
  }
}
