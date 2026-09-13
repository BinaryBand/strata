import 'package:flutter/material.dart';

import '../theme.dart';

class StatusBadge extends StatelessWidget {
  final String text;
  final Color color;
  final Color background;
  final Color borderColor;

  const StatusBadge({
    super.key,
    required this.text,
    required this.color,
    required this.background,
    required this.borderColor,
  });

  factory StatusBadge.installed(bool installed) => installed
      ? const StatusBadge(text: 'Installed', color: Color(0xFF6EE7B7), background: Color(0x2434D399), borderColor: Color(0x4D34D399))
      : const StatusBadge(text: 'Not installed', color: Color(0xFFFCD34D), background: Color(0x24FBBF24), borderColor: Color(0x4DFBBF24));

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: borderColor),
      ),
      child: Text(text, style: mono(size: 10, weight: FontWeight.w700, color: color)),
    );
  }
}

class Pill extends StatelessWidget {
  final String text;
  final Color color;
  final Color background;

  const Pill({super.key, required this.text, required this.color, required this.background});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(4)),
      child: Text(text, style: sans(size: 10.5, weight: FontWeight.w600, color: color)),
    );
  }
}

class GhostButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;

  const GhostButton({super.key, required this.label, this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 34,
      child: OutlinedButton(
        onPressed: onTap,
        style: OutlinedButton.styleFrom(
          side: BorderSide(color: AppColors.border(0.13)),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          padding: const EdgeInsets.symmetric(horizontal: 13),
        ),
        child: Text(label, style: sans(size: 12.5, weight: FontWeight.w500, color: AppColors.textSecondary)),
      ),
    );
  }
}

class PrimaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  final bool expand;

  const PrimaryButton({super.key, required this.label, this.onTap, this.expand = false});

  @override
  Widget build(BuildContext context) {
    final disabled = onTap == null;
    final btn = SizedBox(
      height: 38,
      width: expand ? double.infinity : null,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: disabled ? const Color(0xFF2A3040) : AppColors.cyan,
          disabledBackgroundColor: const Color(0xFF2A3040),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          padding: const EdgeInsets.symmetric(horizontal: 18),
        ),
        child: Text(
          label,
          style: sans(size: 13, weight: FontWeight.w700, color: disabled ? AppColors.textDim : const Color(0xFF04222A)),
        ),
      ),
    );
    return btn;
  }
}

class DangerButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;

  const DangerButton({super.key, required this.label, this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 34,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.pink,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          padding: const EdgeInsets.symmetric(horizontal: 14),
        ),
        child: Text(label, style: sans(size: 12.5, weight: FontWeight.w600, color: const Color(0xFF2A0A12))),
      ),
    );
  }
}

class ToastOverlay extends StatelessWidget {
  final String text;

  const ToastOverlay({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    return Positioned(
      left: 0,
      right: 0,
      bottom: 24,
      child: Center(
        child: Material(
          color: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(9),
          elevation: 12,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppColors.green.withValues(alpha: 0.35)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('✓', style: sans(size: 13, color: AppColors.green)),
                const SizedBox(width: 8),
                Text(text, style: sans(size: 12.5, weight: FontWeight.w500)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
