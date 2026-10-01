#!/usr/bin/env bash
# scripts/taskgen_checkpoint.sh <pid> [results_dir] -- while the full run <pid> (taskgen_generate_all.sh) is alive,
# append one progress line to <results_dir>/checkpoints.log every 2 h, and a last one when it exits.
# results_dir defaults to results (taskgen/v2/results); it must hold the run's generate_all.log (the nohup output).
set -uo pipefail
PID=$1
cd "$(dirname "$0")/.." && cd "${2:-results}" || exit 1
snap() {
  dbs=$(grep -c '^== ' generate_all.log); fails=$(grep -c FAILED generate_all.log)
  cands=$(cat */candidates.jsonl 2>/dev/null | wc -l); checked=$(cat */check.jsonl 2>/dev/null | wc -l)
  passed=$(cat */check.jsonl 2>/dev/null | grep -c '"ok": true')
  echo "$(date '+%F %T') $1 | dbs_started=$dbs failed_lines=$fails candidates=$cands checked=$checked check_ok=$passed | now: $(grep '^== ' generate_all.log | tail -1)" >> checkpoints.log
}
snap start
while kill -0 "$PID" 2>/dev/null; do
  for i in $(seq 720); do kill -0 "$PID" 2>/dev/null || break; sleep 10; done
  kill -0 "$PID" 2>/dev/null && snap running
done
snap finished
