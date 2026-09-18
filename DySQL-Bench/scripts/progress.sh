#!/usr/bin/env bash
# scripts/progress.sh <tag> [conc] [agent_port] [agent_container] -- one-screen status of a full run
TAG="${1:?usage: progress.sh <tag> [conc] [agent_port] [agent_container]}"
CONC="${2:-16}"; APORT="${3:-8000}"; ACONT="${4:-dysql-agent}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"
LOG="$OUT/run.log"; [ -f "$LOG" ] || LOG="$OUT/../full_run.log"
echo "== $(date '+%F %T')  tag=$TAG"
grep -E "^\[" "$LOG" 2>/dev/null | tail -3
python3 - "$OUT" "$CONC" <<'PY'
import glob, json, sys, statistics
out, conc = sys.argv[1], int(sys.argv[2])
counts = {"eu_soccer":215,"retail":205,"entertainment":131,"bowling":111,"pagila":105,"law_episode":53,"cookbook":51,
          "chinook":44,"human_resources":40,"retail_world":31,"ice_hockey":28,"car":27,"music":21}
tot_done = tot_pass = 0; walls = []
print(f"{'env':16s} {'done':>9s} {'pass':>6s} {'avg wall':>9s}")
for env, n in counts.items():
    fs = [f for f in glob.glob(f"{out}/{env}-*.json") if not f.endswith(".config.json")]
    if not fs: continue
    rs = json.load(open(fs[0]))
    d = len(rs); p = sum(1 for r in rs if r["reward"] == 1)
    w = [r["meta"].get("wall_s") or 0 for r in rs]
    walls += w; tot_done += d; tot_pass += p
    err = sum(1 for r in rs if r["meta"].get("termination") == "error")
    print(f"{env:16s} {d:4d}/{n:<4d} {100*p/max(d,1):5.1f}% {statistics.mean(w) if w else 0:8.0f}s" + (f"  errors={err}" if err else ""))
print(f"{'TOTAL':16s} {tot_done:4d}/1062 {100*tot_pass/max(tot_done,1):5.1f}%")
if walls:
    rem = 1062 - tot_done
    print(f"ETA ≈ {rem*statistics.mean(walls)/conc/3600:.1f} h remaining (avg wall {statistics.mean(walls):.0f}s, c≈{conc})")
PY
echo "-- servers: agent:$APORT $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$APORT/v1/models) user:8001 $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/v1/models) | preempt agent=$(docker logs --since 1h $ACONT 2>&1 | grep -ci preempt) user=$(docker logs --since 1h dysql-user 2>&1 | grep -ci preempt) | $(docker logs --since 30s $ACONT 2>&1 | grep -oE 'Running: [0-9]+ reqs, Waiting: [0-9]+' | tail -1)"
free -g | sed -n 2p
