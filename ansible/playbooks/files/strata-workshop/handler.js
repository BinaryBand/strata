// strata-workshop: draft AnythingLLM customizations from the chat window.
// Deployed and owned by strata's services.enable_anythingllm_workshop runbook;
// edit it in the strata repository, not in place.
//
// Safety model, in order of what it relies on:
// 1. Every write is refused outside a live chat window. A scheduled job's
//    runner auto-approves tool approval requests, so the presence of
//    requestToolApproval proves nothing; only the chat window's websocket
//    plugin defines requestUserClarification.
// 2. Every write shows an approval card carrying the full content.
// 3. Skills and flows are written held back (see lib/drafts.js) and only
//    promoted once the user switches them on in the settings UI.
const drafts = require("./lib/drafts");
const { guide } = require("./lib/guides");
const { DraftError } = require("./lib/validate");
const { prepareWorkspace, listWorkspaces } = require("./lib/workspaces");

const STORAGE_DIR = process.env.STORAGE_DIR;

// AnythingLLM re-requires this file for every agent session, so this runs each
// time: anything the user switched on since the last session is promoted now.
if (STORAGE_DIR) {
  for (const { name, outcome } of drafts.sweep(STORAGE_DIR))
    console.log(`[strata-workshop] ${name}: ${outcome}`);
}

const PREPARE = {
  draft_skill: (args) => drafts.prepareSkill(STORAGE_DIR, args),
  draft_flow: (args) => drafts.prepareFlow(STORAGE_DIR, args),
  draft_mcp: (args) => drafts.prepareMcp(STORAGE_DIR, args),
  workspace: (args) => prepareWorkspace(STORAGE_DIR, args),
};

async function listAll(kind) {
  const all = drafts.list(STORAGE_DIR);
  if (!kind || kind === "workspace") all.workspaces = await listWorkspaces(STORAGE_DIR);
  const pick = { skill: "skills", flow: "flows", mcp: "mcp", workspace: "workspaces" }[kind];
  return JSON.stringify(pick ? { [pick]: all[pick] } : all, null, 2);
}

module.exports.runtime = {
  handler: async function (args = {}) {
    const { action } = args;
    try {
      if (!STORAGE_DIR) return "STORAGE_DIR is not set; the workshop cannot find AnythingLLM's storage.";
      if (action === "guide") return guide(args.kind);
      if (action === "list") return await listAll(args.kind);
      if (!PREPARE[action])
        return `Unknown action "${action}". Actions: guide, list, draft_skill, draft_flow, draft_mcp, workspace. Switching things on or deleting them is done by the user in the settings UI.`;

      if (typeof this.super?.requestUserClarification !== "function")
        return "The workshop only writes from a live chat window, where the user can review the approval card. It does not run in scheduled jobs or API calls.";

      const plan = await PREPARE[action](args);
      this.introspect(`${plan.summary} -- waiting for approval`);
      const approval = await this.requestToolApproval({
        description: plan.summary,
        payload: plan.payload,
      });
      if (!approval?.approved) return `Nothing was written: ${approval?.message ?? "not approved"}`;
      return await plan.commit();
    } catch (e) {
      if (e instanceof DraftError) return `Rejected: ${e.message}`;
      this.logger?.(`[strata-workshop] ${action} failed: ${e.stack || e}`);
      return `The workshop failed: ${e.message}`;
    }
  },
};
