#!/bin/bash
# watch_jobs.sh — SLURM job watcher. Emits ONE line per state change, nothing else.
#
# Runs under the Monitor tool, where every stdout line becomes a notification.
# Silence is therefore free and noise is expensive: a job's whole life should cost
# ~4 lines, not one per poll.
#
# Runs LOCALLY. Nothing is left running on the login node — each poll is a
# short-lived ssh that exits immediately.
#
# WHAT THIS WATCHES, AND WHAT IT DOES NOT
#
#   It reports two things: what SLURM says about the job, and what the job's own
#   output says out loud. It does NOT infer health. There is deliberately no hang
#   detector: "no output for N minutes" needs an N that depends on the code, the
#   system size and the calculation type, and a single fixed threshold is wrong in
#   both directions — false alarms on a slow linear-response step, and useless
#   slack on an MD run that writes every few seconds. A wrong alarm costs more
#   than the missed detection, because it trains you to ignore the channel.
#
#   So: an error is reported when the code prints one. A hang is caught when the
#   job hits its walltime and SLURM reports TIMEOUT.
#
# Three design points worth knowing before editing:
#
#   1. Jobs come from a WATCHLIST FILE, re-read every tick — not from argv.
#      A running process cannot be handed new argv, so an argv-based watcher had
#      to be restarted every time a node was submitted. Appending a line is how
#      the agent adds a job to a live watcher.
#
#   2. Per-job state lives in a STATE FILE, not `declare -A`. Associative arrays
#      are bash 4+; macOS ships 3.2, where a string subscript is evaluated as
#      arithmetic and every key silently collapses onto index 0. The state file
#      also survives a watcher restart and can be inspected with `cat`.
#
#   3. The error probe is TOOL-SPECIFIC and runs LOCALLY, selected per job by
#      the watchlist's 5th column — which is the `tool` field copied verbatim
#      from the DAG node, NOT a path. The path is derived by convention:
#      `.claude/skills/<tool>/scripts/probe.sh`, falling back to the generic
#      probe when that tool has none yet. Copying a name rather than building a
#      path is what stops a typo'd path from silently disabling monitoring.
#      Keeping the probe local means a newly-learned error signature applies
#      immediately, including to jobs already running — a probe shipped with the
#      node would have its patterns frozen at preparation time.
#
#      Watchlist row:  jobid  exploration  node  remote_dir  tool
#      A value containing '/' is taken as an explicit probe path instead, which
#      is the escape hatch for a one-off; nothing in the normal flow uses it.
#
# SLURM COMPLETED is NOT the same as "the physics is right". That judgement is
# the node's gate, evaluated separately.
#
# Usage:   bash scripts/watch_jobs.sh
# Stop:    TaskStop (it never exits on its own)
#
# Env:
#   SSH_HOST=ls6              ssh alias for the login node
#   WATCHLIST=project_workflow/.watchlist
#   STATEFILE=project_workflow/.watchstate
#   TICK=300                  seconds between polls once a job is settled
#   SETTLE_TICK=60            seconds between polls while ANY job is settling
#   SETTLE_SECONDS=600        how long a freshly-started job stays in SETTLING
#   HEALTHY_PROBE_MIN=30      minutes between probes once SETTLED
#   UNKNOWN_TICKS=5           consecutive "no such job" polls before reporting it
#   ERROR_STOPS_PROBE=0       1 = an ERROR= from the probe ends probing for that job

set -u

HERE=$(cd "$(dirname "$0")/.." && pwd)
SSH_HOST="${SSH_HOST:-ls6}"
WATCHLIST="${WATCHLIST:-$HERE/project_workflow/.watchlist}"
STATEFILE="${STATEFILE:-$HERE/project_workflow/.watchstate}"
TICK="${TICK:-300}"
SETTLE_TICK="${SETTLE_TICK:-60}"
SETTLE_SECONDS="${SETTLE_SECONDS:-600}"
HEALTHY_PROBE_MIN="${HEALTHY_PROBE_MIN:-30}"
UNKNOWN_TICKS="${UNKNOWN_TICKS:-5}"
ERROR_STOPS_PROBE="${ERROR_STOPS_PROBE:-0}"
DEFAULT_PROBE="${DEFAULT_PROBE:-$HERE/scripts/probe_generic.sh}"

# -n is load-bearing, not tidiness: without it ssh forwards stdin to the remote
# command and drains it. The per-job loop below is `... | while read`, so the
# first job's ssh would swallow every remaining line and only one job per tick
# would ever be processed. The same applies to the probes, which inherit this
# prefix through PROBE_SSH.
SSH="ssh -n -o BatchMode=yes -o ConnectTimeout=10"

# ---------------------------------------------------------------------------
# State file: one line per job
#   jobid phase settle_ts probe_ts unknown msgsum
#
# settle_ts is stamped once, when the job is first seen RUNNING, and never moved
# — it is what SETTLING is measured against. probe_ts is the last probe, which
# paces the HEALTHY cadence. msgsum is a checksum of the probe's current message
# set, so an unchanged error is not re-reported every poll.
#
# phase: NEW | PENDING | SETTLING | HEALTHY | NOPROBE | DONE | GONE
# ---------------------------------------------------------------------------
touch "$STATEFILE" 2>/dev/null || { echo "FATAL: cannot write $STATEFILE" >&2; exit 1; }

st_line() { grep "^$1 " "$STATEFILE" 2>/dev/null | head -1; }

st_field() {            # st_field JOBID N  (1=phase 2=settle_ts 3=probe_ts 4=unknown 5=msgsum)
  local l; l=$(st_line "$1")
  [ -z "$l" ] && return 1
  echo "$l" | awk -v n="$(( $2 + 1 ))" '{print $n}'
}

st_put() {              # st_put JOBID PHASE SETTLE_TS PROBE_TS UNKNOWN MSGSUM
  local tmp="$STATEFILE.$$"
  grep -v "^$1 " "$STATEFILE" > "$tmp" 2>/dev/null
  echo "$1 $2 $3 $4 ${5:-0} ${6:-0}" >> "$tmp"
  mv "$tmp" "$STATEFILE"
}

st_drop() {
  local tmp="$STATEFILE.$$"
  grep -v "^$1 " "$STATEFILE" > "$tmp" 2>/dev/null
  mv "$tmp" "$STATEFILE"
}

emit() { echo "[$1 $2] $3"; }

# Wait until an ISO start time, in whole minutes. BSD date (macOS) needs -j -f;
# a bad or N/A timestamp must not kill the watcher, so failures return nothing.
wait_minutes() {
  local ts="$1" e n
  case "$ts" in ''|N/A|Unknown) return 1 ;; esac
  e=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$ts" +%s 2>/dev/null) || return 1
  [ -z "$e" ] && return 1
  n=$(date +%s)
  echo "$(( (e - n) / 60 ))"
}

# ---------------------------------------------------------------------------
# Remote state poll: ONE ssh per tick for ALL jobs. Always 3 fields:
#   JOBID|PENDING|2026-08-30T14:20:00      queued    (squeue)
#   JOBID|RUNNING|2026-08-30T09:05:00      running   (squeue)
#   JOBID|COMPLETED|07:12:44               finished  (sacct -P: State|Elapsed)
#   JOBID|UNKNOWN|                         no record
# ---------------------------------------------------------------------------
poll_states() {
  local jobs="$1"
  [ -z "$jobs" ] && return 0
  local remote='for j in '"$jobs"'; do
    l=$(squeue -h -j $j -o "%T|%S" 2>/dev/null)
    if [ -n "$l" ]; then
      echo "$j|$l"
    else
      s=$(sacct -j $j -X -n -P -o State,Elapsed 2>/dev/null | head -1)
      if [ -n "$s" ]; then echo "$j|$s"; else echo "$j|UNKNOWN|"; fi
    fi
  done'
  $SSH "$SSH_HOST" "$remote" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Error probe — LOCAL script, selected per job by the watchlist's `tool` column.
#
#   invoked as:  bash <probe> <remote_dir>
#   environment: SSH_HOST, and PROBE_SSH — a ready-made ssh prefix that already
#                carries BatchMode and ConnectTimeout, so a probe cannot hang
#                the watcher on a dead connection.
#   prints (any subset, exit 0 always):
#       ERROR=<message>   the code said something fatal
#       WARN=<message>    the code said something concerning
#       NOTE=<message>    informational
#
# A probe REPORTS WHAT THE CODE SAID. It does not judge whether the run is going
# well — no counters, no rates, no timing. That keeps a probe to a handful of
# greps over a bounded tail, which is what makes it safe to run repeatedly on a
# shared login node, and it keeps the signal falsifiable: every line the watcher
# emits can be traced to text the code actually printed.
#
# Keep whatever the probe reads cheap — `tail -c` is O(1); a grep over a
# multi-hundred-MB output file is not.
# ---------------------------------------------------------------------------
run_probe() {           # run_probe PROBE REMOTE_DIR
  [ -z "$1" ] && return 0
  if [ ! -f "$1" ]; then echo "ERROR=probe script not found: $1"; return 0; fi
  PROBE_SSH="$SSH $SSH_HOST" SSH_HOST="$SSH_HOST" bash "$1" "$2" 2>/dev/null
}

is_terminal() {
  case "$1" in
    COMPLETED|FAILED|TIMEOUT|CANCELLED*|NODE_FAIL|OUT_OF_MEMORY|BOOT_FAIL|DEADLINE|PREEMPTED) return 0 ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Main loop. Never exits on its own: the moment all current jobs are terminal is
# exactly when the agent is about to submit the next node, so exiting there
# guarantees missing it. Stop with TaskStop.
# ---------------------------------------------------------------------------
fails=0
warned_empty=0

while true; do
  jobs=""
  if [ -f "$WATCHLIST" ]; then
    jobs=$(grep -v '^[[:space:]]*#' "$WATCHLIST" 2>/dev/null | awk 'NF {print $1}' | sort -u)
  fi

  if [ -z "$jobs" ]; then
    [ "$warned_empty" -eq 0 ] && { echo "watching $WATCHLIST — no jobs yet"; warned_empty=1; }
    sleep "$TICK"; continue
  fi
  warned_empty=0

  # Drop state for jobs the agent has removed from the watchlist.
  while read -r sj _rest; do
    [ -z "$sj" ] && continue
    case " $(echo $jobs) " in *" $sj "*) ;; *) st_drop "$sj" ;; esac
  done < "$STATEFILE"

  # Poll only jobs that can still change. A terminal job left in the watchlist
  # would otherwise cost a squeue AND a sacct every tick, forever, for a state
  # that is already known.
  live=""
  for j in $jobs; do
    case "$(st_field "$j" 1)" in DONE|GONE) ;; *) live="$live $j" ;; esac
  done

  if [ -n "$live" ]; then
    out=$(poll_states "$live")
    if [ -z "$out" ]; then
      fails=$(( fails + 1 ))
      if [ "$fails" -eq 3 ]; then
        echo "WARN: 3 consecutive poll failures on $SSH_HOST — watcher is BLIND. Run 'ssh $SSH_HOST' to re-establish the ControlMaster."
      fi
      sleep "$TICK"; continue
    fi
    fails=0
    now=$(date +%s)

    echo "$out" | while IFS='|' read -r j state extra; do
      [ -z "$j" ] && continue

      row=$(grep -v '^[[:space:]]*#' "$WATCHLIST" 2>/dev/null | awk -v j="$j" '$1==j {print; exit}')
      expl=$(echo "$row" | awk '{print $2}')
      node=$(echo "$row" | awk '{print $3}')
      rdir=$(echo "$row" | awk '{print $4}')
      # Column 5 is the DAG node's `tool`. Resolve it to a probe by convention;
      # a tool with no probe.sh yet is watched at SLURM granularity plus the
      # generic runtime-error check, rather than not at all.
      tool=$(echo "$row" | awk '{print $5}')
      case "$tool" in
        '')  probe="$DEFAULT_PROBE" ;;
        */*) case "$tool" in /*) probe="$tool" ;; *) probe="$HERE/$tool" ;; esac ;;
        *)   probe="$HERE/.claude/skills/$tool/scripts/probe.sh"
             [ -f "$probe" ] || probe="$DEFAULT_PROBE" ;;
      esac
      label="${expl:-?}/${node:-?}"

      phase=$(st_field "$j" 1) || phase=NEW
      settle_ts=$(st_field "$j" 2); settle_ts="${settle_ts:-$now}"
      probe_ts=$(st_field "$j" 3);  probe_ts="${probe_ts:-0}"
      unk=$(st_field "$j" 4);       unk="${unk:-0}"
      msgsum=$(st_field "$j" 5);    msgsum="${msgsum:-0}"

      # ---- terminal: report once, stop tracking ----
      if is_terminal "$state"; then
        emit "$j" "$label" "$state runtime=${extra:-?}"
        st_put "$j" DONE "$settle_ts" "$probe_ts" "$unk" "$msgsum"
        continue
      fi

      # ---- scheduler has no record of this job ----
      # Silence here is indistinguishable from "still running", so report it — but
      # only after a few ticks, since a job is briefly unknown in the gap between
      # sbatch returning and the scheduler registering it.
      if [ "$state" = UNKNOWN ]; then
        unk=$(( unk + 1 ))
        if [ "$unk" -ge "$UNKNOWN_TICKS" ]; then
          emit "$j" "$label" "GONE — scheduler has no record of this job after $unk polls (wrong id, or purged from sacct)"
          st_put "$j" GONE "$settle_ts" "$probe_ts" "$unk" "$msgsum"
        else
          st_put "$j" "$phase" "$settle_ts" "$probe_ts" "$unk" "$msgsum"
        fi
        continue
      fi

      # ---- queued ----
      if [ "$state" = PENDING ]; then
        if [ "$phase" != PENDING ]; then
          w=$(wait_minutes "$extra") && \
            emit "$j" "$label" "QUEUED est_start=$extra (~${w}m)" || \
            emit "$j" "$label" "QUEUED est_start=${extra:-unknown}"
          st_put "$j" PENDING "$now" 0 0 0
        fi
        continue
      fi

      # ---- running: entering the settling window ----
      if [ "$state" = RUNNING ] && [ "$phase" != SETTLING ] && [ "$phase" != HEALTHY ] && [ "$phase" != NOPROBE ]; then
        emit "$j" "$label" "RUNNING"
        st_put "$j" SETTLING "$now" 0 "$unk" 0
        phase=SETTLING; settle_ts="$now"; probe_ts=0; msgsum=0
      fi

      [ "$phase" = NOPROBE ] && continue

      # ---- probe, on this phase's cadence ----
      # SETTLING is the close-watch window: every poll, at the shorter tick, for
      # SETTLE_SECONDS after the job starts. That is where a bad parameter or a
      # missing file announces itself. After that, checking is a background cost
      # and drops to the HEALTHY cadence.
      due=0
      if [ "$phase" = SETTLING ]; then
        due=1
      elif [ "$phase" = HEALTHY ]; then
        [ $(( now - probe_ts )) -ge $(( HEALTHY_PROBE_MIN * 60 )) ] && due=1
      fi

      if [ "$due" -eq 1 ]; then
        pout=""
        [ -n "$rdir" ] && pout=$(run_probe "$probe" "$rdir")

        # ---- messages: emit only when the set of them has changed ----
        perr=$(echo "$pout"  | sed -n 's/^ERROR=//p' | head -1)
        pwarn=$(echo "$pout" | sed -n 's/^WARN=//p'  | head -1)
        pnote=$(echo "$pout" | sed -n 's/^NOTE=//p'  | head -1)
        newsum=$(printf '%s|%s|%s' "$perr" "$pwarn" "$pnote" | cksum | awk '{print $1}')
        if [ "$newsum" != "$msgsum" ]; then
          [ -n "$perr" ]  && emit "$j" "$label" "ERROR $perr"
          [ -n "$pwarn" ] && emit "$j" "$label" "WARN $pwarn"
          [ -n "$pnote" ] && emit "$j" "$label" "NOTE $pnote"
          msgsum="$newsum"
        fi
        probe_ts="$now"

        # An ERROR is reported once and, by default, probing continues — a run
        # often prints a second, more specific line after the first.
        if [ -n "$perr" ] && [ "$ERROR_STOPS_PROBE" = "1" ]; then
          st_put "$j" NOPROBE "$settle_ts" "$probe_ts" "$unk" "$msgsum"
          continue
        fi
      fi

      # ---- graduate out of the close-watch window, on time ----
      # Purely time-based, deliberately: the window means "I have watched this
      # closely for SETTLE_SECONDS and the code has not complained", which is a
      # statement about elapsed time, not about anything the job produced.
      if [ "$phase" = SETTLING ] && [ $(( now - settle_ts )) -ge "$SETTLE_SECONDS" ]; then
        emit "$j" "$label" "SETTLED — no errors in first $(( SETTLE_SECONDS / 60 ))m; checking every ${HEALTHY_PROBE_MIN}m"
        st_put "$j" HEALTHY "$settle_ts" "$probe_ts" "$unk" "$msgsum"
      else
        st_put "$j" "$phase" "$settle_ts" "$probe_ts" "$unk" "$msgsum"
      fi
    done
  fi

  # Poll faster while any job is inside its close-watch window; that is the only
  # phase where resolution buys anything.
  if grep -q ' SETTLING ' "$STATEFILE" 2>/dev/null; then
    sleep "$SETTLE_TICK"
  else
    sleep "$TICK"
  fi
done
