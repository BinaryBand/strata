// Workspace creation and system-prompt edits, through AnythingLLM's own
// Workspace model so its validations and defaults apply. A prompt runs no code,
// so there is no hold-back here: the approval card is the gate.
const path = require("path");
const validate = require("./validate");

const SLUG = /^[a-z0-9][a-z0-9-]{0,254}$/;
const MAX_PROMPT = 20_000;

// The server root is the storage directory's parent (/app/server in the image),
// so the model is found wherever the image puts the server.
function workspaceModel(storageDir) {
  return require(path.join(path.dirname(storageDir), "models", "workspace")).Workspace;
}

async function prepareWorkspace(storageDir, input) {
  const Workspace = workspaceModel(storageDir);
  const updates = {};
  if (input.name !== undefined && input.name !== "")
    updates.name = validate.requireString("name", input.name);
  if (input.systemPrompt !== undefined && input.systemPrompt !== "")
    updates.openAiPrompt = validate.requireString("systemPrompt", input.systemPrompt, MAX_PROMPT);
  if (!Object.keys(updates).length)
    throw new validate.DraftError("Give a name, a systemPrompt, or both.");

  let existing = null;
  if (input.slug !== undefined && input.slug !== "") {
    if (typeof input.slug !== "string" || !SLUG.test(input.slug))
      throw new validate.DraftError("slug must be a workspace slug as `list` reports it.");
    existing = await Workspace.get({ slug: input.slug });
    if (!existing) throw new validate.DraftError(`No workspace has the slug ${input.slug}.`);
  } else if (!updates.name) {
    throw new validate.DraftError("A new workspace needs a name.");
  }

  const payload = { workspace: existing ? existing.slug : "(new)", ...updates };
  return {
    summary: existing ? `Update workspace ${existing.slug}` : `Create workspace "${updates.name}"`,
    payload,
    async commit() {
      const { workspace, message } = existing
        ? await Workspace.update(existing.id, updates)
        : await Workspace.new(updates.name, null, updates);
      if (!workspace) throw new validate.DraftError(`AnythingLLM refused: ${message}`);
      return existing
        ? `Updated workspace ${existing.slug}.`
        : `Created workspace ${workspace.slug}. Reload the page to see it in the sidebar.`;
    },
  };
}

async function listWorkspaces(storageDir) {
  const rows = await workspaceModel(storageDir).where({});
  return rows.map((w) => ({ slug: w.slug, name: w.name }));
}

module.exports = { prepareWorkspace, listWorkspaces };
