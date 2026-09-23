"""A stand-in for the research skill's research.py: records each call and obeys it.

`init` creates the run directory, `check` fails when the file contains FAIL,
`search` exits 4 when the query is "refused", and every call appends its argv
and search engine to calls.jsonl next to this script.
"""

import json
import os
import sys
from pathlib import Path

here = Path(__file__).parent
args = sys.argv[1:]
with (here / "calls.jsonl").open("a") as log:
    log.write(json.dumps({"argv": args, "engine": os.environ.get("RESEARCH_SEARCH_ENGINE")}) + "\n")
command, run = args[0], Path(args[args.index("--run") + 1])
if command == "init":
    run.mkdir(parents=True)
    sys.stdout.write(f"run ready at {run}" + "\n")
elif command == "check":
    text = Path(args[-1]).read_text()
    sys.stdout.write(("problems: FAIL found" if "FAIL" in text else "check passed") + "\n")
    sys.exit(1 if "FAIL" in text else 0)
elif command == "search" and args[-1] == "refused":
    sys.stdout.write("search s1 failed: DuckDuckGo refused the search as a bot" + "\n")
    sys.exit(4)
else:
    sys.stdout.write(f"{command} ok" + "\n")
