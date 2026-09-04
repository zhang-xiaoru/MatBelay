#!/bin/bash
# gpu_dispatcher.sh — run ONE task pinned to N GPUs and their CPU cores.
#
# Called once per joblist line by launcher_gpu's paramrun:
#     gpu_dispatcher.sh <task_dir> <executable> [args...]
#
# The launcher hands out worker slots; it does NOT assign GPUs. This script is
# what turns a slot index into a device list, a core range, and a launch.
#
# It knows nothing about what it runs, and nothing about how to start it.
# Placement is its job; the launch is handed off to `launch.sh`, which the calling
# tool supplies. That split exists because `mpirun`, `ibrun`, `srun` and "just run
# it" are all correct answers depending on the toolchain, and none of them is the
# launcher's to pick.
#
# ---------------------------------------------------------------------------
# Placement (export in the .batch, before $LAUNCHER_DIR/paramrun)
#   GPUS_PER_TASK    GPUs given to one task              default 1
#   GPUS_PER_NODE    GPUs the node actually has          default 3   (a100; h100 = 2)
#   CORES_PER_NODE   cores the node actually has         default 128 (a100; h100 = 96)
#   LAUNCHER_PPN     workers per node = GPUS_PER_NODE / GPUS_PER_TASK
#
# Tool-specific (also exported in the .batch — same for every task in the job)
#   TASK_STDOUT      file each task's output goes to     default task.out
#   TASK_DONE_CHECK  shell test run in the task dir; exit 0 means "already
#                    finished, skip me". Unset = never skip.
#
#   e.g. for VASP:
#     export TASK_STDOUT=vasp.out
#     export TASK_DONE_CHECK='grep -q "reached required accuracy\|General timing" OUTCAR'
#
# Required: $LAUNCHER_WORKDIR/launch.sh, supplied by the tool. It is called as
#   launch.sh <executable> [args...]
# in the task directory, with CUDA_VISIBLE_DEVICES, TASK_CORES, TASK_NRANKS and
# OMP_NUM_THREADS already exported. It decides how to start the code.
#
#   shape                       M  PPN  -N  -n
#   A  farm, 1 task per GPU     1   3    k  3k
#   B  memory-bound, whole node 3   1    k   k
#   C  parallel, whole node     3   1    k   k
#
# B and C are the same placement; they differ only in the tool's own parallel
# parameter, which this script neither sets nor knows about.
# ---------------------------------------------------------------------------
set -e

SELF_DIR=$(cd "$(dirname "$0")" && pwd)

TASK_DIR="$1"; shift
EXE_NAME="$1";  shift          # remaining "$@" are the executable's own arguments

GPUS_PER_TASK="${GPUS_PER_TASK:-1}"
GPUS_PER_NODE="${GPUS_PER_NODE:-3}"
CORES_PER_NODE="${CORES_PER_NODE:-128}"
TASK_STDOUT="${TASK_STDOUT:-task.out}"

# --- the rule that prevents silently stranding hardware ---------------------
# GPUs are handed out in contiguous blocks per worker, so a task size that does
# not divide the node leaves devices idle with no error. On a100 (3 GPUs),
# GPUS_PER_TASK=2 gives 1 task/node and wastes the third; that shape belongs on
# gpu-h100, which has exactly 2.
if [ $(( GPUS_PER_NODE % GPUS_PER_TASK )) -ne 0 ]; then
  echo "ERROR: GPUS_PER_TASK=$GPUS_PER_TASK does not divide GPUS_PER_NODE=$GPUS_PER_NODE." >&2
  echo "       That strands $(( GPUS_PER_NODE % GPUS_PER_TASK )) GPU(s) per node. Use a divisor, or a partition whose GPU count fits." >&2
  exit 1
fi

EXPECTED_PPN=$(( GPUS_PER_NODE / GPUS_PER_TASK ))
if [ "${LAUNCHER_PPN:-$EXPECTED_PPN}" -ne "$EXPECTED_PPN" ]; then
  echo "ERROR: LAUNCHER_PPN=$LAUNCHER_PPN but GPUS_PER_NODE/GPUS_PER_TASK = $EXPECTED_PPN." >&2
  echo "       Set LAUNCHER_PPN=$EXPECTED_PPN in the batch script (and -n = $EXPECTED_PPN x N)." >&2
  exit 1
fi

EXE=$(command -v "$EXE_NAME" 2>/dev/null)
if [ -z "$EXE" ] || [ ! -x "$EXE" ]; then
  echo "ERROR: executable '$EXE_NAME' not found or not executable" >&2
  exit 1
fi

cd "$TASK_DIR"

# Skip tasks that already finished, so resubmitting a whole joblist is safe after
# a walltime kill. What "finished" means is the tool's business, not this
# script's — it only runs the test it was given.
if [ -n "${TASK_DONE_CHECK:-}" ] && eval "$TASK_DONE_CHECK" >/dev/null 2>&1; then
  echo "$TASK_DIR already complete, skipping" >&2
  exit 0
fi

# --- slot -> devices + cores -----------------------------------------------
# LAUNCHER_TSK_ID is the GLOBAL worker index and is fixed for that worker's
# lifetime. LAUNCHER_JID is the joblist LINE number and changes with every task
# the worker picks up — taking its modulo would reshuffle GPU assignment mid-run
# and land two concurrent tasks on the same device.
LOCAL_RANK=$(( LAUNCHER_TSK_ID % LAUNCHER_PPN ))

FIRST_GPU=$(( LOCAL_RANK * GPUS_PER_TASK ))
# Built with a loop, not `seq -s,`: BSD and GNU seq disagree about a trailing
# separator, and "CUDA_VISIBLE_DEVICES=0," is not something to debug on a
# compute node.
DEVLIST=""; i=0
while [ "$i" -lt "$GPUS_PER_TASK" ]; do
  [ -n "$DEVLIST" ] && DEVLIST="${DEVLIST},"
  DEVLIST="${DEVLIST}$(( FIRST_GPU + i ))"
  i=$(( i + 1 ))
done
export CUDA_VISIBLE_DEVICES="$DEVLIST"

# Cores per task = one core per OpenMP thread, per rank. The remainder is spare, not
# lost work — raising OMP_NUM_THREADS widens each block.
OMP="${OMP_NUM_THREADS:-32}"
SPAN=$(( OMP * GPUS_PER_TASK ))
if [ $(( SPAN * LAUNCHER_PPN )) -gt "$CORES_PER_NODE" ]; then
  echo "ERROR: OMP_NUM_THREADS=$OMP x GPUS_PER_TASK=$GPUS_PER_TASK x PPN=$LAUNCHER_PPN" >&2
  echo "       = $(( SPAN * LAUNCHER_PPN )) cores > CORES_PER_NODE=$CORES_PER_NODE. Lower OMP_NUM_THREADS." >&2
  exit 1
fi
FIRST_CORE=$(( LOCAL_RANK * SPAN ))

# The contract handed to launch.sh: which devices, which cores, how many ranks.
# This script COMPUTES the core range; launch.sh APPLIES it, because numactl vs
# `--bind-to core` vs `srun --cpu-bind` are toolchain choices, not node arithmetic.
export TASK_CORES="${FIRST_CORE}-$(( FIRST_CORE + SPAN - 1 ))"
export TASK_NRANKS="$GPUS_PER_TASK"

# --- give any inner MPI launcher a self-consistent view of its allocation ---
# On a multi-node launcher job SLURM exports SLURM_TASKS_PER_NODE="<ppn>(x<N>)",
# describing the WHOLE farm. An inner MPI launcher reading that would try to
# spread this task's ranks across every node. Overriding only
# SLURM_NODELIST leaves node list = 1 host but task layout = N nodes, which Open
# MPI cannot reconcile — it aborts in ras_base_allocate BEFORE MPI_Init, so every
# task "finishes" in seconds having produced nothing.
#
# Required at PPN=1 too, and for the mirror-image reason: with -N 3, PPN=1 SLURM
# says "1(x3)", and a 3-rank launch would read that as one rank on each of three
# nodes and scatter a single task across the farm. Harmless for a task that uses
# no MPI at all.
export SLURM_NODELIST=$(hostname -s)
export SLURM_NNODES=1
export SLURM_JOB_NUM_NODES=1
export SLURM_TASKS_PER_NODE=$GPUS_PER_TASK
export SLURM_NTASKS=$GPUS_PER_TASK
export SLURM_NPROCS=$GPUS_PER_TASK

echo "$(hostname -s) TSK=$LAUNCHER_TSK_ID JID=${LAUNCHER_JID:-?} GPU=$CUDA_VISIBLE_DEVICES CORES=$TASK_CORES EXE=$EXE DIR=$TASK_DIR" >&2

# --- hand off to the tool's launch script -----------------------------------
# There is deliberately no fallback. A default would be some particular MPI's
# syntax, which is exactly the assumption this split removes — and a tool that
# inherited it by accident would fail confusingly rather than loudly.
LAUNCH="${LAUNCHER_WORKDIR:-$SELF_DIR}/launch.sh"
if [ ! -f "$LAUNCH" ]; then
  echo "ERROR: no launch.sh at $LAUNCH" >&2
  echo "       The dispatcher places tasks; it cannot know how to start this code." >&2
  echo "       Supply launch.sh from the tool's skill (VASP: .claude/skills/vasp/assets/launch.sh)." >&2
  exit 1
fi

exec bash "$LAUNCH" "$EXE" "$@" > "$TASK_STDOUT" 2>&1
