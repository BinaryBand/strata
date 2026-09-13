import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_state.dart';
import 'models.dart';
import 'screens/apps_screen.dart';
import 'screens/machines_screen.dart';
import 'screens/runbooks_screen.dart';
import 'theme.dart';
import 'widgets/common.dart';
import 'widgets/header.dart';
import 'widgets/sidebar.dart';

const _mobileBreakpoint = 1000.0;

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  late final AppState _state;

  @override
  void initState() {
    super.initState();
    _state = AppState()..addListener(_onStateChanged);
    _state.loadRealData();
  }

  void _onStateChanged() => setState(() {});

  @override
  void dispose() {
    _state.removeListener(_onStateChanged);
    _state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;
    final isMobile = width < _mobileBreakpoint;

    Widget screen = switch (_state.screen) {
      Screen.runbooks => RunbooksScreen(state: _state, isMobile: isMobile),
      Screen.apps => AppsScreen(state: _state, isMobile: isMobile),
      Screen.machines => MachinesScreen(state: _state, isMobile: isMobile),
    };

    return Shortcuts(
      shortcuts: {
        LogicalKeySet(LogicalKeyboardKey.escape): const _EscapeIntent(),
      },
      child: Actions(
        actions: {
          _EscapeIntent: CallbackAction<_EscapeIntent>(onInvoke: (_) {
            _state.closeOverlays();
            return null;
          }),
        },
        child: Focus(
          autofocus: true,
          child: Scaffold(
            backgroundColor: AppColors.bg,
            body: Stack(
              children: [
                Row(
                  children: [
                    if (!isMobile) Sidebar(state: _state, isMobile: isMobile),
                    Expanded(
                      child: Column(
                        children: [
                          AppHeader(state: _state, isMobile: isMobile),
                          Expanded(child: screen),
                        ],
                      ),
                    ),
                  ],
                ),
                if (isMobile) Sidebar(state: _state, isMobile: isMobile),
                if (_state.targetOpen)
                  Positioned.fill(
                    child: GestureDetector(
                      onTap: _state.toggleTargetMenu,
                      child: Container(color: Colors.transparent),
                    ),
                  ),
                TargetMenuOverlay(state: _state),
                if (_state.toast.isNotEmpty) ToastOverlay(text: _state.toast),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _EscapeIntent extends Intent {
  const _EscapeIntent();
}
