"""Manage Ansible inventory hosts in inventory/hosts.ini.

Remote devices live in a ``[remote]`` group alongside the built-in
``[local]`` group.  The ``[secrets:children]`` group is kept in sync so
that vault-encrypted vars are loaded for every managed host.

The low-level helpers parse and rewrite the INI file as plain text,
preserving comments and the ``[all]`` section untouched.
"""

import re

from strata.adapters import fs
from strata.core import paths
from strata.core.models import Device

_INI_PATH = paths.INVENTORY_DIR / "hosts.ini"

_REMOTE_GROUP = "remote"
_LOCAL_GROUP = "local"
_SECRETS_CHILDREN = "secrets:children"

# Every section other than [remote] and [secrets:children] is now passed
# through verbatim, so the old _PRESERVED_SECTIONS allowlist is gone: it
# enumerated what to protect, which meant a group nobody thought to list --
# any operator-defined one -- was fair game for the device CRUD to rewrite.

# ── INI parser ────────────────────────────────────────────────────────────────────────

_HEADER_RE = re.compile(r"^\[([^\]]+)\]\s*$")
_HOST_LINE_RE = re.compile(r"^(\S+)(?:\s+(.*))?$")
_VAR_RE = re.compile(r"(\w+)\s*=\s*(\S*)")

# Lines before the first [section] header. Rendered back without a header;
# keying them under "" made _render_section emit a literal "[]" line, so a
# single leading comment turned every later rewrite into a corrupt file.
_PREAMBLE = ""

# The four variables this module understands well enough to model. Anything
# else on a host line is carried through verbatim rather than parsed away --
# hosts.ini already relies on that for ansible_become_exe, and dropping e.g.
# ansible_ssh_private_key_file on the next `strata device add` would silently
# break access to the host.
_KNOWN_VARS = (
    ("host", "ansible_host"),
    ("user", "ansible_user"),
    ("connection", "ansible_connection"),
    ("port", "ansible_port"),
)
_VAR_TO_KEY = {var: key for key, var in _KNOWN_VARS}
_EXTRAS_KEY = "extras"


def _parse_ini(text: str) -> dict[str, list[str]]:
    """Parse INI text into ``{section: [raw_lines]}``.

    Comments and blank lines inside a section are preserved so they
    survive a round-trip. Lines before the first header land under
    ``_PREAMBLE``.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current if current is not None else _PREAMBLE, []).append(line)
    return sections


def _strip_comment(text: str) -> str:
    """Drop an inline ``#`` comment from the variable portion of a host line.

    Without this, _VAR_RE happily matched inside the comment, so
    ``h1 ansible_host=1.2.3.4  # was ansible_user=old`` parsed a commented-out
    value as live configuration -- and then wrote it back as real config.
    """
    return text.split("#", 1)[0]


def _parse_host_line(line: str) -> dict[str, object] | None:
    """Parse a host definition line into a dict.

    Returns None for blank, comment, and child-group lines.

    Args:
        line: A single raw line from an inventory section.

    Returns:
        A dict with ``name``, any of ``host``/``user``/``connection``/``port``
        the line declared, and ``extras`` holding every other variable in
        source order; or None if the line defines no host.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", ":children")):
        return None
    # A bare hostname with no variables is valid inventory. The old pattern
    # required whitespace, so such a host parsed as None: invisible to get()
    # and all_hosts(), and deleted by the next rewrite.
    m = _HOST_LINE_RE.match(stripped)
    if not m:
        return None
    result: dict[str, object] = {"name": m.group(1)}
    extras: dict[str, str] = {}
    for vm in _VAR_RE.finditer(_strip_comment(m.group(2) or "")):
        var, value = vm.group(1), vm.group(2)
        key = _VAR_TO_KEY.get(var)
        if key is None:
            extras[var] = value
        else:
            result[key] = value
    result[_EXTRAS_KEY] = extras
    return result


def _build_host_line(entry: dict[str, object]) -> str:
    """Build a host definition line from a dict, keeping unmodelled variables."""
    parts = [str(entry["name"])]
    parts.extend(
        f"{var}={entry[key]}" for key, var in _KNOWN_VARS if entry.get(key) not in (None, "")
    )
    extras = entry.get(_EXTRAS_KEY) or {}
    if isinstance(extras, dict):
        parts.extend(f"{var}={value}" for var, value in extras.items())
    return " ".join(parts)


# ── File I/O ──────────────────────────────────────────────────────────────────────────


def _read() -> str:
    return _INI_PATH.read_text() if _INI_PATH.exists() else ""


def _write(text: str) -> None:
    _INI_PATH.parent.mkdir(parents=True, exist_ok=True)
    fs.write_text(_INI_PATH, text)


def _entries_from_sections(text: str, group: str = _REMOTE_GROUP) -> list[dict[str, object]]:
    """Extract host entries from one section of parsed INI text.

    Scoped to a single group on purpose. This used to sweep every section
    that was not explicitly preserved, so hosts in an operator-defined group
    like ``[servers]`` were collected as entries and then written into
    ``[remote]`` by _rewrite -- while _render_section also passed their
    original group through untouched, leaving the same host in two groups
    with only the four modelled variables in one of them.
    """
    sections = _parse_ini(text)
    entries: list[dict[str, object]] = []
    for line in sections.get(group, []):
        parsed = _parse_host_line(line)
        if parsed:
            entries.append(parsed)
    return entries


def _remote_block(existing: list[str], entries: list[dict[str, object]]) -> list[str]:
    """Render ``[remote]``, rewriting host lines in place and keeping the rest.

    Walks the section as it was written rather than regenerating it from
    entries alone: comments and blank lines stay where the operator put them,
    next to the host they document, and a host that was only updated keeps
    its position. Regenerating from entries deleted every comment in the
    group -- which the module docstring's "preserving comments" claim had
    been wrong about for as long as this existed.
    """
    by_name = {str(e["name"]): e for e in entries}
    emitted: set[str] = set()
    body: list[str] = []
    for line in existing:
        parsed = _parse_host_line(line)
        if parsed is None:
            body.append(line)
            continue
        name = str(parsed["name"])
        if name in by_name:
            body.append(_build_host_line(by_name[name]))
            emitted.add(name)
        # A host absent from entries was removed; drop its line.
    body.extend(_build_host_line(e) for name, e in by_name.items() if name not in emitted)

    # Nothing but comments left behind means the group is empty; drop it
    # entirely, which is what the previous implementation did too.
    if not any(_parse_host_line(line) for line in body):
        return []
    return [f"[{_REMOTE_GROUP}]", *body]


def _secrets_children_block(entries: list[dict[str, object]]) -> list[str]:
    """Render ``[secrets:children]``, listing ``[remote]`` only when it has hosts."""
    block = [f"[{_SECRETS_CHILDREN}]", _LOCAL_GROUP]
    if entries:
        block.append(_REMOTE_GROUP)
    return block


def _render_section(
    sec_name: str,
    lines: list[str],
    *,
    entries: list[dict[str, object]],
) -> list[str]:
    """Render one existing section, regenerating the two managed groups."""
    if sec_name == _PREAMBLE:
        # Leading comments/blank lines: no header to re-emit.
        return list(lines)
    if sec_name == _REMOTE_GROUP:
        return _remote_block(lines, entries)
    if sec_name == _SECRETS_CHILDREN:
        return _secrets_children_block(entries)
    # Everything else, [local] included, is passed through untouched.
    return [f"[{sec_name}]", *lines]


def _rewrite(text: str, entries: list[dict[str, object]]) -> str:
    """Rewrite the INI, replacing the ``[remote]`` group contents.

    Entries already in ``[local]`` are left untouched.
    ``[secrets:children]`` is kept in sync.
    """
    sections = _parse_ini(text)

    out: list[str] = []
    for sec_name, lines in sections.items():
        out.extend(_render_section(sec_name, lines, entries=entries))

    # Append the managed groups the file did not already contain.
    if _REMOTE_GROUP not in sections:
        out.extend(_remote_block([], entries))
    if _SECRETS_CHILDREN not in sections:
        out.extend(_secrets_children_block(entries))

    result = "\n".join(out)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


# ── CRUD ──────────────────────────────────────────────────────────────────────────────


def add(
    name: str,
    host: str,
    *,
    user: str = "root",
    connection: str = "ssh",
    port: int | None = None,
) -> Device:
    """Add (or update) a remote device in the inventory.

    If *name* already exists in ``[remote]``, its fields are updated.
    """
    text = _read()
    entries: list[dict[str, object]] = _entries_from_sections(text)

    new_entry: dict[str, object] = {
        "name": name,
        "host": host,
        "user": user,
        "connection": connection,
        _EXTRAS_KEY: {},
    }
    if port is not None:
        new_entry["port"] = str(port)

    for i, e in enumerate(entries):
        if e["name"] == name:
            # Updating the four modelled fields must not discard the ones
            # this module does not model -- re-running `device add` on a host
            # carrying ansible_become_exe would otherwise silently drop it.
            new_entry[_EXTRAS_KEY] = e.get(_EXTRAS_KEY) or {}
            entries[i] = new_entry
            break
    else:
        entries.append(new_entry)

    _write(_rewrite(text, entries))
    return Device(
        name=name,
        host=host,
        user=user,
        connection=connection,
        port=port,
    )


def remove(name: str) -> bool:
    """Remove a device from ``[remote]``.  Refuses ``[local]`` hosts."""
    # One read, reused. Reading three times meant the membership check and
    # the text that got rewritten were different snapshots of the file.
    text = _read()
    sections = _parse_ini(text)
    for line in sections.get(_LOCAL_GROUP, []):
        parsed = _parse_host_line(line)
        if parsed and parsed["name"] == name:
            return False

    entries = _entries_from_sections(text)
    new_entries = [e for e in entries if e["name"] != name]
    if len(new_entries) == len(entries):
        return False

    _write(_rewrite(text, new_entries))
    return True


def _default_connection(group: str) -> str:
    """Connection a host in `group` gets when its line does not say."""
    return "local" if group == _LOCAL_GROUP else "ssh"


def _device_from(parsed: dict[str, object], *, group: str) -> Device:
    """Build a Device from a parsed host line.

    The single place a missing field gets a default. There used to be three,
    disagreeing: get() defaulted connection to "local" for hosts in *any*
    group, all_hosts() defaulted per group, and list_all() went through
    Device's own "ssh". Since _is_controller() is built on get(), a [remote]
    host whose line omitted ansible_connection was judged to be the
    controller -- so every guard fast path inspected the local machine and
    skipped provisioning the remote one.
    """
    port = parsed.get("port")
    return Device(
        name=str(parsed["name"]),
        host=str(parsed.get("host", "")),
        user=str(parsed.get("user", "root")),
        connection=str(parsed.get("connection", _default_connection(group))),
        port=int(str(port)) if port else None,
    )


def list_all() -> list[Device]:
    """Return all remote devices from the ``[remote]`` group."""
    entries = _entries_from_sections(_read(), group=_REMOTE_GROUP)
    return [_device_from(e, group=_REMOTE_GROUP) for e in entries]


def all_hosts() -> list[Device]:
    """Return every targetable host: the ``[local]`` controller plus ``[remote]`` devices.

    Unlike ``list_all()`` (remote only), this includes the local controller,
    since a runbook can target either. ``[local]`` hosts default to a ``local``
    connection when the line does not say otherwise.
    """
    sections = _parse_ini(_read())
    return [
        _device_from(parsed, group=group)
        for group in (_LOCAL_GROUP, _REMOTE_GROUP)
        for line in sections.get(group, [])
        if (parsed := _parse_host_line(line)) is not None
    ]


def get(name: str) -> Device | None:
    """Return a device by name (searches all groups), or ``None``.

    The connection default comes from the group the host was found in, so a
    ``[remote]`` line with no explicit ansible_connection is reported as
    ``ssh`` rather than ``local``. See _device_from.
    """
    sections = _parse_ini(_read())
    for sec_name, lines in sections.items():
        if sec_name in {_PREAMBLE, _SECRETS_CHILDREN}:
            continue
        for line in lines:
            parsed = _parse_host_line(line)
            if parsed and parsed["name"] == name:
                return _device_from(parsed, group=sec_name)
    return None
