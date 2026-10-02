"""Run the pull play from fresh facts with a fake Podman, without provisioning a host."""

from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

from tests.playbooks._ansible import ANSIBLE_DIR, PLAYBOOKS_DIR


@pytest.mark.parametrize("present", [False, True], ids=["missing-models", "existing-models"])
def test_pull_initializes_the_runtime_directory(tmp_path: Path, *, present: bool) -> None:
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\ninject_facts_as_vars = False\n")
    calls_file = tmp_path / "calls.jsonl"
    podman = tmp_path / "podman"
    models = "qwen2.5:3b abc 2GB now\nllama3.2:latest def 2GB now\n" if present else ""
    podman.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"with open({str(calls_file)!r}, 'a') as calls:\n"
        "    calls.write(json.dumps({'argv': sys.argv[1:], "
        "'runtime': os.environ.get('XDG_RUNTIME_DIR')}) + '\\n')\n"
        "if sys.argv[-1] == 'list':\n"
        f"    print('NAME ID SIZE MODIFIED\\n' + {models!r})\n"
    )
    podman.chmod(0o755)
    variables = tmp_path / "vars.json"
    variables.write_text(
        json.dumps(
            {
                "diot_user": pwd.getpwuid(os.getuid()).pw_name,
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
                "ollama_models": ["qwen2.5:3b", "llama3.2"],
            }
        )
    )
    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "ansible-playbook"),
            "-i",
            "localhost,",
            "-c",
            "local",
            "-e",
            f"@{ANSIBLE_DIR / 'inventory/group_vars/all/common.yml'}",
            "-e",
            f"@{variables}",
            str(PLAYBOOKS_DIR / "pull_ollama_model.yml"),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local"),
            "ANSIBLE_REMOTE_TEMP": str(tmp_path / "remote"),
            "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    commands = [["exec", "systemd-ollama", "ollama", "list"]]
    if not present:
        commands.extend(
            ["exec", "systemd-ollama", "ollama", "pull", model]
            for model in ["qwen2.5:3b", "llama3.2"]
        )
    assert calls == [
        {"argv": command, "runtime": f"/run/user/{os.getuid()}"} for command in commands
    ]
    assert f"changed={0 if present else 1}" in result.stdout
