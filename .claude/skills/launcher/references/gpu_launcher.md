# GPU launcher wiring

How a joblist line reaches a specific node and a specific GPU, and the three ways
that mapping fails **without an error**. Read this before writing a multi-node
launcher job.

Module facts, variable names and GPUs per node: `reference/taccLS6-launchers.md`.
Shapes, sizing and the joblist contract: the `launcher` skill.

## Nothing in the joblist mentions nodes or GPUs

The mapping is built in two stages, and knowing which variable does what is the
difference between a working farm and one where every task piles onto GPU 0.

**Stage 1 — `paramrun` creates worker slots.** SLURM hands the job `N` nodes.
`paramrun` starts `LAUNCHER_PPN` worker processes **per node**, so there are
`PPN × N` workers. Each gets a global index in `LAUNCHER_TSK_ID`,
block-distributed by node:

```
             LAUNCHER_PPN=3, -N 4  ->  12 workers
node c301-001    TSK_ID  0  1  2
node c301-002    TSK_ID  3  4  5
node c301-003    TSK_ID  6  7  8
node c301-004    TSK_ID  9 10 11
```

Each worker then loops: claim the next unread joblist line, run it to completion,
claim another. With `LAUNCHER_SCHED=dynamic` there is no wave barrier — a worker
that finishes early takes the next task immediately.

**Stage 2 — the dispatcher picks the devices.** The launcher does *not* assign
GPUs. This is `gpu_dispatcher.sh`:

```bash
LOCAL_RANK=$(( LAUNCHER_TSK_ID % LAUNCHER_PPN ))    # global index -> within-node
FIRST_GPU=$(( LOCAL_RANK * GPUS_PER_TASK ))         # contiguous block per worker
```

The modulo collapses the *global* worker index to a *within-node* index, which is
exactly why the block distribution above matters.

With `GPUS_PER_TASK=1, PPN=3` on a 3-GPU node:

| `TSK_ID` | `% 3` | gets |
|---|---|---|
| 0, 3, 6, 9 | 0 | `CUDA_VISIBLE_DEVICES=0`, cores 0–31 |
| 1, 4, 7, 10 | 1 | `CUDA_VISIBLE_DEVICES=1`, cores 32–63 |
| 2, 5, 8, 11 | 2 | `CUDA_VISIBLE_DEVICES=2`, cores 64–95 |

`CUDA_VISIBLE_DEVICES=1` makes the task see exactly **one** GPU, which it then
calls "GPU 0". Three single-GPU processes coexist on a node, each believing it
owns the machine. The core range in `TASK_CORES` does the same for CPUs — the
dispatcher works out which cores are this task's, and `launch.sh` binds to them
in whatever way its toolchain uses.

With `GPUS_PER_TASK=3, PPN=1` the same arithmetic gives one worker
`CUDA_VISIBLE_DEVICES=0,1,2` and cores 0–95 — the whole node, one task. The
pinning becomes a no-op, correctly: there is no neighbour to protect against.

### Cores per task is `OMP_NUM_THREADS × GPUS_PER_TASK`

One core per OpenMP thread, per rank. The occupied core can be smaller than 
total but. For example, OpenMP thread 32 takes 96 of 128 cores when running 
3 rank. The dispatcher refuses to start if the blocks would overrun
the node.

## Use `LAUNCHER_TSK_ID`, never `LAUNCHER_JID`

`TSK_ID` is the **worker slot** (`0…slots−1`) and is **fixed for that worker's
lifetime**. `LAUNCHER_JID` is the **joblist line number** and changes every time
the worker picks up new work.

Taking the modulo of `JID` reshuffles the GPU assignment on every task, so two
concurrent tasks on a node can land on the same GPU. They still run — slowly,
contending for VRAM — which is why this survives casual inspection.

## The failure that produces no output at all

**Multi-node (`-N > 1`) requires the SLURM-environment override.**

Each joblist task starts its own MPI job. Open MPI is SLURM-aware: it reads
`SLURM_NODELIST` and `SLURM_TASKS_PER_NODE` to decide what hardware it may use.
On a multi-node job SLURM sets `SLURM_TASKS_PER_NODE="3(x2)"` — the whole farm.

Override only `SLURM_NODELIST` to the local host and the MPI launcher sees **1
node in the list, 2 nodes in the task layout**, cannot reconcile them, and aborts in
`ras_base_allocate` *before* `MPI_Init`. Every task "finishes" in seconds with
**no output file**. On `-N 1` the value is a plain `3` with no `(xN)` multiplier,
so it matches and the bug never appears in testing.

`gpu_dispatcher.sh` gives each inner MPI launcher a self-consistent view (this
part stays in the dispatcher — it is about SLURM misdescribing the allocation to
*anything* that reads it, and is harmless for a task that uses no MPI):

```bash
export SLURM_NODELIST=$(hostname -s)
export SLURM_NNODES=1
export SLURM_JOB_NUM_NODES=1
export SLURM_TASKS_PER_NODE=$GPUS_PER_TASK
export SLURM_NTASKS=$GPUS_PER_TASK
export SLURM_NPROCS=$GPUS_PER_TASK
```

**This is required at `LAUNCHER_PPN=1` too, for the mirror-image reason.** With
`-N 3, PPN=1` SLURM exports `"1(x3)"`, and an inner 3-rank launch would read that
as *one rank on each of three nodes* and scatter a single task across the farm.
The override must say **1 node, `GPUS_PER_TASK` tasks**.

## Verifying the mapping on a real run

The dispatcher echoes one line per task to stderr:

```bash
grep "TSK=" <jobname>.e<jobid> | head
# c301-001 TSK=0 JID=1 GPU=0 CORES=0-31 EXE=.../<binary> DIR=.../task-001
```

Each host should appear with each device exactly once per concurrent wave. **Keep
the grep scoped to one file** — a recursive grep across a whole farm's logs is a
login-node problem in its own right.
