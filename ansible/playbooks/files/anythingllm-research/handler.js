// research: the research skill's engine (research.py), driven from AnythingLLM.
// Deployed and owned by strata's services.enable_anythingllm_research runbook;
// edit it in the strata repository. The engine, SKILL.md and contracts are
// copied from the operator's research skill into engine/ on every run.
//
// Every run lives in <storage>/research-runs/<slug>/, outside the File System
// tools' root, so the evidence -- fetched pages, the ledger, the budget -- can
// only change through research.py. The agent writes briefs, handbacks and the
// report through this tool's `write` action, which reports the saved size and
// hash so a write that silently failed cannot pass unnoticed. A run is finished
// only by `finish`, which runs `check` itself and publishes the report only if
// it passes.
const { execFile } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const ENGINE = path.join(__dirname, "engine");
const SLUG = /^[a-z0-9][a-z0-9-]{1,59}$/;
// The only files the agent may write or read in a run.
const RUN_FILE = /^(briefs\/\d{2}\.md|handbacks\/\d{2}\.json|reports\/final\.md)$/;
const MAX_FILE_CHARS = 200_000;
const MAX_PARTS = 20;
const MAX_OUTPUT_CHARS = 16_000;
const TIMEOUT_MS = 240_000;
const EXIT_MEANING = {
  "-1": "the engine timed out or could not start",
  0: "done",
  1: "check listed problems, or quote found no match",
  2: "bad arguments, or no run by that name",
  3: "the budget is spent: stop searching and fetching and write up what you have",
  4: "the search or fetch failed: that URL is not citable",
};

const PREFACE = `You are running the research skill below inside AnythingLLM. Read it as follows:
- Every "research.py SUBCOMMAND" command is a call to this research tool with action set to that subcommand. Pass run (the run's slug, 2-60 lowercase letters, digits and dashes), not a path. RUN in the text means that run.
- Never write run files with the File System tools, and never use the editor or read_files: write each brief, handback and the final report with action "write" (run, file, content), and read them back with action "read". file is briefs/NN.md, handbacks/NN.json or reports/final.md. For a file over about 6000 characters, send it in parts: part 1..N with the same parts=N; the file is saved when the last part arrives.
- "write" answers with the saved size and sha256. If it does not say "saved", the file was not written: send it again.
- There are no sub-agents: run each brief yourself, one after another, following the sweep contract.
- Search results come from DuckDuckGo and cost nothing. PDFs cannot be fetched on this server; prefer an arXiv abstract page.
- The run is finished only when action "finish" says "check: passed". Then reply with the verdict paragraph it returns and the report path, nothing else. Never write a report in the chat instead.`;

function runDir(storage, slug) {
  if (typeof slug !== "string" || !SLUG.test(slug))
    throw new UsageError("run must be 2-60 lowercase letters, digits and dashes, such as llm-judges.");
  return path.join(storage, "research-runs", slug);
}

function runFile(run, file) {
  if (typeof file !== "string" || !RUN_FILE.test(file))
    throw new UsageError("file must be briefs/NN.md, handbacks/NN.json or reports/final.md.");
  return path.join(run, file);
}

class UsageError extends Error {}

function engine(args) {
  return new Promise((resolve) => {
    execFile(
      "python3",
      [path.join(ENGINE, "research.py"), ...args],
      {
        cwd: ENGINE,
        timeout: TIMEOUT_MS,
        maxBuffer: 8 * 1024 * 1024,
        env: { PATH: process.env.PATH, RESEARCH_SEARCH_ENGINE: "duckduckgo", PYTHONDONTWRITEBYTECODE: "1" },
      },
      (error, stdout, stderr) => {
        const code = error ? (typeof error.code === "number" ? error.code : -1) : 0;
        resolve({ code, out: `${stdout}${stderr ? `\n${stderr}` : ""}`.trim() });
      }
    );
  });
}

function report({ code, out }) {
  const body = out.length > MAX_OUTPUT_CHARS ? `${out.slice(0, MAX_OUTPUT_CHARS)}\n...(output truncated)` : out;
  return `exit ${code} (${EXIT_MEANING[code] || "unexpected"})\n${body}`;
}

function guide() {
  const read = (p) => fs.readFileSync(path.join(ENGINE, p), "utf8");
  return [
    PREFACE,
    "===== SKILL.md =====",
    read("SKILL.md"),
    "===== contracts/sweep.md =====",
    read("contracts/sweep.md"),
    "===== contracts/brief.md (template) =====",
    read("contracts/brief.md"),
    "===== contracts/final.md (template) =====",
    read("contracts/final.md"),
  ].join("\n\n");
}

function sha256(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

function write(run, args) {
  if (!fs.existsSync(run)) throw new UsageError("No run by that name: call init first.");
  const target = runFile(run, args.file);
  if (typeof args.content !== "string" || !args.content.length)
    throw new UsageError("content is required.");
  const parts = Number(args.parts || 1);
  const part = Number(args.part || 1);
  if (!Number.isInteger(parts) || parts < 1 || parts > MAX_PARTS || !Number.isInteger(part) || part < 1 || part > parts)
    throw new UsageError(`part and parts must be whole numbers with 1 <= part <= parts <= ${MAX_PARTS}.`);

  const staging = path.join(run, ".parts", args.file.replace("/", "__"));
  let text = args.content;
  if (parts > 1) {
    fs.mkdirSync(staging, { recursive: true });
    fs.writeFileSync(path.join(staging, `${part}-of-${parts}`), args.content);
    const have = fs.readdirSync(staging).filter((n) => n.endsWith(`-of-${parts}`));
    if (have.length < parts) return `part ${part} of ${parts} received for ${args.file}; send the rest.`;
    text = Array.from({ length: parts }, (_, i) => fs.readFileSync(path.join(staging, `${i + 1}-of-${parts}`), "utf8")).join("");
  }
  if (text.length > MAX_FILE_CHARS) throw new UsageError(`the file is over ${MAX_FILE_CHARS} characters.`);
  if (args.file.endsWith(".json")) {
    try {
      JSON.parse(text);
    } catch (e) {
      if (parts > 1) fs.rmSync(staging, { recursive: true, force: true });
      throw new UsageError(`${args.file} is not valid JSON (${e.message}); nothing was saved.`);
    }
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, target);
  if (parts > 1) fs.rmSync(staging, { recursive: true, force: true });
  return `saved ${args.file}: ${Buffer.byteLength(text, "utf8")} bytes, sha256 ${sha256(text)}`;
}

function read(run, args) {
  const target = runFile(run, args.file);
  if (!fs.existsSync(target)) return `${args.file} does not exist in this run.`;
  return fs.readFileSync(target, "utf8");
}

async function finish(storage, slug, run) {
  const final = path.join(run, "reports", "final.md");
  if (!fs.existsSync(final)) return "reports/final.md does not exist: write it first.";
  const result = await engine(["check", "--run", run, final]);
  if (result.code !== 0) return `Not finished: check failed. Fix every problem and call finish again.\n${report(result)}`;
  const text = fs.readFileSync(final, "utf8");
  const outDir = path.join(storage, "anythingllm-fs", "research");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, `${slug}.md`), text);
  const verdict = (text.split(/^## +Verdict\s*$/m)[1] || "").split(/^## /m)[0].trim();
  return `check: passed\nReport: research/${slug}.md\n\n${verdict}`;
}

module.exports.runtime = {
  handler: async function (args = {}) {
    const storage = process.env.STORAGE_DIR;
    const action = args.action;
    try {
      if (!storage) return "STORAGE_DIR is not set; the research tool cannot find AnythingLLM's storage.";
      if (action === "guide") return guide();
      const run = runDir(storage, args.run);
      const flags = [];
      if (args.brief) flags.push("--brief", String(args.brief));
      switch (action) {
        case "init":
          fs.mkdirSync(path.dirname(run), { recursive: true });
          return report(
            await engine(["init", "--run", run, "--max-searches", String(args.max_searches || 24), "--max-fetches", String(args.max_fetches || 60)])
          );
        case "search":
          this.introspect(`Searching: ${args.query}`);
          return report(await engine(["search", "--run", run, ...flags, ...(args.counter ? ["--counter"] : []), String(args.query || "")]));
        case "fetch":
          this.introspect(`Fetching ${args.url}`);
          return report(await engine(["fetch", "--run", run, ...flags, String(args.url || "")]));
        case "quote":
          return report(await engine(["quote", "--run", run, String(args.url || ""), String(args.text || "")]));
        case "status":
          return report(await engine(["status", "--run", run]));
        case "check":
          return report(await engine(["check", "--run", run, runFile(run, args.file)]));
        case "write":
          return write(run, args);
        case "read":
          return read(run, args);
        case "finish":
          return await finish(storage, args.run, run);
        default:
          return `Unknown action "${action}". Actions: guide, init, search, fetch, quote, status, write, read, check, finish. Call guide first.`;
      }
    } catch (e) {
      if (e instanceof UsageError) return `Rejected: ${e.message}`;
      this.logger?.(`[research] ${action} failed: ${e.stack || e}`);
      return `The research tool failed: ${e.message}`;
    }
  },
};
