#!/bin/bash
# launch.sh — start GPU VASP for one launcher task.
#
# Called by the launcher's gpu_dispatcher.sh as:
#     launch.sh <vasp_binary> [args...]
# in the task directory, with these already exported:
#     CUDA_VISIBLE_DEVICES   the devices this task owns, e.g. "0,1,2"
#     TASK_CORES             the core range this task owns, e.g. "0-31"
#     TASK_NRANKS            how many devices it owns
#     OMP_NUM_THREADS        threads per rank
#
# The dispatcher computes those; this file decides how to turn them into a
# running job. That is VASP-and-toolchain specific, which is why it lives in the
# `vasp` skill and not in the launcher:
#
#   * GPU VASP compiled against Navidia's **OpenMPI**, so `--map-by ppr:`,
#     `--bind-to` and `-x VAR` are the right spellings. 
#   * GPU VASP wants **one MPI rank per GPU** — hence `-n $TASK_NRANKS`.
#
# Copy this into the node directory during preparation; it runs on the cluster
# and travels with the node, so a finished run records how it was started.
set -eu

: "${TASK_CORES:?launch.sh: TASK_CORES not set — is this being run by gpu_dispatcher.sh?}"
: "${TASK_NRANKS:?launch.sh: TASK_NRANKS not set — is this being run by gpu_dispatcher.sh?}"
OMP="${OMP_NUM_THREADS:-32}"

# A lone rank wants --bind-to none; several ranks need explicit placement or they
# all land on the same cores. Both forms are also documented in reference/VASP.md.
if [ "$TASK_NRANKS" -eq 1 ]; then
  exec numactl --physcpubind="$TASK_CORES" mpirun -n 1 --bind-to none \
    -x CUDA_VISIBLE_DEVICES -x OMP_NUM_THREADS -x OMP_PLACES -x OMP_PROC_BIND \
    "$@"
else
  exec numactl --physcpubind="$TASK_CORES" mpirun -n "$TASK_NRANKS" \
    --map-by "ppr:${TASK_NRANKS}:node:PE=${OMP}" --bind-to core \
    -x CUDA_VISIBLE_DEVICES -x OMP_NUM_THREADS -x OMP_PLACES -x OMP_PROC_BIND \
    "$@"
fi
