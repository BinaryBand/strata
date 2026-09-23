// Input validation for workshop drafts. Every check here runs before the
// approval card is shown, so the user is never asked to approve something the
// workshop would refuse to write. Nothing in this module executes drafted code.
const vm = require("vm");

const SELF_HUB_ID = "strata-workshop";
// Strata's enable_anythingllm_filestore runbook owns this MCP entry.
const PROTECTED_MCP = new Set(["filestore"]);
const HUB_ID = /^[a-z0-9][a-z0-9-]{1,48}$/;
const MCP_NAME = /^[A-Za-z0-9_-]{1,64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// AnythingLLM 1.16's FLOW_TYPES. saveFlow refuses any other step type, and so
// does the workshop, before the user is asked to review it.
const FLOW_STEP_TYPES = new Set(["start", "apiCall", "llmInstruction", "webScraping"]);
const PARAM_TYPES = new Set(["string", "number", "boolean"]);
// The manifest keys imported-manifest.schema.json requires, minus the three the
// workshop forces itself (active, hubId, imported).
const MANIFEST_REQUIRED = ["name", "schema", "version", "description", "entrypoint"];
const MAX_HANDLER_BYTES = 200_000;

class DraftError extends Error {}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseJson(label, value) {
  if (isPlainObject(value) || Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim())
    throw new DraftError(`${label} is required, as a JSON string.`);
  try {
    return JSON.parse(value);
  } catch (e) {
    throw new DraftError(`${label} is not valid JSON: ${e.message}`);
  }
}

function requireString(label, value, max = 255) {
  if (typeof value !== "string" || !value.trim())
    throw new DraftError(`${label} is required and must be a non-empty string.`);
  if (value.length > max) throw new DraftError(`${label} is longer than ${max} characters.`);
  return value;
}

function hubId(value) {
  requireString("hubId", value, 49);
  if (!HUB_ID.test(value))
    throw new DraftError("hubId must be lowercase letters, digits and dashes, 2-49 characters.");
  if (value === SELF_HUB_ID)
    throw new DraftError("strata-workshop is managed by strata and cannot be redrafted from chat.");
  return value;
}

function manifest(value) {
  const parsed = parseJson("manifest", value);
  if (!isPlainObject(parsed)) throw new DraftError("manifest must be a JSON object.");
  for (const key of MANIFEST_REQUIRED)
    if (!(key in parsed)) throw new DraftError(`manifest is missing "${key}".`);
  requireString("manifest.name", parsed.name);
  requireString("manifest.description", parsed.description, 2000);
  requireString("manifest.version", parsed.version, 64);
  if (parsed.schema !== "skill-1.0.0")
    throw new DraftError('manifest.schema must be "skill-1.0.0".');
  const entry = parsed.entrypoint;
  if (!isPlainObject(entry) || entry.file !== "handler.js" || !isPlainObject(entry.params))
    throw new DraftError('manifest.entrypoint must be {"file": "handler.js", "params": {...}}.');
  for (const [name, param] of Object.entries(entry.params)) {
    if (!isPlainObject(param) || typeof param.description !== "string" || !PARAM_TYPES.has(param.type))
      throw new DraftError(
        `manifest.entrypoint.params.${name} needs a description and a type of string, number or boolean.`
      );
  }
  return parsed;
}

// Compiles the handler inside the same wrapper Node gives a CommonJS module,
// so a top-level `return` is legal, and never runs it: vm.Script only parses.
function handlerCode(value) {
  requireString("handler", value, MAX_HANDLER_BYTES);
  try {
    new vm.Script(
      `(function (exports, require, module, __filename, __dirname) {${value}\n})`,
      { filename: "handler.js" }
    );
  } catch (e) {
    throw new DraftError(`handler does not compile: ${e.message}`);
  }
  return value;
}

function flow(nameValue, configValue, uuidValue) {
  const name = requireString("name", nameValue);
  const config = parseJson("config", configValue);
  if (!isPlainObject(config) || !Array.isArray(config.steps) || config.steps.length === 0)
    throw new DraftError("config must be a JSON object with a non-empty steps array.");
  for (const [i, step] of config.steps.entries()) {
    if (!isPlainObject(step) || !FLOW_STEP_TYPES.has(step.type))
      throw new DraftError(
        `config.steps[${i}].type must be one of: ${[...FLOW_STEP_TYPES].join(", ")}.`
      );
    if (step.config !== undefined && !isPlainObject(step.config))
      throw new DraftError(`config.steps[${i}].config must be an object.`);
  }
  let uuid = null;
  if (uuidValue !== undefined && uuidValue !== null && uuidValue !== "") {
    if (typeof uuidValue !== "string" || !UUID.test(uuidValue))
      throw new DraftError("uuid must be a lowercase UUID, as `list` reports it.");
    uuid = uuidValue;
  }
  return { name, config, uuid };
}

function mcp(nameValue, commandValue, argsValue, envValue) {
  const name = requireString("name", nameValue, 64);
  if (!MCP_NAME.test(name))
    throw new DraftError("name must be letters, digits, dashes or underscores, up to 64.");
  if (PROTECTED_MCP.has(name))
    throw new DraftError(`${name} is managed by strata and cannot be redrafted from chat.`);
  const command = requireString("command", commandValue, 1000);
  const args = argsValue === undefined || argsValue === "" ? [] : parseJson("args", argsValue);
  if (!Array.isArray(args) || !args.every((a) => typeof a === "string"))
    throw new DraftError("args must be a JSON array of strings.");
  const env = envValue === undefined || envValue === "" ? {} : parseJson("env", envValue);
  if (!isPlainObject(env) || !Object.values(env).every((v) => typeof v === "string"))
    throw new DraftError("env must be a JSON object of string values.");
  return { name, command, args, env };
}

module.exports = {
  DraftError,
  SELF_HUB_ID,
  FLOW_STEP_TYPES,
  MANIFEST_REQUIRED,
  isPlainObject,
  requireString,
  hubId,
  manifest,
  handlerCode,
  flow,
  mcp,
};
