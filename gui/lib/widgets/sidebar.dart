import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';
import '../theme.dart';

class Sidebar extends StatelessWidget {
  final AppState state;
  final bool isMobile;

  const Sidebar({super.key, required this.state, required this.isMobile});

  @override
  Widget build(BuildContext context) {
    final content = Container(
      width: isMobile ? null : 236,
      color: AppColors.sidebarBg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: AppColors.border(0.07))),
            ),
            child: Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(7),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [AppColors.cyan, AppColors.teal],
                    ),
                  ),
                  alignment: Alignment.center,
                  child: Text('s', style: mono(size: 14, weight: FontWeight.w700, color: const Color(0xFF04222A))),
                ),
                const SizedBox(width: 10),
                Text('strata', style: sans(size: 15.5, weight: FontWeight.w600, letterSpacing: 0.2)),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(10),
              children: [
                _NavButton(
                  label: 'Runbooks',
                  count: '${state.runbooks.length}',
                  active: state.screen == Screen.runbooks,
                  onTap: state.selectScreenRunbooks,
                ),
                const SizedBox(height: 4),
                _CategoryRow(
                  label: 'All categories',
                  count: null,
                  active: state.selectedCategory == null,
                  onTap: state.selectAllCategories,
                ),
                ...RunbookCategory.values.map((cat) {
                  final count = state.runbooks.where((r) => r.category == cat).length;
                  return _CategoryRow(
                    label: cat.label,
                    count: count,
                    active: state.selectedCategory == cat,
                    onTap: () => state.selectCategory(cat),
                  );
                }),
                const SizedBox(height: 14),
                _NavButton(
                  label: 'Server apps',
                  count: '2',
                  active: state.screen == Screen.apps,
                  onTap: state.selectScreenApps,
                ),
                const SizedBox(height: 14),
                _NavButton(
                  label: 'Machines',
                  count: '${state.machines.length}',
                  active: state.screen == Screen.machines,
                  onTap: state.selectScreenMachines,
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: AppColors.border(0.07))),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (!state.usingLiveData)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(2, 0, 2, 8),
                    child: Text(
                      'Sample data — couldn\'t reach the strata CLI',
                      style: sans(size: 11, weight: FontWeight.w500, color: AppColors.amberText),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2),
                  child: RichText(
                    text: TextSpan(
                      style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textDim, height: 1.6),
                      children: [
                        const TextSpan(text: 'Shortcuts: '),
                        TextSpan(text: '/', style: mono(size: 11.5, color: AppColors.textMuted)),
                        const TextSpan(text: ' search · '),
                        TextSpan(text: 'Esc', style: mono(size: 11.5, color: AppColors.textMuted)),
                        const TextSpan(text: ' close · '),
                        TextSpan(text: '↵', style: mono(size: 11.5, color: AppColors.textMuted)),
                        const TextSpan(text: ' open first result'),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );

    if (!isMobile) {
      return Container(
        decoration: BoxDecoration(
          border: Border(right: BorderSide(color: AppColors.border(0.07))),
        ),
        child: content,
      );
    }

    return Stack(
      children: [
        if (state.sidebarOpen)
          Positioned.fill(
            child: GestureDetector(
              onTap: state.closeSidebar,
              child: Container(color: Colors.black.withValues(alpha: 0.5)),
            ),
          ),
        AnimatedPositioned(
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
          top: 0,
          bottom: 0,
          left: state.sidebarOpen ? 0 : -280,
          width: 280,
          child: Material(
            elevation: state.sidebarOpen ? 24 : 0,
            color: AppColors.sidebarBg,
            child: content,
          ),
        ),
      ],
    );
  }
}

class _NavButton extends StatelessWidget {
  final String label;
  final String count;
  final bool active;
  final VoidCallback onTap;

  const _NavButton({required this.label, required this.count, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(7),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        decoration: BoxDecoration(
          color: active ? AppColors.cyan.withValues(alpha: 0.1) : Colors.transparent,
          borderRadius: BorderRadius.circular(7),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: sans(size: 13, weight: FontWeight.w600, color: active ? AppColors.textPrimary : AppColors.textSecondary)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
              decoration: BoxDecoration(
                color: AppColors.border(0.05),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(count, style: sans(size: 11.5, weight: FontWeight.w500, color: AppColors.textDim)),
            ),
          ],
        ),
      ),
    );
  }
}

class _CategoryRow extends StatelessWidget {
  final String label;
  final int? count;
  final bool active;
  final VoidCallback onTap;

  const _CategoryRow({required this.label, required this.count, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(6),
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(top: 1),
        padding: const EdgeInsets.fromLTRB(20, 6, 10, 6),
        decoration: BoxDecoration(
          color: active ? AppColors.border(0.06) : Colors.transparent,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: sans(size: 12.5, weight: FontWeight.w500, color: active ? AppColors.textPrimary : AppColors.textMuted),
              ),
            ),
            if (count != null)
              Text('$count', style: mono(size: 10.5, weight: FontWeight.w500, color: AppColors.textDim)),
          ],
        ),
      ),
    );
  }
}
