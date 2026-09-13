import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'models.dart';

class AppColors {
  static const bg = Color(0xFF0B0E13);
  static const headerBg = Color(0xFF0D1017);
  static const sidebarBg = Color(0xFF101319);
  static const surface = Color(0xFF141922);
  static const surfaceAlt = Color(0xFF161B22);
  static const inputBg = Color(0xFF12161D);

  static const textPrimary = Color(0xFFE6E9EF);
  static const textSecondary = Color(0xFFC3C9D3);
  static const textMuted = Color(0xFF8992A1);
  static const textDim = Color(0xFF5B6472);

  static const cyan = Color(0xFF22D3EE);
  static const cyanSoft = Color(0xFF67E8DD);
  static const teal = Color(0xFF0E9488);

  static const green = Color(0xFF34D399);
  static const greenText = Color(0xFF6EE7B7);
  static const amber = Color(0xFFFBBF24);
  static const amberText = Color(0xFFFCD34D);
  static const red = Color(0xFFF87171);
  static const redText = Color(0xFFFCA5A5);
  static const pink = Color(0xFFFB7185);
  static const pinkText = Color(0xFFFDA4AF);
  static const purple = Color(0xFFA78BFA);
  static const tealUser = Color(0xFF2DD4BF);
  static const blueMount = Color(0xFF38BDF8);
  static const indigoStorage = Color(0xFF818CF8);
  static const slate = Color(0xFF94A3B8);

  static Color border(double opacity) => Colors.white.withValues(alpha: opacity);
}

class GuardMeta {
  final String abbr;
  final Color color;

  const GuardMeta(this.abbr, this.color);
}

const guardMeta = <GuardType, GuardMeta>{
  GuardType.prerequisite: GuardMeta('SUDO', AppColors.cyan),
  GuardType.secret: GuardMeta('SECRET', AppColors.purple),
  GuardType.user: GuardMeta('USER', AppColors.tealUser),
  GuardType.path: GuardMeta('PATH', AppColors.amber),
  GuardType.mount: GuardMeta('MOUNT', AppColors.blueMount),
  GuardType.storage: GuardMeta('STORE', AppColors.indigoStorage),
  GuardType.requires: GuardMeta('REQ', AppColors.slate),
  GuardType.controllerOnly: GuardMeta('ONLY', AppColors.pink),
};

const guardHint = <GuardType, String>{
  GuardType.prerequisite: 'Stored for this session',
  GuardType.secret: 'Not in vault — you’ll be asked',
  GuardType.user: 'Created on target if missing',
  GuardType.path: 'Created on target if missing',
  GuardType.mount: 'Checked on target',
  GuardType.storage: 'Not set — you’ll be asked',
  GuardType.requires: 'Runs automatically if missing',
  GuardType.controllerOnly: 'Only runs on This machine',
};

const failReasons = <GuardType, String>{
  GuardType.requires: 'Upstream runbook has not run on this target yet.',
  GuardType.mount: 'Remote "pcloud" is registered but not authorized — reconnect it before retrying.',
  GuardType.prerequisite: 'No sudo password registered for this session.',
  GuardType.path: 'Path exists but is owned by root, not diot.',
  GuardType.secret: 'Vault is locked — unlock it before this secret can be read.',
  GuardType.user: 'System user creation failed: playbook exited non-zero.',
  GuardType.storage: 'Configured storage location is unreachable.',
  GuardType.controllerOnly: 'This runbook cannot target a remote host.',
};

TextStyle sans({
  double size = 13,
  FontWeight weight = FontWeight.w400,
  Color color = AppColors.textPrimary,
  double? letterSpacing,
  double? height,
}) {
  return GoogleFonts.ibmPlexSans(
    fontSize: size,
    fontWeight: weight,
    color: color,
    letterSpacing: letterSpacing,
    height: height,
  );
}

TextStyle mono({
  double size = 12,
  FontWeight weight = FontWeight.w500,
  Color color = AppColors.textDim,
  double? letterSpacing,
}) {
  return GoogleFonts.ibmPlexMono(
    fontSize: size,
    fontWeight: weight,
    color: color,
    letterSpacing: letterSpacing,
  );
}

ThemeData buildAppTheme() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.bg,
    canvasColor: AppColors.bg,
    textTheme: GoogleFonts.ibmPlexSansTextTheme(base.textTheme).apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    ),
    colorScheme: base.colorScheme.copyWith(
      primary: AppColors.cyan,
      surface: AppColors.bg,
    ),
    dividerColor: AppColors.border(0.07),
    scrollbarTheme: ScrollbarThemeData(
      thumbColor: WidgetStateProperty.all(const Color(0xFF262C38)),
    ),
  );
}
