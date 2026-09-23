// Drives the research skill's handler outside AnythingLLM for
// tests/test_anythingllm_research.py. STORAGE_DIR comes from the environment;
// argv[2] is the skill directory and argv[3] a JSON list of handler arguments.
// Prints one result string per call as a JSON list.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const [skillDir, callsFile] = process.argv.slice(2);
const require = createRequire(import.meta.url);
const skill = require(path.join(skillDir, "handler.js"));
const context = { introspect: () => {}, logger: () => {} };
const results = [];
for (const args of JSON.parse(fs.readFileSync(callsFile, "utf8")))
  results.push(await skill.runtime.handler.call(context, args));
process.stdout.write(JSON.stringify(results));
