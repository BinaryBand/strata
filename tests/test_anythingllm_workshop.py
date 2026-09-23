"""The strata-workshop AnythingLLM skill keeps every draft unloadable until switched on.

AnythingLLM 1.16 loads a skill or flow named in a scheduled job's tool list
without checking `active`, so these tests assert on what is on disk: a drafted
skill has no handler.js and a drafted flow is a start-only stub until the user's
toggle sets `active: true` and the sweep promotes the approved bytes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "ansible" / "playbooks" / "files" / "strata-workshop"
FIXTURES = ROOT / "tests" / "fixtures" / "anythingllm_workshop"
NODE = shutil.which("node")

HANDLER = 'module.exports.runtime = { handler: async () => "hi" };'
MANIFEST = {
    "name": "Hello",
    "schema": "skill-1.0.0",
    "version": "1.0.0",
    "description": "Says hi.",
    "entrypoint": {"file": "handler.js", "params": {}},
}
FLOW = {
    "description": "Scrape then summarise",
    "steps": [
        {"type": "start", "config": {"variables": [{"name": "url", "type": "required"}]}},
        {"type": "webScraping", "config": {"url": "${url}", "resultVariable": "page"}},
    ],
}
# A stand-in for AnythingLLM's models/workspace.js, found by the workshop at
# <storage>/../models/workspace.js exactly as in the image.
FAKE_WORKSPACE = """
const rows = [];
module.exports.Workspace = {
  get: async ({ slug }) => rows.find((r) => r.slug === slug) || null,
  where: async () => rows,
  new: async (name, _c, f) => {
    const w = { id: rows.length + 1, slug: name.toLowerCase(), name, ...f };
    rows.push(w); return { workspace: w, message: null }; },
  update: async (id, u) => { const w = rows.find((r) => r.id === id); Object.assign(w, u);
    return { workspace: w, message: null }; },
};
"""


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    assert NODE, "node is required to test the strata-workshop skill"
    (tmp_path / "server" / "models").mkdir(parents=True)
    (tmp_path / "server" / "models" / "workspace.js").write_text(FAKE_WORKSPACE)
    store = tmp_path / "server" / "storage"
    (store / "plugins").mkdir(parents=True)
    return store


def run(storage: Path, *steps: dict) -> list:
    steps_file = storage.parent / "steps.json"
    steps_file.write_text(json.dumps(list(steps)))
    result = subprocess.run(
        [str(NODE), str(FIXTURES / "harness.mjs"), str(SKILL), str(steps_file)],
        capture_output=True,
        text=True,
        env={**os.environ, "STORAGE_DIR": str(storage)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def call(action: str, *, approve: bool = True, interactive: bool = True, **args: object) -> dict:
    return {
        "op": "call",
        "approve": approve,
        "interactive": interactive,
        "args": {"action": action, **args},
    }


def draft_skill(
    hub_id: str = "hello", handler: str = HANDLER, *, approve: bool = True, interactive: bool = True
) -> dict:
    return call(
        "draft_skill",
        approve=approve,
        interactive=interactive,
        hubId=hub_id,
        manifest=json.dumps(MANIFEST),
        handler=handler,
    )


def set_active(file: Path, *, active: bool) -> None:
    """Do what the settings-page toggle does: merge `active` into the JSON."""
    data = json.loads(file.read_text())
    data["active"] = active
    file.write_text(json.dumps(data))


def test_required_manifest_keys_track_the_vendored_schema(storage: Path) -> None:
    schema = json.loads((FIXTURES / "imported-manifest.schema.json").read_text())
    forced = {"active", "hubId", "imported"}
    [keys] = run(storage, {"op": "required-keys"})
    assert set(keys) == set(schema["required"]) - forced


def test_a_drafted_skill_has_no_loadable_handler(storage: Path) -> None:
    [res] = run(storage, draft_skill())
    skill = storage / "plugins" / "agent-skills" / "hello"
    manifest = json.loads((skill / "plugin.json").read_text())
    assert manifest["active"] is False
    assert manifest["hubId"] == "hello"
    assert not (skill / "handler.js").exists()
    assert (skill / "handler.js.draft").read_text() == HANDLER
    assert res["cards"][0]["payload"]["handler"] == HANDLER


def test_a_skill_is_promoted_only_after_it_is_switched_on(storage: Path) -> None:
    skill = storage / "plugins" / "agent-skills" / "hello"
    run(storage, draft_skill(), {"op": "load"})
    assert not (skill / "handler.js").exists()

    set_active(skill / "plugin.json", active=True)
    run(storage, {"op": "load"})
    assert (skill / "handler.js").read_text() == HANDLER
    assert not (skill / "handler.js.draft").exists()
    assert "strataWorkshop" not in json.loads((skill / "plugin.json").read_text())


def test_a_tampered_draft_is_never_promoted(storage: Path) -> None:
    skill = storage / "plugins" / "agent-skills" / "hello"
    run(storage, draft_skill())
    (skill / "handler.js.draft").write_text("require('child_process')")
    set_active(skill / "plugin.json", active=True)
    run(storage, {"op": "load"})
    assert not (skill / "handler.js").exists()


def test_redrafting_a_live_skill_takes_it_out_of_service(storage: Path) -> None:
    skill = storage / "plugins" / "agent-skills" / "hello"
    run(storage, draft_skill())
    set_active(skill / "plugin.json", active=True)
    run(storage, {"op": "load"})
    assert (skill / "handler.js").exists()

    run(storage, draft_skill(handler=HANDLER + "\n// v2"))
    assert json.loads((skill / "plugin.json").read_text())["active"] is False
    assert not (skill / "handler.js").exists()


@pytest.mark.parametrize(
    "step",
    [
        pytest.param(draft_skill(approve=False), id="denied"),
        pytest.param(draft_skill(interactive=False), id="no-chat-window"),
        pytest.param(draft_skill(hub_id="../escape"), id="path-traversal"),
        pytest.param(draft_skill(hub_id="strata-workshop"), id="self"),
        pytest.param(draft_skill(handler="function ("), id="syntax-error"),
        pytest.param(
            call("draft_skill", hubId="hello", manifest="{}", handler=HANDLER), id="bad-manifest"
        ),
    ],
)
def test_a_refused_skill_draft_writes_nothing(storage: Path, step: dict) -> None:
    [res] = run(storage, step)
    assert not (storage / "plugins" / "agent-skills").exists(), res["text"]


def test_a_syntax_error_is_rejected_without_running_the_code(storage: Path) -> None:
    marker = storage.parent / "ran"
    code = f"require('fs').writeFileSync({json.dumps(str(marker))}, 'x'); function ("
    [res] = run(storage, draft_skill(handler=code))
    assert res["text"].startswith("Rejected: handler does not compile")
    assert res["cards"] == []
    assert not marker.exists()


def test_a_drafted_flow_is_a_start_only_stub_until_switched_on(storage: Path) -> None:
    [res] = run(storage, call("draft_flow", name="Summarise", config=json.dumps(FLOW)))
    flows = storage / "plugins" / "agent-flows"
    [live] = list(flows.glob("*.json"))
    stub = json.loads(live.read_text())
    assert stub["active"] is False
    assert [s["type"] for s in stub["steps"]] == ["start"]
    assert res["cards"][0]["payload"]["config"]["steps"] == FLOW["steps"]

    set_active(live, active=True)
    run(storage, {"op": "load"})
    promoted = json.loads(live.read_text())
    assert promoted["active"] is True
    assert promoted["steps"] == FLOW["steps"]
    assert not live.with_name(live.name + ".draft").exists()


@pytest.mark.parametrize(
    "step",
    [
        pytest.param(
            call("draft_flow", name="x", config=json.dumps(FLOW), uuid="../../x"), id="uuid"
        ),
        pytest.param(
            call("draft_flow", name="x", config=json.dumps({"steps": [{"type": "code"}]})),
            id="unknown-step",
        ),
    ],
)
def test_a_refused_flow_draft_writes_nothing(storage: Path, step: dict) -> None:
    run(storage, step)
    assert not (storage / "plugins" / "agent-flows").exists()


def test_an_mcp_draft_keeps_siblings_and_never_autostarts(storage: Path) -> None:
    config_file = storage / "plugins" / "anythingllm_mcp_servers.json"
    sibling = {"command": "npx", "args": ["x"], "anythingllm": {"autoStart": True}}
    config_file.write_text(json.dumps({"mcpServers": {"sibling": sibling}}))

    run(storage, call("draft_mcp", name="memory", command="npx", args='["-y", "m@1"]'))
    servers = json.loads(config_file.read_text())["mcpServers"]
    assert servers["sibling"] == sibling
    assert servers["memory"]["anythingllm"] == {"autoStart": False}

    run(storage, call("draft_mcp", name="sibling", command="npx", args='["y"]'))
    redrafted = json.loads(config_file.read_text())["mcpServers"]["sibling"]
    assert redrafted["anythingllm"] == {"autoStart": False}


def test_workspace_create_then_update(storage: Path) -> None:
    [created, updated, listed] = run(
        storage,
        call("workspace", name="Research", systemPrompt="Be terse."),
        call("workspace", slug="research", systemPrompt="Be thorough."),
        call("list", kind="workspace"),
    )
    assert created["cards"][0]["payload"]["openAiPrompt"] == "Be terse."
    assert "Updated workspace research" in updated["text"]
    assert json.loads(listed["text"]) == {"workspaces": [{"slug": "research", "name": "Research"}]}


def test_there_is_no_way_to_activate_from_chat(storage: Path) -> None:
    [res] = run(storage, call("activate", hubId="hello"))
    assert res["text"].startswith('Unknown action "activate"')
