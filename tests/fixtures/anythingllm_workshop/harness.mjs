// Drives the strata-workshop skill outside AnythingLLM for
// tests/test_anythingllm_workshop.py. STORAGE_DIR comes from the environment;
// argv[2] is the skill directory and argv[3] a JSON list of steps. Prints one
// JSON result per step.
import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";

const [skillDir, stepsFile] = process.argv.slice(2);
const require = createRequire(import.meta.url);
const handlerPath = path.join(skillDir, "handler.js");
console.log = (...a) => process.stderr.write(`${a.join(" ")}\n`);

function load() {
  for (const key of Object.keys(require.cache))
    if (key.startsWith(path.resolve(skillDir))) delete require.cache[key];
  return require(handlerPath);
}

let skill = load();
const results = [];
for (const step of JSON.parse(fs.readFileSync(stepsFile, "utf8"))) {
  if (step.op === "load") {
    skill = load();
    results.push({ op: "load" });
  } else if (step.op === "required-keys") {
    results.push(require(path.join(skillDir, "lib", "validate.js")).MANIFEST_REQUIRED);
  } else if (step.op === "call") {
    const cards = [];
    const aibitat = {};
    if (step.interactive !== false) aibitat.requestUserClarification = async () => ({});
    const context = {
      super: aibitat,
      introspect: () => {},
      logger: () => {},
      requestToolApproval: async (card) => {
        cards.push(card);
        return { approved: step.approve !== false, message: "denied by test" };
      },
    };
    const text = await skill.runtime.handler.call(context, step.args);
    results.push({ text, cards });
  }
}
process.stdout.write(JSON.stringify(results));
