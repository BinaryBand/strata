import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_state.dart';
import '../mock_data.dart';
import '../models.dart';
import '../theme.dart';
import '../widgets/common.dart';

class RunbooksScreen extends StatefulWidget {
  final AppState state;
  final bool isMobile;

  const RunbooksScreen({super.key, required this.state, required this.isMobile});

  @override
  State<RunbooksScreen> createState() => _RunbooksScreenState();
}

class _RunbooksScreenState extends State<RunbooksScreen> {
  final _searchFocus = FocusNode();
  late final TextEditingController _searchController;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(text: widget.state.query);
  }

  @override
  void dispose() {
    _searchFocus.dispose();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final isMobile = widget.isMobile;
    final showList = !isMobile || !s.mobileShowDetail;
    final showDetail = !isMobile || s.mobileShowDetail;

    if (isMobile) {
      return showDetail ? _buildDetailPane(context) : _buildListPane(context);
    }

    return Row(
      children: [
        if (showList)
          Expanded(
            flex: 58,
            child: Container(
              constraints: const BoxConstraints(minWidth: 340),
              decoration: BoxDecoration(border: Border(right: BorderSide(color: AppColors.border(0.07)))),
              child: _buildListPane(context),
            ),
          ),
        if (showDetail)
          Expanded(
            flex: 42,
            child: Container(
              constraints: const BoxConstraints(minWidth: 340),
              color: const Color(0xFF0D1017),
              child: _buildDetailPane(context),
            ),
          ),
      ],
    );
  }

  Widget _buildListPane(BuildContext context) {
    final s = widget.state;
    final isMobile = widget.isMobile;
    final filtered = s.filteredRunbooks;
    final grouped = s.groupedSections;
    final hasQuery = s.query.trim().isNotEmpty;
    final hasCategory = s.selectedCategory != null;

    return Column(
      children: [
        Container(
          padding: EdgeInsets.fromLTRB(isMobile ? 16 : 22, isMobile ? 14 : 16, isMobile ? 16 : 22, 12),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border(0.06)))),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Runbooks', style: sans(size: 20, weight: FontWeight.w600, letterSpacing: -0.1)),
                  Text('${filtered.length} of ${s.runbooks.length}', style: sans(size: 12, weight: FontWeight.w500, color: AppColors.textDim)),
                ],
              ),
              const SizedBox(height: 10),
              Stack(
                alignment: Alignment.centerRight,
                children: [
                  Shortcuts(
                    shortcuts: {
                      LogicalKeySet(LogicalKeyboardKey.escape): const _ClearIntent(),
                      LogicalKeySet(LogicalKeyboardKey.enter): const _SubmitIntent(),
                    },
                    child: Actions(
                      actions: {
                        _ClearIntent: CallbackAction<_ClearIntent>(onInvoke: (_) {
                          s.clearQuery();
                          _searchController.text = '';
                          _searchFocus.unfocus();
                          return null;
                        }),
                        _SubmitIntent: CallbackAction<_SubmitIntent>(onInvoke: (_) {
                          final first = s.firstMatchDotted;
                          if (first != null) s.selectRunbook(first);
                          return null;
                        }),
                      },
                      child: TextField(
                        focusNode: _searchFocus,
                        controller: _searchController,
                        onChanged: s.setQuery,
                        style: sans(size: isMobile ? 15 : 13, weight: FontWeight.w500),
                        decoration: InputDecoration(
                          hintText: 'Search runbooks…  ( / to focus )',
                          hintStyle: sans(size: isMobile ? 15 : 13, weight: FontWeight.w500, color: AppColors.textDim),
                          filled: true,
                          fillColor: AppColors.bg,
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: isMobile ? 14 : 12, vertical: isMobile ? 14 : 10),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(isMobile ? 10 : 7),
                            borderSide: BorderSide(color: AppColors.border(0.09)),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(isMobile ? 10 : 7),
                            borderSide: BorderSide(color: AppColors.border(0.09)),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(isMobile ? 10 : 7),
                            borderSide: BorderSide(color: AppColors.border(0.09)),
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (hasQuery)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: InkWell(
                        onTap: () {
                          s.clearQuery();
                          _searchController.text = '';
                        },
                        borderRadius: BorderRadius.circular(6),
                        child: Container(
                          width: 28,
                          height: 28,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(color: AppColors.border(0.06), borderRadius: BorderRadius.circular(6)),
                          child: Text('✕', style: sans(size: 13, color: AppColors.textMuted)),
                        ),
                      ),
                    ),
                ],
              ),
              if (isMobile) ...[
                const SizedBox(height: 4),
                SizedBox(
                  height: 34,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      _CategoryChip(label: 'All', count: null, active: s.selectedCategory == null, onTap: s.selectAllCategories),
                      ...RunbookCategory.values.map((cat) {
                        final count = s.runbooks.where((r) => r.category == cat).length;
                        return _CategoryChip(
                          label: cat.label,
                          count: count,
                          active: s.selectedCategory == cat,
                          onTap: () => s.selectCategory(cat),
                        );
                      }),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
        Expanded(
          child: filtered.isEmpty
              ? _buildNoResults(context, hasQuery, hasCategory)
              : ListView(
                  padding: const EdgeInsets.fromLTRB(10, 6, 10, 20),
                  children: [
                    for (final cat in RunbookCategory.values)
                      if (grouped[cat] != null) _buildSection(context, cat, grouped[cat]!),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _buildNoResults(BuildContext context, bool hasQuery, bool hasCategory) {
    final s = widget.state;
    final text = hasQuery
        ? 'No runbooks match "${s.query}"${hasCategory ? ' in ${s.selectedCategory!.label}' : ''}.'
        : 'No runbooks in this category.';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 20),
      child: Column(
        children: [
          Text(text, textAlign: TextAlign.center, style: sans(size: 13, color: AppColors.textDim)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            alignment: WrapAlignment.center,
            children: [
              if (hasQuery) GhostButton(label: 'Clear search', onTap: () { s.clearQuery(); _searchController.text = ''; }),
              if (hasCategory) GhostButton(label: 'Show all categories', onTap: s.selectAllCategories),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSection(BuildContext context, RunbookCategory cat, List<Runbook> items) {
    final s = widget.state;
    final isMobile = widget.isMobile;
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 5),
            child: Text(cat.label, style: sans(size: 12, weight: FontWeight.w600, color: AppColors.textMuted)),
          ),
          for (final rb in items) _buildRunbookRow(context, rb, s, isMobile),
        ],
      ),
    );
  }

  Widget _buildRunbookRow(BuildContext context, Runbook rb, AppState s, bool isMobile) {
    final active = rb.dotted == s.selectedDotted;
    final readiness = computeReadiness(rb, s.targetIsController);
    return InkWell(
      onTap: () => s.selectRunbook(rb.dotted),
      borderRadius: BorderRadius.circular(isMobile ? 10 : 8),
      child: Container(
        margin: EdgeInsets.only(bottom: isMobile ? 6 : 2),
        padding: EdgeInsets.symmetric(horizontal: isMobile ? 14 : 12, vertical: isMobile ? 13 : 10),
        constraints: BoxConstraints(minHeight: isMobile ? 58 : 0),
        decoration: BoxDecoration(
          color: active ? AppColors.cyan.withValues(alpha: 0.08) : Colors.transparent,
          borderRadius: BorderRadius.circular(isMobile ? 10 : 8),
          border: Border.all(color: active ? AppColors.cyan.withValues(alpha: 0.28) : Colors.transparent),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 9,
                    children: [
                      Text(rb.alias, style: sans(size: 14, weight: FontWeight.w500)),
                      Text(rb.leaf, style: mono(size: 11)),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    rb.desc,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: sans(size: 12, color: AppColors.textMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 6),
            if (rb.checkState != CheckState.unknown) StatusBadge.installed(rb.checkState == CheckState.installed),
            const SizedBox(width: 6),
            Tooltip(
              message: readiness.title,
              child: Pill(text: readiness.text, color: Color(readiness.color), background: Color(readiness.background)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDetailPane(BuildContext context) {
    final s = widget.state;
    return s.runView ? _RunFlowView(state: s, isMobile: widget.isMobile) : _DetailView(state: s, isMobile: widget.isMobile);
  }
}

class _ClearIntent extends Intent {
  const _ClearIntent();
}

class _SubmitIntent extends Intent {
  const _SubmitIntent();
}

class _CategoryChip extends StatelessWidget {
  final String label;
  final int? count;
  final bool active;
  final VoidCallback onTap;

  const _CategoryChip({required this.label, required this.count, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 7),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(17),
        child: Container(
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 13),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: active ? AppColors.cyan.withValues(alpha: 0.14) : AppColors.inputBg,
            borderRadius: BorderRadius.circular(17),
            border: Border.all(color: active ? AppColors.cyan.withValues(alpha: 0.4) : AppColors.border(0.08)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(label, style: sans(size: 12.5, weight: FontWeight.w600, color: active ? AppColors.textPrimary : AppColors.textMuted)),
              if (count != null) ...[
                const SizedBox(width: 6),
                Text('$count', style: mono(size: 10.5, color: AppColors.textDim)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailView extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const _DetailView({required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final s = state;
    final rb = s.selectedRunbook;
    final readiness = computeReadiness(rb, s.targetIsController);
    final blocked = s.selectedBlockedByTarget;

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 26, isMobile ? 16 : 24, isMobile ? 16 : 26, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (isMobile)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  TextButton(
                    onPressed: s.backToListMobile,
                    style: TextButton.styleFrom(padding: EdgeInsets.zero),
                    child: Text('‹ Runbooks', style: sans(size: 13, weight: FontWeight.w600, color: AppColors.cyan)),
                  ),
                  const Spacer(),
                  Text(rb.leaf, style: mono(size: 11)),
                ],
              ),
            ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(rb.alias, style: sans(size: 21, weight: FontWeight.w600, letterSpacing: -0.1)),
                    const SizedBox(height: 3),
                    Text(rb.dotted, style: mono(size: 12)),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(color: AppColors.border(0.05), borderRadius: BorderRadius.circular(5)),
                child: Text(rb.category.label, style: mono(size: 10.5, weight: FontWeight.w600, color: AppColors.textMuted)),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Text(rb.desc, style: sans(size: 13.5, height: 1.6, color: AppColors.textSecondary)),
          ),
          if (rb.hasCheck && rb.checkState != CheckState.unknown)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Row(
                children: [
                  StatusBadge.installed(rb.checkState == CheckState.installed),
                  const SizedBox(width: 8),
                  Text('Strata can check this without running it', style: sans(size: 11.5, color: AppColors.textDim)),
                ],
              ),
            ),
          if (rb.hasCheck && rb.checkState == CheckState.unknown)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(
                'Strata can check this without running it — live status isn\'t loaded here.',
                style: sans(size: 11.5, color: AppColors.textDim),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 24),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Before it runs', style: sans(size: 12.5, weight: FontWeight.w600, color: AppColors.textMuted)),
                Text(readiness.text, style: sans(size: 11.5, weight: FontWeight.w600, color: Color(readiness.color))),
              ],
            ),
          ),
          const SizedBox(height: 12),
          if (rb.guards.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text('Nothing needed — this runs straight away.', style: sans(size: 12.5, color: AppColors.textDim)),
            )
          else
            Column(
              children: [
                for (final g in rb.guards) _buildGuardChip(context, g, s),
              ],
            ),
          if (blocked)
            Container(
              margin: const EdgeInsets.only(top: 20),
              padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
              decoration: BoxDecoration(
                color: AppColors.pink.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.pink.withValues(alpha: 0.3)),
              ),
              child: Text(
                '⚠ Controller-only runbook — switch the target to "This machine" to run it.',
                style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.pinkText),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 26),
            child: Container(
              padding: const EdgeInsets.only(top: 18),
              decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border(0.07)))),
              child: isMobile
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        PrimaryButton(label: 'Run on ${s.activeDevice.name}', onTap: blocked ? null : s.startRun, expand: true),
                        const SizedBox(height: 7),
                        Text(_runHint(readiness), textAlign: TextAlign.center, style: sans(size: 11.5, color: AppColors.textDim)),
                      ],
                    )
                  : Row(
                      children: [
                        PrimaryButton(label: 'Run on ${s.activeDevice.name}', onTap: blocked ? null : s.startRun),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(_runHint(readiness), style: sans(size: 11.5, color: AppColors.textDim)),
                        ),
                      ],
                    ),
            ),
          ),
        ],
      ),
    );
  }

  String _runHint(Readiness r) {
    if (r.key == 'ready') return 'Everything it needs is on hand — no prompts expected.';
    if (r.key == 'asks') return 'You’ll be asked for what’s missing before anything changes.';
    return 'Switch the target to run this.';
  }

  Widget _buildGuardChip(BuildContext context, Guard g, AppState s) {
    final meta = guardMeta[g.type]!;
    final hint = guardHint[g.type]!;
    final known = knownGuards[g.type];
    final blocked = g.type == GuardType.controllerOnly && s.targetId != 'local';
    final asks = known == false;
    final isReq = g.type == GuardType.requires;

    final stateText = blocked ? 'Blocked' : (asks ? 'Will ask' : 'OK');
    final stateColor = blocked ? AppColors.pinkText : (asks ? AppColors.amberText : AppColors.greenText);
    final stateBg = blocked ? AppColors.pink.withValues(alpha: 0.12) : (asks ? AppColors.amber.withValues(alpha: 0.12) : AppColors.green.withValues(alpha: 0.12));

    return Container(
      margin: const EdgeInsets.only(bottom: 7),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.border(0.03),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppColors.border(0.07)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(shape: BoxShape.circle, color: meta.color.withValues(alpha: 0.85)),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(g.label, style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textSecondary)),
                const SizedBox(height: 2),
                Text(hint, style: sans(size: 11.5, color: AppColors.textDim)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Pill(text: stateText, color: stateColor, background: stateBg),
          if (isReq)
            TextButton(
              onPressed: () => s.jumpTo(g.label.replaceFirst('Requires ', '')),
              style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4)),
              child: Text('Open →', style: sans(size: 12, weight: FontWeight.w600, color: AppColors.cyan)),
            ),
        ],
      ),
    );
  }
}

class _RunFlowView extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const _RunFlowView({required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final s = state;
    final rb = s.selectedRunbook;
    final steps = s.buildRunSteps(rb, s.runScenario);
    final outputRevealed = s.runScenario == RunScenario.complete;
    final doneSteps = steps.where((x) => x.status == GuardStepStatus.satisfied).length;
    final pct = outputRevealed ? 100 : (steps.isNotEmpty ? ((doneSteps / (steps.length + 1)) * 100).round() : 50);

    final runTitle = switch (s.runScenario) {
      RunScenario.complete => 'Finished ${rb.alias}',
      RunScenario.failed => 'Could not run ${rb.alias}',
      RunScenario.progress => 'Running ${rb.alias}',
    };
    final (statusText, statusColor, statusBg) = switch (s.runScenario) {
      RunScenario.complete => ('Completed', AppColors.greenText, AppColors.green.withValues(alpha: 0.12)),
      RunScenario.failed => ('Stopped — a check failed', AppColors.redText, AppColors.red.withValues(alpha: 0.12)),
      RunScenario.progress => (
          'Step ${(doneSteps + 1).clamp(0, steps.isEmpty ? 1 : steps.length)} of ${steps.isEmpty ? 1 : steps.length}',
          AppColors.cyanSoft,
          AppColors.cyan.withValues(alpha: 0.12),
        ),
    };
    final progressColor = switch (s.runScenario) {
      RunScenario.failed => AppColors.red,
      RunScenario.complete => AppColors.green,
      RunScenario.progress => AppColors.cyan,
    };

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 26, isMobile ? 14 : 22, isMobile ? 16 : 26, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          isMobile
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _backButton(),
                    const SizedBox(height: 10),
                    _scenarioGroup(),
                  ],
                )
              : Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    _backButton(),
                    Row(
                      children: [
                        Text('Preview state', style: sans(size: 11, color: const Color(0xFF3A4150))),
                        const SizedBox(width: 8),
                        _scenarioGroup(),
                      ],
                    ),
                  ],
                ),
          const SizedBox(height: 16),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(runTitle, style: sans(size: 18, weight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text('${rb.dotted} → ${s.activeDevice.name}', style: mono(size: 12)),
                  ],
                ),
              ),
              Pill(text: statusText, color: statusColor, background: statusBg),
            ],
          ),
          const SizedBox(height: 14),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: Container(
              height: 4,
              color: const Color(0xFF1A1F2A),
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: pct / 100,
                child: Container(color: progressColor),
              ),
            ),
          ),
          const SizedBox(height: 20),
          for (var i = 0; i < steps.length; i++) _buildStep(context, steps[i], i, steps.length),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            constraints: const BoxConstraints(minHeight: 70),
            decoration: BoxDecoration(
              color: AppColors.bg,
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppColors.border(0.07)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('Output', style: sans(size: 12.5, weight: FontWeight.w600, color: AppColors.textMuted)),
                    if (!outputRevealed) ...[
                      const SizedBox(width: 8),
                      Text('shown once everything above is ready', style: sans(size: 11, color: AppColors.textDim)),
                    ],
                  ],
                ),
                const SizedBox(height: 8),
                if (!outputRevealed)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    child: Text('Waiting on the checks above…', style: sans(size: 12.5, color: const Color(0xFF4A5160))),
                  )
                else
                  Text(
                    rb.fakeOutput ??
                        'PLAY [${rb.alias}] ***\nTASK [Run] ... ok\n\nPLAY RECAP\nlocalhost : ok=1 changed=1 unreachable=0 failed=0',
                    style: mono(size: 12, weight: FontWeight.w400, color: const Color(0xFF8EE6B8)),
                  ),
              ],
            ),
          ),
          if (outputRevealed)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Wrap(
                spacing: 9,
                runSpacing: 9,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  PrimaryButton(label: 'Done', onTap: s.finishRun),
                  if (rb.category == RunbookCategory.services)
                    GhostButton(label: 'View in Server apps', onTap: s.selectScreenApps),
                  GhostButton(label: 'Run again', onTap: () => s.setScenario(RunScenario.progress)),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _backButton() {
    return TextButton(
      onPressed: state.backToDetail,
      style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
      child: Text(
        '‹ Back',
        style: sans(size: isMobile ? 13 : 12, weight: isMobile ? FontWeight.w600 : FontWeight.w500, color: isMobile ? AppColors.cyan : AppColors.textDim),
      ),
    );
  }

  Widget _scenarioGroup() {
    Widget btn(String label, RunScenario value) {
      final active = state.runScenario == value;
      return Expanded(
        child: InkWell(
          onTap: () => state.setScenario(value),
          borderRadius: BorderRadius.circular(isMobile ? 7 : 5),
          child: Container(
            height: isMobile ? 38 : 28,
            alignment: Alignment.center,
            padding: EdgeInsets.symmetric(horizontal: isMobile ? 6 : 10),
            decoration: BoxDecoration(
              color: active ? AppColors.cyan : Colors.transparent,
              borderRadius: BorderRadius.circular(isMobile ? 7 : 5),
            ),
            child: Text(
              label,
              style: sans(size: isMobile ? 12 : 11.5, weight: FontWeight.w600, color: active ? const Color(0xFF04222A) : AppColors.textMuted),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.inputBg,
        border: Border.all(color: AppColors.border(0.08)),
        borderRadius: BorderRadius.circular(isMobile ? 9 : 7),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          btn('In progress', RunScenario.progress),
          const SizedBox(width: 4),
          btn('Guard failed', RunScenario.failed),
          const SizedBox(width: 4),
          btn('Complete', RunScenario.complete),
        ],
      ),
    );
  }

  Widget _buildStep(BuildContext context, GuardStep step, int index, int total) {
    final meta = guardMeta[step.guard.type]!;
    final s = state;
    final (glyph, wrapColor, statusText, labelColor) = switch (step.status) {
      GuardStepStatus.satisfied => ('✓', AppColors.green, 'Satisfied', AppColors.textPrimary),
      GuardStepStatus.pending => ('·', const Color(0xFF2A3040), 'Pending', AppColors.textDim),
      GuardStepStatus.resolving => ('', AppColors.cyan, 'Checking…', AppColors.textPrimary),
      GuardStepStatus.prompting => ('!', AppColors.amber, 'Needs input', AppColors.textPrimary),
      GuardStepStatus.failed => ('✕', AppColors.red, 'Failed', AppColors.textPrimary),
    };
    final isSpinner = step.status == GuardStepStatus.resolving;
    final showConnector = index < total - 1;
    final anyUnsatisfiedBefore = index == 0;
    final connectorColor = anyUnsatisfiedBefore && step.status == GuardStepStatus.satisfied ? AppColors.green : const Color(0xFF262C38);

    return Padding(
      padding: EdgeInsets.only(bottom: 0),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Column(
              children: [
                Container(
                  width: 22,
                  height: 22,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: isSpinner ? Colors.transparent : wrapColor,
                    border: isSpinner ? Border.all(color: Colors.white.withValues(alpha: 0.3), width: 2) : null,
                  ),
                  child: isSpinner
                      ? const SizedBox(
                          width: 12,
                          height: 12,
                          child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.cyan),
                        )
                      : Text(glyph, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: step.status == GuardStepStatus.pending ? AppColors.textDim : AppColors.bg)),
                ),
                if (showConnector) Expanded(child: Container(width: 2, color: connectorColor, margin: const EdgeInsets.symmetric(vertical: 2))),
              ],
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(meta.abbr, style: mono(size: 10.5, weight: FontWeight.w600, color: meta.color.withValues(alpha: 0.9), letterSpacing: 0.4)),
                        const SizedBox(width: 8),
                        Text(step.guard.label, style: sans(size: 13, weight: FontWeight.w600, color: labelColor)),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(statusText, style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textDim)),
                    if (step.status == GuardStepStatus.prompting) _promptInput(step),
                    if (step.status == GuardStepStatus.failed) _failureBox(step, s),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _promptInput(GuardStep step) {
    final placeholder = step.guard.type == GuardType.secret ? 'Paste secret value…' : 'Path or remote:subpath…';
    return Padding(
      padding: const EdgeInsets.only(top: 9),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              obscureText: true,
              style: sans(size: 12.5, weight: FontWeight.w500),
              decoration: InputDecoration(
                hintText: placeholder,
                hintStyle: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textDim),
                filled: true,
                fillColor: AppColors.bg,
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(6),
                  borderSide: BorderSide(color: AppColors.amber.withValues(alpha: 0.35)),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          ElevatedButton(
            onPressed: () {},
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.amber,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            ),
            child: Text('Continue', style: sans(size: 12.5, weight: FontWeight.w600, color: const Color(0xFF221A03))),
          ),
        ],
      ),
    );
  }

  Widget _failureBox(GuardStep step, AppState s) {
    final hasFix = step.guard.type == GuardType.requires || step.guard.type == GuardType.mount;
    final fixLabel = step.guard.type == GuardType.requires
        ? 'Run ${step.guard.label.replaceFirst('Requires ', '').split('.').last.replaceAll('_', ' ')} first'
        : 'Reconnect remote';
    void onFix() {
      if (step.guard.type == GuardType.requires) {
        s.jumpTo(step.guard.label.replaceFirst('Requires ', ''));
      } else {
        s.jumpTo('infrastructure.sync_rclone_remote');
      }
    }

    return Container(
      margin: const EdgeInsets.only(top: 7),
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
      decoration: BoxDecoration(
        color: AppColors.red.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: AppColors.red.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(step.reason ?? '', style: sans(size: 12, height: 1.5, color: AppColors.redText)),
          const SizedBox(height: 9),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (hasFix)
                ElevatedButton(
                  onPressed: onFix,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.red,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  ),
                  child: Text(fixLabel, style: sans(size: 12, weight: FontWeight.w600, color: const Color(0xFF2A0A0A))),
                ),
              OutlinedButton(
                onPressed: () => s.setScenario(RunScenario.progress),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(color: AppColors.red.withValues(alpha: 0.35)),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                ),
                child: Text('Retry', style: sans(size: 12, weight: FontWeight.w600, color: AppColors.redText)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
