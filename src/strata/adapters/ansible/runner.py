"""Shared ansible-runner wrapper for executing playbooks.

Satisfies the core.ports.PlaybookRunner protocol structurally, so the executor
can pass this module straight into a runbook's `runner` parameter.

Per-task progress goes through a reporter rather than print(), so the output
channel is the caller's choice: cli installs one that writes to the terminal,
and anything running headlessly (tests, future non-interactive callers) gets
silence instead of stray stdout it has to capture.
"""

from collections.abc import Mapping
from pathlib import Path

import ansible_runner

from strata.core import paths, ports

ANSIBLE_DIR = paths.ANSIBLE_DIR
_VAULT_PASS = ANSIBLE_DIR / "vault_pass.py"
# Module-level (not a function default) so tests can monkeypatch it and
# transparently redirect every run_playbook() call -- including the ones
# guard.* decorators make internally, which have no inventory kwarg of
# their own -- at a disposable test inventory instead of the real one.
_DEFAULT_INVENTORY = ANSIBLE_DIR / "inventory" / "hosts.ini"
# ansible-runner treats private_data_dir as persistent job state: it reads
# env/extravars, env/cmdline, env/envvars from here as *base* extravars for
# every run, merged under whatever this call passes explicitly. Since this
# always pointed at the real ansible/ directory, a leftover env/extravars
# from one runbook's run silently bleeds into every later run that doesn't
# happen to override every one of its keys. Kept as ANSIBLE_DIR by default
# (unchanged real-world behavior) but monkeypatchable so tests can isolate
# their own runs into a scratch directory instead.
_DEFAULT_PRIVATE_DATA_DIR = ANSIBLE_DIR
# ansible-runner writes a full job-event dump per run under artifacts/ and
# never prunes it on its own; left unbounded this grew to 447 directories /
# 71 MB. rotate_artifacts keeps the N most recent and deletes the rest at the
# start of each run, so the recent runs stay inspectable without the tree
# growing forever.
_ARTIFACT_RETENTION = 25


# The host-keyed buckets ansible-runner reports in `stats`. A play that matched
# at least one host puts it in one of these, even if every task was skipped.
_STATS_HOST_BUCKETS = (
    "ok",
    "changed",
    "failures",
    "dark",
    "skipped",
    "rescued",
    "ignored",
    "processed",
)


def _matched_no_hosts(result: object) -> bool:
    """Report whether a nominally successful run had no host in scope at all.

    Ansible does not treat "no hosts matched" as an error, so a play whose
    `hosts:` never intersects the `--limit` this module always appends exits 0
    having done nothing -- which every caller reads as "provisioned". Guards
    compound it: an upstream whose playbook matches nothing is recorded as
    satisfied, and the dependent playbook then runs against a host that was
    never prepared. ensure_path.yml documents this being found the hard way.

    A result with no stats at all (an older ansible-runner, or a test double)
    is reported as False so the caller keeps its previous exit-code mapping
    rather than failing a run this cannot actually judge.
    """
    stats = getattr(result, "stats", None)
    if not isinstance(stats, dict):
        return False
    return not any(stats.get(bucket) for bucket in _STATS_HOST_BUCKETS)


def _task_status(res: Mapping[str, object]) -> str:
    """Classify one task result for the progress line.

    Only `changed` used to be consulted, so a task that failed, was
    unreachable, or never ran all printed as `[ok]` -- the per-task output
    said everything went fine and only the final status line disagreed.
    Order matters: a failed task can also carry changed=True.
    """
    if res.get("unreachable", False):
        return "unreachable"
    if res.get("failed", False):
        return "failed"
    if res.get("skipped", False):
        return "skipped"
    if res.get("changed", False):
        return "changed"
    return "ok"


# Default sink: drop progress unless a caller installs a real reporter.
_reporter: ports.Reporter = ports.NullReporter()


def set_reporter(reporter: ports.Reporter) -> None:
    """Install the reporter that playbook progress is written to.

    Called once by cli during wiring. Module-level rather than a parameter
    because run_playbook is reached both directly by runbooks and internally by
    the guard executor, and threading a reporter through every one of those
    call sites would buy nothing over setting it once at the composition root.
    """
    global _reporter  # noqa: PLW0603
    _reporter = reporter


def run_playbook(
    playbook: str,
    # ansible-runner serializes extravars to JSON, so nested values are fine.
    extravars: Mapping[str, object] | None = None,
    target: str | None = None,
    inventory: str | Path | None = None,
) -> int:
    """Run `playbook` against `target`, returning 0 on success.

    Args:
        playbook: Playbook path relative to ansible/.
        extravars: Extra variables; serialized to JSON, so nesting is fine.
        target: Inventory host to --limit to, or None for the whole inventory.
        inventory: Inventory override; defaults to ansible/inventory/hosts.ini.

    Returns:
        0 if the playbook succeeded against at least one host, 1 otherwise --
        including the case where the play matched no hosts, which ansible
        itself reports as success. See _matched_no_hosts.
    """
    cmdline = f"--vault-password-file={_VAULT_PASS}"
    if target:
        cmdline += f" --limit {target}"

    result = ansible_runner.run(
        private_data_dir=str(_DEFAULT_PRIVATE_DATA_DIR),
        project_dir=str(ANSIBLE_DIR),
        inventory=str(inventory or _DEFAULT_INVENTORY),
        playbook=playbook,
        extravars=extravars or {},
        cmdline=cmdline,
        rotate_artifacts=_ARTIFACT_RETENTION,
    )

    for event in result.events:
        event_data = event.get("event_data", {})
        task = event_data.get("task")
        res = event_data.get("res", {})
        if task and res:
            _reporter.info(f"  [{_task_status(res)}] {task}")

    if result.status == "successful":
        if _matched_no_hosts(result):
            scope = f" under --limit {target}" if target else ""
            _reporter.info(f"{playbook} matched no hosts{scope} -- nothing was done.")
            return 1
        return 0

    _reporter.info(f"Playbook failed (status={result.status}).")
    return 1
