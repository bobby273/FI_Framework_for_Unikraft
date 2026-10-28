#!/usr/bin/env python3
'''
checks the validity of a data set
usage:  python3 verifica.py results/prova.jsonl [12]
'''

import json, sys, os, collections

path = sys.argv[1]
expected = int(sys.argv[2]) if len(sys.argv) > 2 else None

if not os.path.exists(path):
    print(f"{path} does not exist: the runner produced no results.")
    print("Look at the runner's traceback, or the logs in <app_dir>/logs/.")
    sys.exit(2)

rows, broken = [], 0
with open(path) as f:
    for n, line in enumerate(f, 1):
        try:
            rows.append(json.loads(line))
        except ValueError:
            broken += 1
            print(f"  line {n} unreadable (truncated?)")

print(f"valid rows: {len(rows)}" + (f" / {expected} expected" if expected else ""))
if broken:
    print(f"broken rows: {broken}")

problems = []
if expected is not None and len(rows) != expected:
    problems.append(f"row count {len(rows)} instead of {expected}")

fields = ["id", "round", "kind", "oracle", "outcome", "ready_ms",
          "duration_s", "qemu_exit", "timed_out", "fault_fired"]
for r in rows:
    missing = [c for c in fields if c not in r]
    if missing:
        problems.append(f"{r.get('id','?')}: missing fields {missing}")
        break

# assessing if the fault was fired
for r in rows:
    if r.get("kind") == "injected" and not r.get("fault_fired"):
        problems.append(f"{r.get('id')} r{r.get('round')}: fault_fired FALSE "
                        f"-> site not armed, or wrong -append")

# assessing clean baselines
for r in rows:
    if r.get("kind") == "baseline" and r.get("oracle") != "gold_run":
        problems.append(f"{r.get('id')} r{r.get('round')}: baseline classified "
                        f"{r.get('oracle')} instead of gold_run")

# assessing no run in the catch-all oracle
for r in rows:
    if r.get("oracle") in ("unclassified_run", "no_signal_run"):
        problems.append(f"{r.get('id')} r{r.get('round')}: {r.get('oracle')}")

print("\noutcomes by oracle:")
for k, n in collections.Counter(r.get("oracle") for r in rows).most_common():
    print(f"  {n:4}  {k}")

print("\nready times (ms):    ",
      sorted(r["ready_ms"] for r in rows if r.get("ready_ms") is not None))
print("client durations (s):",
      sorted(round(r["duration_s"], 2) for r in rows if r.get("duration_s") is not None))
print("qemu exit codes:     ",
      dict(collections.Counter(r.get("qemu_exit") for r in rows)))

print()
if problems:
    print(f"PROBLEMS ({len(problems)}):")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("no mechanical problems: the chain worked")
