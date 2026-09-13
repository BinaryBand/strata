import 'package:flutter/material.dart';

import 'main_shell.dart';
import 'theme.dart';

void main() {
  runApp(const StrataApp());
}

class StrataApp extends StatelessWidget {
  const StrataApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Strata',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const MainShell(),
    );
  }
}
