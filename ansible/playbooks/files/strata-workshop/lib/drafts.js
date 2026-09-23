// Held-back drafts for skills, flows and MCP servers, and the sweep that
// promotes them once the user has switched them on in the settings UI.
//
// AnythingLLM 1.16 loads a skill or flow named in a scheduled job's tool list
// without checking `active`, so an inactive draft is not enough. A draft is
// stored in a form AnythingLLM cannot execute: a skill's code as
// handler.js.draft (no handler.js, so the loader skips it), a flow as a
// start-only stub beside <uuid>.json.draft (which the flow loader never reads).
// Each carries a `strataWorkshop.pending` sha256 of the approved draft bytes.
// Only `active: true` -- a click in the settings UI, which the agent has no tool
// for -- lets the sweep move the draft into place.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const validate = require("./validate");

const MARK = "strataWorkshop";

function roots(storageDir) {
  const plugins = path.join(storageDir, "plugins");
  return {
    skills: path.join(plugins, "agent-skills"),
    flows: path.join(plugins, "agent-flows"),
    mcpConfig: path.join(plugins, "anythingllm_mcp_servers.json"),
  };
}

function sha256(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

// Resolves `parts` under `root` and refuses anything that lands outside it.
function inside(root, ...parts) {
  const base = path.resolve(root);
  const target = path.resolve(base, ...parts);
  if (!target.startsWith(base + path.sep))
    throw new validate.DraftError(`Refusing a path outside ${base}.`);
  return target;
}

function writeAtomic(file, text) {
  const tmp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

function readJson(file, fallback) {
  if (!fs.existsSync(file)) return fallback;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function serialize(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

// ---- skills -----------------------------------------------------------------

function prepareSkill(storageDir, input) {
  const hubId = validate.hubId(input.hubId);
  const manifest = validate.manifest(input.manifest);
  const code = validate.handlerCode(input.handler);
  const { [MARK]: _ignored, ...rest } = manifest;
  const final = {
    ...rest,
    hubId,
    active: false,
    imported: true,
    [MARK]: { pending: sha256(code) },
  };
  const dir = inside(roots(storageDir).skills, hubId);
  return {
    summary: `Draft skill "${final.name}" (${hubId}), held back until switched on`,
    payload: { hubId, manifest: rest, handler: code },
    commit() {
      fs.mkdirSync(dir, { recursive: true });
      // Deactivate first, then take any live code out of service, then write
      // the draft: an interrupted commit leaves the skill off, never live.
      writeAtomic(path.join(dir, "plugin.json"), serialize(final));
      fs.rmSync(path.join(dir, "handler.js"), { force: true });
      writeAtomic(path.join(dir, "handler.js.draft"), code);
      return `Drafted skill ${hubId}. It stays off until you switch it on under Settings > Agent Skills; it then works from the next chat.`;
    },
  };
}

// ---- flows ------------------------------------------------------------------

function prepareFlow(storageDir, input) {
  const { name, config, uuid: given } = validate.flow(input.name, input.config, input.uuid);
  const uuid = given || crypto.randomUUID();
  const { [MARK]: _ignored, active: _active, ...rest } = config;
  const draftText = serialize({ ...rest, name, active: false });
  const starts = rest.steps.filter((s) => s.type === "start");
  const stub = {
    name,
    description: rest.description || "",
    active: false,
    steps: starts.length ? starts : [{ type: "start", config: { variables: [] } }],
    [MARK]: { pending: sha256(draftText) },
  };
  const root = roots(storageDir).flows;
  const live = inside(root, `${uuid}.json`);
  const draft = inside(root, `${uuid}.json.draft`);
  return {
    summary: `Draft flow "${name}" (${uuid}), held back until switched on`,
    payload: { uuid, name, config: rest },
    commit() {
      fs.mkdirSync(root, { recursive: true });
      writeAtomic(live, serialize(stub));
      writeAtomic(draft, draftText);
      return `Drafted flow ${name} (${uuid}). It stays a do-nothing stub until you switch it on under Settings > Agent Flows; it then works from the next chat.`;
    },
  };
}

// ---- MCP servers ------------------------------------------------------------

function readMcpConfig(file) {
  const config = readJson(file, { mcpServers: {} });
  if (!validate.isPlainObject(config) || !validate.isPlainObject(config.mcpServers ?? {}))
    throw new validate.DraftError(`${file} is not a JSON object with an mcpServers object.`);
  return config;
}

function prepareMcp(storageDir, input) {
  const { name, command, args, env } = validate.mcp(input.name, input.command, input.args, input.env);
  const entry = { command, args, env, anythingllm: { autoStart: false } };
  const file = roots(storageDir).mcpConfig;
  readMcpConfig(file); // fail before the card, not after it
  return {
    summary: `Register MCP server "${name}" with autoStart off`,
    payload: { name, ...entry },
    commit() {
      const config = readMcpConfig(file);
      config.mcpServers = { ...(config.mcpServers ?? {}), [name]: entry };
      fs.mkdirSync(path.dirname(file), { recursive: true });
      writeAtomic(file, serialize(config));
      return `Registered MCP server ${name} with autoStart off. Start it from Settings > Agent Skills > MCP Servers (refresh the list first).`;
    },
  };
}

// ---- promotion --------------------------------------------------------------

function promoteSkill(dir) {
  const manifestFile = path.join(dir, "plugin.json");
  const draftFile = path.join(dir, "handler.js.draft");
  const manifest = readJson(manifestFile, null);
  const pending = manifest?.[MARK]?.pending;
  if (!pending || manifest.active !== true || !fs.existsSync(draftFile)) return null;
  const code = fs.readFileSync(draftFile, "utf8");
  if (sha256(code) !== pending) return "mismatch";
  writeAtomic(path.join(dir, "handler.js"), code);
  fs.rmSync(draftFile);
  const { [MARK]: _done, ...rest } = manifest;
  writeAtomic(manifestFile, serialize(rest));
  return "promoted";
}

function promoteFlow(live) {
  const draftFile = `${live}.draft`;
  const stub = readJson(live, null);
  const pending = stub?.[MARK]?.pending;
  if (!pending || stub.active !== true || !fs.existsSync(draftFile)) return null;
  const text = fs.readFileSync(draftFile, "utf8");
  if (sha256(text) !== pending) return "mismatch";
  writeAtomic(live, serialize({ ...JSON.parse(text), active: true }));
  fs.rmSync(draftFile);
  return "promoted";
}

// Runs at module load. Never throws: a broken entry must not stop the
// workshop, or the chat, from loading.
function sweep(storageDir) {
  const { skills, flows } = roots(storageDir);
  const results = [];
  const each = (root, filter, promote) => {
    if (!fs.existsSync(root)) return;
    for (const name of fs.readdirSync(root).filter(filter)) {
      try {
        const outcome = promote(path.join(root, name));
        if (outcome) results.push({ name, outcome });
      } catch (e) {
        results.push({ name, outcome: `error: ${e.message}` });
      }
    }
  };
  each(skills, (n) => n !== validate.SELF_HUB_ID, promoteSkill);
  each(flows, (n) => n.endsWith(".json"), promoteFlow);
  return results;
}

// ---- listing ----------------------------------------------------------------

function state(item, hasDraft, hasLive) {
  const pending = item?.[MARK]?.pending;
  if (pending && hasDraft) return item.active === true ? "switched on, promotes next chat" : "draft, off";
  if (pending) return "draft missing";
  return hasLive ? (item?.active === false ? "off" : "on") : "no handler";
}

function list(storageDir) {
  const { skills, flows, mcpConfig } = roots(storageDir);
  const out = { skills: [], flows: [], mcp: [] };
  if (fs.existsSync(skills))
    for (const hubId of fs.readdirSync(skills)) {
      const dir = path.join(skills, hubId);
      const manifest = readJson(path.join(dir, "plugin.json"), null);
      if (!manifest) continue;
      const hasDraft = fs.existsSync(path.join(dir, "handler.js.draft"));
      const hasLive = fs.existsSync(path.join(dir, "handler.js"));
      out.skills.push({ hubId, name: manifest.name, state: state(manifest, hasDraft, hasLive) });
    }
  if (fs.existsSync(flows))
    for (const file of fs.readdirSync(flows).filter((f) => f.endsWith(".json"))) {
      const flow = readJson(path.join(flows, file), null);
      if (!flow) continue;
      const hasDraft = fs.existsSync(path.join(flows, `${file}.draft`));
      out.flows.push({ uuid: file.slice(0, -5), name: flow.name, state: state(flow, hasDraft, true) });
    }
  const config = readJson(mcpConfig, { mcpServers: {} });
  for (const [name, server] of Object.entries(config.mcpServers ?? {}))
    out.mcp.push({ name, autoStart: server?.anythingllm?.autoStart !== false });
  return out;
}

module.exports = { MARK, prepareSkill, prepareFlow, prepareMcp, sweep, list };
