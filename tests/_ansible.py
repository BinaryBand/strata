"""Where the Ansible sources live, for the gates that parse them.

Four test modules had each spelled the path to `ansible/` from their own
location. The answer is a property of the repository layout, not of any one
gate, so it is stated once here.
"""

from __future__ import annotations

from pathlib import Path

ANSIBLE_DIR = Path(__file__).resolve().parents[1] / "ansible"
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"

# Every file that holds Ansible tasks: the playbooks and the roles' task,
# handler and default files.
TASK_FILES = sorted([*PLAYBOOKS_DIR.glob("*.yml"), *ANSIBLE_DIR.glob("roles/*/*/*.yml")])
