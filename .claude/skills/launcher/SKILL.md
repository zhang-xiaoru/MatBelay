---
name: launcher
description: >-
  Pack many independent tasks into ONE SLURM job instead of submitting each
  separately — choosing the dispatch shape (how many GPUs or cores per task),
  sizing LAUNCHER_PPN / -N / -n, and writing the joblist and dispatcher. Use
  whenever several similar runs could share an allocation, or one run needs more
  than one GPU: "pack these 3 relaxes onto one A100 node", "run 200 displacements
  as one job", "this cell is too big for one GPU", "run each job on a whole GPU
  node", "use the launcher for this sweep", "how many nodes for 192 displacement
  runs". Also use when a launcher job misbehaves — tasks landing on the same GPU,
  every task finishing in seconds with no output, or GPUs sitting idle. Covers
  TACC `launcher_gpu`; environment facts (modules, variables, GPUs per node) are
  in `reference/taccLS6-launchers.md`. This skill does NOT choose the queue, walltime or
  allocation — that is `prepare-node` — and knows nothing about what the tasks
  compute: the executable, its parallel parameters and how to tell a run finished
  all come from that tool's own skill, so the same dispatcher serves VASP,
  LAMMPS, Quantum ESPRESSO or anything else that runs one rank per GPU.
---

# Packing tasks into one job

When several **independent** runs each need less than a whole allocation, submit
them as one job and run them side by side. The saving is queue time and billing,
not compute: three separately-queued GPU jobs wait three times and bill three
fractional nodes; one packed node waits once and bills one.

The same machinery also gives a **single** task more than one GPU, which is how a
cell too large for one card gets to run at all.

Environment facts — modules, what they set, GPUs per node — are in
`reference/taccLS6-launchers.md`. Read it before sizing anything.

## The one rule

```
LAUNCHER_PPN = GPUS_PER_NODE / GPUS_PER_TASK          -n = LAUNCHER_PPN × N
```

**`GPUS_PER_TASK` must divide `GPUS_PER_NODE`.** GPUs are handed to workers in
contiguous blocks, so a task size that does not divide the node leaves devices
idle with no error at all. On `gpu-a100` (3 GPUs) that rules out 2 GPUs per task;
that shape belongs on `gpu-h100`, which has exactly 2.

`assets/gpu_dispatcher.sh` enforces this and refuses to start rather than
silently stranding hardware.

## Dispatch shapes

| Shape | GPUs/task | `LAUNCHER_PPN` | `-N` | `-n` | Use when |
|---|---:|---:|---:|---:|---|
| **A — farm** | 1 | 3 | k | 3k | many small independent jobs. Best throughput per node-hour |
| **B — memory** | 3 | 1 | k | k | one cell does not fit in a single GPU's memory |
| **C — parallel** | 3 | 1 | k | k | one job with enough k-points to split across GPUs |
| **h100 pair** | 2 | 1 | k | k | `gpu-h100` only — 2 GPUs/node divides exactly |

**B and C are the same plumbing.** They differ only in the calculation's own
parallel parameter — whatever that tool calls it — which belongs to that tool's
skill, not here.

### Choosing between them

**A is the default.** It is the only shape that scales linearly: N independent
tasks on N GPUs, zero communication, no idle devices.

**Reach for B or C only with a reason**, because giving one task the whole node
cuts your concurrency by the GPU count:

* **B — memory.** The cell overflows one card. You are buying *feasibility*, not
  speed: the job either runs or it does not.
* **C — parallelism.** The calculation has something real to split across cards.

The distinction matters because multi-GPU **speed** scaling and multi-GPU
**memory** relief are different things, and a code can offer one without the
other. Ask the tool's own skill which applies before choosing B or C — a code
that cannot decompose the work will take 3 GPUs and use one.


### Sizing `-N`

Tasks run in `ceil(Ntasks / (LAUNCHER_PPN × N))` waves. Pick `N` from the wave
count you want against the per-task runtime — then **check the queue before
committing**, with the `queue-wait` skill. On a backlogged partition a bigger
allocation can *finish later* despite running faster, because it waits longer for
a slot. Record the comparison and its date in the batch script's header comment;
a `-N` with no recorded reason is unreviewable six months on.

## The joblist

One line per task: the dispatcher, a task directory, an executable, and any
arguments that executable takes.

```
$LAUNCHER_WORKDIR/gpu_dispatcher.sh $LAUNCHER_WORKDIR/task-001 <executable> [args...]
$LAUNCHER_WORKDIR/gpu_dispatcher.sh $LAUNCHER_WORKDIR/task-002 <executable> [args...]
```

The dispatcher does not know or care what the executable is — it sets the
devices, the cores and the rank count, then runs what it was handed. Anything
tool-specific is job-level configuration in the batch script, not per line.

Two failure modes that produce wrong output rather than an error:

* **The file must end in a newline.** Without one the launcher never reads the
  last line, and that task simply does not run.
* **Pad with `/bin/true` when tasks < slots.** Launch 2 tasks into 3 slots and
  the launcher may duplicate one into the empty slot; the two copies then write
  to the same directory and clobber each other.

```
$LAUNCHER_WORKDIR/gpu_dispatcher.sh $LAUNCHER_WORKDIR/task-001 <executable>
$LAUNCHER_WORKDIR/gpu_dispatcher.sh $LAUNCHER_WORKDIR/task-002 <executable>
/bin/true
```

## The launch script

The dispatcher works out *where* a task runs. It does not decide *how to start
it*, because `mpirun`, `ibrun`, `srun` and "just run the binary" are all correct
answers depending on the toolchain, and none of them belongs to a launcher.

So every launcher job needs a **`launch.sh`** in `LAUNCHER_WORKDIR`, supplied by
the tool's own skill. The dispatcher calls it as

```
launch.sh <executable> [args...]
```

in the task directory, with the placement already exported:

| Variable | Meaning |
|---|---|
| `CUDA_VISIBLE_DEVICES` | the devices this task owns, e.g. `0,1,2` |
| `TASK_CORES` | the core range this task owns, e.g. `0-31` |
| `TASK_NRANKS` | how many devices it owns — the natural rank count |
| `OMP_NUM_THREADS` | threads per rank, passed through |

The dispatcher **computes** the core range; `launch.sh` **applies** it.
`numactl --physcpubind`, OpenMPI's `--bind-to core` and `srun --cpu-bind` are
three ways to do the same thing, and which is right is a toolchain fact.

**There is no default and no fallback.** A missing `launch.sh` is an error naming
the file. That is deliberate: a default would be some particular MPI's syntax,
and a tool that inherited it by accident would fail in a way that looks like a
cluster problem rather than a missing decision.

A `launch.sh` can be very small. For a single-process GPU code — a training
script, a CUDA program — the whole thing is:

```bash
#!/bin/bash
exec numactl --physcpubind=$TASK_CORES "$@"
```

`CUDA_VISIBLE_DEVICES` is already set, so the process sees only its own devices.

**This skill ships no `launch.sh`.** A generic "OpenMPI, one rank per GPU" script
here would just move the assumption rather than remove it. Each tool writes its
own when it is first used; today that is `vasp` (`assets/launch.sh`), and nothing
else.

## Assembling the batch script

Six blocks, in this order. **Only block 4 comes from this skill** — the others
are listed so the assembly order is visible, not so they are restated here.

| # | block | owned by |
|---|---|---|
| 1 | `#SBATCH` header — queue, `-N`, `-n`, `-t`, allocation | `prepare-node` -> `references/sbatch_header.md` |
| 2 | launcher module, then the tool's prerequisite | `reference/<cluster>-launchers.md` — **load order matters** |
| 3 | `LAUNCHER_WORKDIR` · `JOB_FILE` · `PPN` · `SCHED` | `reference/<cluster>-launchers.md` § Variables you set |
| 4 | **placement** | **this skill** |
| 5 | `TASK_STDOUT` · `TASK_DONE_CHECK` · `launch.sh` in `LAUNCHER_WORKDIR` | the packed tool's skill |
| 6 | `$LAUNCHER_DIR/paramrun` | `reference/<cluster>-launchers.md` |

Block 4 is the only one written from this skill's arithmetic:

```bash
export GPUS_PER_TASK=<n>     # must divide GPUS_PER_NODE -- see The one rule
export GPUS_PER_NODE=<n>     # reference/<cluster>-nodes.md
export CORES_PER_NODE=<n>    # reference/<cluster>-nodes.md
export OMP_NUM_THREADS=<n>   # threads per rank. gpu_dispatcher.sh assumes 32 if
                             # unset, and the core span is OMP x GPUS_PER_TASK --
                             # so leaving it unset sizes every block silently wrong
```

**Two cross-block constraints, both silent when broken:**

* `-n` in block 1 must equal `LAUNCHER_PPN × N` from block 3. The dispatcher
  checks `LAUNCHER_PPN` against `GPUS_PER_NODE / GPUS_PER_TASK` and refuses to
  start on a mismatch — but it cannot see `-n`.
* `TASK_DONE_CHECK` (block 5) is what makes resubmitting a whole joblist safe
  after a walltime kill: finished tasks skip themselves. Leave it unset and
  every task re-runs from scratch.

## Report block

**Additive, not a replacement.** A packed node's `tool` names the code being
packed (`vasp`), never this skill, so `prepare-node` shows that tool's
`## Report block` *and* this one — the tool's first, describing what a task
computes, then this one, describing how the tasks are placed. Neither is
complete on its own.

On top of the tool's block, §1 shows these, each justified:

| Item | Show |
|---|---|
| shape | A / B / C, and the reason it is not A |
| `GPUS_PER_TASK` · `LAUNCHER_PPN` | and that the first divides `GPUS_PER_NODE` |
| `-N` · `-n` | with the wave count, and the queue-wait comparison behind `-N` |
| task count | how many joblist lines, and the padding if any |
| per-task resources | GPUs and cores each task gets |
| executable + `TASK_*` | the binary, its args, and the two tool values |
| `launch.sh` | which tool supplied it, and how it starts the code |

Then: "everything else is the dispatcher's default."

## Variants

* **`references/gpu_launcher.md`** — how a task reaches a specific node and GPU,
  and the failures that produce silent wrong output. Read it before writing a
  multi-node launcher job.

## Bundled resources

- `assets/gpu_dispatcher.sh` — maps a worker slot to its GPUs and cores, skips
  already-finished tasks, and launches one. Copy it into the node directory
  during preparation; it runs on the cluster, not here.
  `gpu_dispatcher.sh <task_dir> <executable> [args...]`, reading `GPUS_PER_TASK`,
  `GPUS_PER_NODE`, `CORES_PER_NODE`, `LAUNCHER_PPN` for placement and
  `TASK_STDOUT`, `TASK_DONE_CHECK` and `launch.sh` from the calling tool. **It
  contains no knowledge of any specific code and no launch command**, which is
  what lets one dispatcher serve VASP, LAMMPS, Quantum ESPRESSO or a plain CUDA
  program without edits.

There is deliberately nothing else here. `launch.sh` belongs to the tool — see
`.claude/skills/vasp/assets/launch.sh` for the one that exists.

## Scope boundary

In scope: whether to pack, the dispatch shape, `LAUNCHER_*` sizing, the joblist,
and the dispatcher.

Out of scope: **queue, walltime, allocation** — `prepare-node` ->
`references/sbatch_header.md`. **Which executable, how
to start it (`launch.sh`), its parallel parameters, and how to tell a run
finished** — that tool's own skill;
this skill places tasks and knows nothing about what they compute. **Module paths
and GPUs per node** — `reference/taccLS6-launchers.md`.
