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
    final readiness = computeReadiness(rb, s.targetIsController, liveSteps: s.statusLoaded ? s.guardSteps : null);
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
          if (s.needsVaultPasswordFirst) _VaultPasswordRow(state: s),
          if (rb.guards.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text('Nothing needed — this runs straight away.', style: sans(size: 12.5, color: AppColors.textDim)),
            )
          else
            Column(
              children: [
                for (final step in s.guardSteps) _buildGuardChip(context, step, s),
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
                        PrimaryButton(label: 'Run on ${s.activeDevice.name}', onTap: s.canRun ? s.startRun : null, expand: true),
                        const SizedBox(height: 7),
                        Text(_runHint(s, readiness), textAlign: TextAlign.center, style: sans(size: 11.5, color: AppColors.textDim)),
                      ],
                    )
                  : Row(
                      children: [
                        PrimaryButton(label: 'Run on ${s.activeDevice.name}', onTap: s.canRun ? s.startRun : null),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(_runHint(s, readiness), style: sans(size: 11.5, color: AppColors.textDim)),
                        ),
                      ],
                    ),
            ),
          ),
        ],
      ),
    );
  }

  String _runHint(AppState s, Readiness r) {
    if (!s.hasLiveApi) return 'Not connected to strata — run `strata gui` to enable this.';
    if (s.selectedBlockedByTarget) return 'Switch the target to run this.';
    if (s.needsVaultPasswordFirst) return 'Unlock the vault above before running.';
    if (r.key == 'asks') return 'Fill in what\'s missing above before running.';
    if (!s.statusLoaded) return 'Checking what this needs…';
    return 'Everything it needs is on hand — no prompts expected.';
  }

  Widget _buildGuardChip(BuildContext context, GuardStep step, AppState s) {
    final g = step.guard;
    final meta = guardMeta[g.type]!;
    final hint = guardHint[g.type]!;
    final loading = !s.statusLoaded;
    final missing = step.status == GuardReadiness.missing;
    final needsInput = step.needsInputWhenMissing && missing;
    final isReq = g.type == GuardType.requires;

    final (stateText, stateColor, stateBg) = switch (step.status) {
      _ when loading => ('Checking…', AppColors.textMuted, AppColors.border(0.05)),
      GuardReadiness.satisfied => ('OK', AppColors.greenText, AppColors.green.withValues(alpha: 0.12)),
      GuardReadiness.unknown => ("Can't tell", AppColors.textMuted, AppColors.border(0.05)),
      GuardReadiness.missing when needsInput => ('Needs input', AppColors.amberText, AppColors.amber.withValues(alpha: 0.12)),
      GuardReadiness.missing => ('Will resolve automatically', AppColors.textMuted, AppColors.border(0.05)),
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 7),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.border(0.03),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppColors.border(0.07)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
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
          if (needsInput && !s.needsVaultPasswordFirst) _GuardInputRow(state: s, guard: g),
        ],
      ),
    );
  }
}

class _VaultPasswordRow extends StatefulWidget {
  final AppState state;

  const _VaultPasswordRow({required this.state});

  @override
  State<_VaultPasswordRow> createState() => _VaultPasswordRowState();
}

class _VaultPasswordRowState extends State<_VaultPasswordRow> {
  final _controller = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    await widget.state.submitVaultPassword(_controller.text);
    _controller.clear();
    if (mounted) setState(() => _submitting = false);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
      decoration: BoxDecoration(
        color: AppColors.amber.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppColors.amber.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Vault password needed', style: sans(size: 12.5, weight: FontWeight.w600, color: AppColors.amberText)),
          const SizedBox(height: 3),
          Text(
            'This runbook needs to read or write a vaulted secret. Unlock the vault first.',
            style: sans(size: 11.5, color: AppColors.textDim),
          ),
          const SizedBox(height: 9),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  obscureText: true,
                  enabled: !_submitting,
                  style: sans(size: 12.5, weight: FontWeight.w500),
                  decoration: InputDecoration(
                    hintText: 'Vault password…',
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
                  onSubmitted: (_) => _submit(),
                ),
              ),
              const SizedBox(width: 8),
              ElevatedButton(
                onPressed: _submitting ? null : _submit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.amber,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                ),
                child: Text('Unlock', style: sans(size: 12.5, weight: FontWeight.w600, color: const Color(0xFF221A03))),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GuardInputRow extends StatefulWidget {
  final AppState state;
  final Guard guard;

  const _GuardInputRow({required this.state, required this.guard});

  @override
  State<_GuardInputRow> createState() => _GuardInputRowState();
}

class _GuardInputRowState extends State<_GuardInputRow> {
  final _controller = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    await widget.state.submitGuardValue(widget.guard, _controller.text);
    _controller.clear();
    if (mounted) setState(() => _submitting = false);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 9),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              obscureText: true,
              enabled: !_submitting,
              style: sans(size: 12.5, weight: FontWeight.w500),
              decoration: InputDecoration(
                hintText: 'Paste value…',
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
              onSubmitted: (_) => _submit(),
            ),
          ),
          const SizedBox(width: 8),
          ElevatedButton(
            onPressed: _submitting ? null : _submit,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.amber,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            ),
            child: Text('Save', style: sans(size: 12.5, weight: FontWeight.w600, color: const Color(0xFF221A03))),
          ),
        ],
      ),
    );
  }
}

/// Shows a real run's live status and output, polled from `GET /api/run/<id>`.
///
/// There is no per-guard progress here (only per-requirement/top-level lines
/// as guard_executor.execute() reports them) -- the readiness checklist above
/// this view, on [_DetailView], is the last per-guard detail available before
/// the run starts.
class _RunFlowView extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const _RunFlowView({required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final s = state;
    final rb = s.selectedRunbook;
    final run = s.run;
    final lines = run?.lines ?? const <String>[];

    final runTitle = switch (run?.status) {
      RunLifecycle.succeeded => 'Finished ${rb.alias}',
      RunLifecycle.failed => 'Could not run ${rb.alias}',
      _ => 'Running ${rb.alias}',
    };
    final (statusText, statusColor, statusBg) = switch (run?.status) {
      RunLifecycle.succeeded => ('Completed', AppColors.greenText, AppColors.green.withValues(alpha: 0.12)),
      RunLifecycle.failed => ('Failed (exit ${run?.exitCode})', AppColors.redText, AppColors.red.withValues(alpha: 0.12)),
      _ => ('Starting…', AppColors.cyanSoft, AppColors.cyan.withValues(alpha: 0.12)),
    };
    final progressColor = switch (run?.status) {
      RunLifecycle.failed => AppColors.red,
      RunLifecycle.succeeded => AppColors.green,
      _ => AppColors.cyan,
    };
    final finished = run != null && run.status != RunLifecycle.running;

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 26, isMobile ? 14 : 22, isMobile ? 16 : 26, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _backButton(finished),
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
              child: finished
                  ? Container(color: progressColor)
                  : const LinearProgressIndicator(minHeight: 4, backgroundColor: Color(0xFF1A1F2A), color: AppColors.cyan),
            ),
          ),
          const SizedBox(height: 20),
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
                Text('Output', style: sans(size: 12.5, weight: FontWeight.w600, color: AppColors.textMuted)),
                const SizedBox(height: 8),
                if (lines.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    child: Text('Waiting for output…', style: sans(size: 12.5, color: const Color(0xFF4A5160))),
                  )
                else
                  Text(
                    lines.join('\n'),
                    style: mono(size: 12, weight: FontWeight.w400, color: const Color(0xFF8EE6B8)),
                  ),
              ],
            ),
          ),
          if (finished)
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
                  GhostButton(label: 'Run again', onTap: s.retryRun),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _backButton(bool finished) {
    return TextButton(
      onPressed: finished ? state.backToDetail : null,
      style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
      child: Text(
        '‹ Back',
        style: sans(
          size: isMobile ? 13 : 12,
          weight: isMobile ? FontWeight.w600 : FontWeight.w500,
          color: finished ? (isMobile ? AppColors.cyan : AppColors.textDim) : AppColors.textDim.withValues(alpha: 0.4),
        ),
      ),
    );
  }
}
