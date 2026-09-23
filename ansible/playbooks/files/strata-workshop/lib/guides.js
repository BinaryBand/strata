// Authoring specs the chat model reads before drafting, so a valid draft needs
// no terminal and no outside documentation.
const GUIDES = {
  skill: `A custom agent skill is two files. Call draft_skill with:
- hubId: lowercase letters, digits and dashes (e.g. "utc-clock").
- manifest: a JSON string of plugin.json, e.g.
  {"name":"UTC clock","schema":"skill-1.0.0","version":"1.0.0",
   "description":"Returns the current UTC time.",
   "entrypoint":{"file":"handler.js","params":{
     "format":{"type":"string","description":"iso or unix"}}},
   "examples":[{"prompt":"what time is it in UTC?","call":"{\\"format\\":\\"iso\\"}"}]}
  Param types are string, number or boolean only. Optional keys: author, license,
  setup_args (values the user fills in on the settings page, read as
  this.runtimeArgs.<name>). active, hubId and imported are set by the workshop.
- handler: the JavaScript source of handler.js, a CommonJS module:
  module.exports.runtime = {
    handler: async function ({ format }) {
      this.introspect("Reading the clock");   // status line in the chat
      const now = new Date();
      return format === "unix" ? String(Math.floor(now / 1000)) : now.toISOString();
    },
  };
  The handler must return a string. It runs inside the AnythingLLM server (Node 18)
  with full access to it, so keep it small and use only Node built-ins or fetch.
  Destructive steps should call: const ok = await this.requestToolApproval({
  description: "...", payload: {...} }); and stop unless ok.approved.
The draft stays off, and its code stays unloadable, until the user switches it on
under Settings > Agent Skills. It works from the next chat after that. Redrafting an
existing skill switches it off again.`,

  flow: `An Agent Flow is a list of steps. Call draft_flow with:
- name: shown in the UI and used as the tool name.
- config: a JSON string, e.g.
  {"description":"Summarise a web page",
   "steps":[
    {"type":"start","config":{"variables":[{"name":"url","type":"required","description":"Page URL"}]}},
    {"type":"webScraping","config":{"url":"\${url}","resultVariable":"page"}},
    {"type":"llmInstruction","config":{"instruction":"Summarise in 5 bullets: \${page}","resultVariable":"summary"}}]}
  Step types: start (variables), apiCall (url, method, headers[{key,value}], bodyType
  json|form, body, responseVariable, directOutput), llmInstruction (instruction,
  resultVariable), webScraping (url, resultVariable, directOutput). Reference a
  variable as \${name}.
- uuid (optional): an existing flow's uuid from list, to redraft it.
The flow stays a do-nothing stub until the user switches it on under Settings >
Agent Flows, and works from the next chat after that.`,

  mcp: `An MCP server is a command AnythingLLM launches. Call draft_mcp with:
- name: letters, digits, dashes or underscores.
- command: e.g. "npx".
- args: a JSON array of strings, e.g. ["-y","@modelcontextprotocol/server-memory@2026"].
  Pin the package to a version series.
- env (optional): a JSON object of string values.
It is registered with autoStart off: the user starts it from Settings > Agent Skills >
MCP Servers. The name "filestore" belongs to strata and is refused.`,

  workspace: `Call workspace with:
- name: to create a workspace, or rename one given by slug.
- systemPrompt: the workspace's system prompt.
- slug (optional): an existing workspace's slug from list, to update it.
This takes effect as soon as it is approved.`,
};

function guide(kind) {
  if (kind && GUIDES[kind]) return GUIDES[kind];
  return `Pass kind = one of: ${Object.keys(GUIDES).join(", ")}.\n\n${Object.entries(GUIDES)
    .map(([k, v]) => `## ${k}\n${v}`)
    .join("\n\n")}`;
}

module.exports = { guide };
