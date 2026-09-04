#!/bin/bash
# probe.sh — VASP error probe, run LOCALLY by scripts/watch_jobs.sh.
#
# This file is where VASP failure signatures accumulate. Because the probe is
# local rather than shipped with the node, a signature added here applies at the
# next poll — including to jobs that are already running.
#
# Usage:  bash probe.sh <remote_dir>
# Env:    PROBE_SSH — ssh prefix supplied by the watcher (BatchMode + timeout)
#
# Emits:  ERROR=<file: line>   the run said something fatal
#         WARN=<file: line>    the run said something concerning
#
# WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
#
# It reports text VASP (or the runtime under it) actually printed. Nothing here
# infers health from rates, counters or timing: how long a healthy step takes
# depends on the cell, the calculation type and the hardware, so any threshold
# would be wrong somewhere, and a false alarm is worse than a missed one — it
# teaches you to ignore the channel. A run that hangs without complaining is
# caught by SLURM at walltime, as TIMEOUT.
#
# Cost discipline — these run repeatedly on a shared login node:
#   * only bounded tails, never a whole file
#   * OUTCAR and OSZICAR are never touched. OUTCAR reaches many MB, and OSZICAR
#     carries only numbers — no error text lives there
#   * one ssh, one round trip, whatever the number of task directories
set -u
R="${1:-}"
[ -z "$R" ] && exit 0
SSHC="${PROBE_SSH:-ssh -n ls6}"   # -n: never consume the caller's stdin

# vasp.out at the node level covers a plain job; */vasp.out covers a launcher
# job, where each packed task has its own directory. The SLURM .e file catches
# what never reached VASP's stdout — MPI aborts, signals, OOM kills.
out=$($SSHC "cd '$R' 2>/dev/null || exit 0
  for f in vasp.out */vasp.out *.e[0-9]*; do
    [ -f \"\$f\" ] || continue
    echo \"--FILE--\$f\"
    tail -c 1500 \"\$f\"
  done 2>/dev/null" 2>/dev/null)
[ -z "$out" ] && exit 0

# --- fatal: VASP's own panics, then the runtime beneath it ----------------
FATAL='VERY BAD NEWS|internal error|ZBRENT: fatal|EDDDAV.*ZHEGV|LAPACK:.*failed'
FATAL="$FATAL"'|[Ee]rror reading item|Fatal error|ERROR: *[A-Za-z]'
FATAL="$FATAL"'|forrtl: severe|SIGSEGV|SIGBUS|SIGFPE'
FATAL="$FATAL"'|[Oo]ut of memory|oom-kill|oom_kill'
FATAL="$FATAL"'|slurmstepd: error|srun: error|MPI_ABORT|mpirun noticed'
FATAL="$FATAL"'|cuMemAlloc returned error|CUDA.*[Ee]rror'

# --- concerning, not fatal ------------------------------------------------
CONCERN='Sub-Space-Matrix is not hermitian|BRIONS problems|ZBRENT: can'
CONCERN="$CONCERN"'|number of bands is not sufficient|too few bands'

# Attribute each hit to the file it came from — with a launcher job packing
# several tasks into one SLURM job, "which task" is the first thing you need.
scan() {                # scan <regex>
  printf '%s' "$out" | awk -v re="$1" '
    /^--FILE--/ { f = substr($0, 9); next }
    $0 ~ re     { line = $0
                  gsub(/^[ \t]+|[ \t]+$/, "", line)
                  print f ": " substr(line, 1, 140)
                  exit }'
}

err=$(scan "$FATAL")
[ -n "$err" ] && echo "ERROR=$err"

warn=$(scan "$CONCERN")
[ -n "$warn" ] && echo "WARN=$warn"

exit 0
