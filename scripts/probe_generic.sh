#!/bin/bash
# probe_generic.sh — the fallback error probe. Works for any code, knows none.
#
# Used by watch_jobs.sh when a watchlist row's `tool` has no probe of its own
# (or is empty).
#
# It cannot know what YOUR code calls an error, so it reports only what the
# layer BELOW your code says: SLURM, MPI, the OS. Those speak the same way for
# every job on this cluster — a segfault, an OOM kill and an MPI abort look
# identical whether the binary was VASP or a Python script.
#
# What it therefore misses is everything tool-specific: a solver that will not
# converge, a bad input the code rejected politely, a warning that matters. That
# is the whole reason a tool graduates to its own probe.sh — see
# reference/quick-ref.md, "Health probes".
#
# Usage:  bash probe_generic.sh <remote_dir>
# Env:    PROBE_SSH — ssh prefix supplied by the watcher (carries BatchMode and
#                     ConnectTimeout, so this can never hang the watcher)
set -u
R="${1:-}"
[ -z "$R" ] && exit 0
SSHC="${PROBE_SSH:-ssh -n ls6}"   # -n: never consume the caller's stdin

out=$($SSHC "cd '$R' 2>/dev/null || exit 0
  for f in *.e[0-9]* *.err; do
    [ -f \"\$f\" ] || continue
    echo \"--FILE--\$f\"
    tail -c 1500 \"\$f\"
  done 2>/dev/null" 2>/dev/null)
[ -z "$out" ] && exit 0

RUNTIME='slurmstepd: error|srun: error|MPI_ABORT|mpirun noticed'
RUNTIME="$RUNTIME"'|SIGSEGV|SIGBUS|SIGFPE|[Oo]ut of memory|oom-kill|oom_kill'
RUNTIME="$RUNTIME"'|forrtl: severe|Segmentation fault|core dumped'

err=$(printf '%s' "$out" | awk -v re="$RUNTIME" '
  /^--FILE--/ { f = substr($0, 9); next }
  $0 ~ re     { line = $0
                gsub(/^[ \t]+|[ \t]+$/, "", line)
                print f ": " substr(line, 1, 140)
                exit }')
[ -n "$err" ] && echo "ERROR=$err"

exit 0
