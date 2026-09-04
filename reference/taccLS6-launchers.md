# Launcher reference — TACC Lonestar6

Environment facts for packing many independent tasks into one SLURM job.
**How** to size and wire a launcher is the `launcher` skill; this file is only
what exists here and how it is invoked.

*Probed on Lonestar6 on **2026-08-30**. Re-check with [Verifying](#verifying) if a
module is updated.*

**Two kinds of section, and the difference decides who maintains them:**

| | holds | you must |
|---|---|---|
| **Fixed Pattern** | the module, its variables, the entry point | nothing — true for anyone using this module on LS6 |
| **Interactive Pattern** | how the launcher and a packed tool must agree | **add one subsection per tool you pack** |

## Availability

| Module | Version(s) | For |
|--------|-----------|-----|
| `launcher_gpu` | 1.2 | packing GPU tasks — one or more GPUs each |

There is no `module load` for a *dispatcher*: the script that maps a worker slot
to devices and cores is shipped by the `launcher` skill and copied into the node
directory.

## launcher_gpu

### Fixed Pattern

load the module

```bash
module load launcher_gpu
```

**Variables it sets:**

| Variable | Value |
|---|---|
| `LAUNCHER_DIR` | `/opt/apps/launcher_gpu/1.2` |
| `LAUNCHER_PLUGIN_DIR` | `/opt/apps/launcher_gpu/1.2/plugins` |
| `LAUNCHER_RMI` | `SLURM` |
| `TACC_LAUNCHER_GPU_DIR` | `/opt/apps/launcher_gpu/1.2` |

The launcher is started with **`$LAUNCHER_DIR/paramrun`**.

>[!WARN] The module's own help text names a variable that does not exist
>
>`module spider launcher_gpu` says the module "defines the environment variable
`$LAUNCHER_GPU_DIR`". **It does not.** The real names are `LAUNCHER_DIR` and
`TACC_LAUNCHER_GPU_DIR`. `$LAUNCHER_GPU_DIR` expands to the empty string, so
`$LAUNCHER_GPU_DIR/paramrun` silently becomes `/paramrun` and the job dies with
a confusing "not found".

#### Variables you set

| Variable | Meaning |
|---|---|
| `LAUNCHER_WORKDIR` | absolute path of the dir holding `joblist` and the dispatcher |
| `LAUNCHER_JOB_FILE` | the joblist, normally `$LAUNCHER_WORKDIR/joblist` |
| `LAUNCHER_PPN` | **worker processes per node** — not the total |
| `LAUNCHER_SCHED` | `dynamic` so a freed slot immediately takes the next task |

Set by the launcher, read by the dispatcher:

| Variable | Meaning |
|---|---|
| `LAUNCHER_TSK_ID` | global worker index, **fixed for that worker's lifetime** |
| `LAUNCHER_JID` | joblist **line** number — changes with every task the worker picks up |

### Interactive Pattern

> **FILL THIS IN — one subsection per tool you pack.** Nothing above depends on
> the tool; everything below does. These are the points where the launcher and
> the packed code must agree, and where disagreement is **silent** — the job
> starts, runs to completion, and is wrong.
>
> Delete this block once you have added your first tool.

#### Use with `<<TOOL>>`

**1. Load order.** `module load launcher_gpu` pulls in its own compiler, MPI and
python — `intel/19.1.1`, `impi/19.0.9`, `python3/3.9.7`. If `<<TOOL>>` needs a
different toolchain, whichever prerequisite runs **last** wins `$PATH`.

>[!NOTE] Load order against `<<tool prerequisite>>`
>
>```bash
>module load launcher_gpu        # first
><<tool prerequisite>>           # second, so it wins PATH
>```
>
><<State what reversing them does, in one sentence, because it raises no error.
>The genre: "the binary resolves to the wrong build, launched under the right
>dispatcher".>>

**2. The launch script.** The dispatcher places a task; it does not start it.
`launch.sh` comes from the tool's own skill, because `mpirun`, `ibrun`, `srun`
and "just run the binary" are all correct for different builds.

* `<<TOOL>>` → `<<path to its launch script, e.g. .claude/skills/vasp/assets/launch.sh>>`
* MPI flavour it must use: `<<OpenMPI | Intel MPI | srun>>` — from `reference/<<TOOL>>.md`

**3. `OMP_NUM_THREADS`.** The dispatcher's core span is
`OMP_NUM_THREADS × GPUS_PER_TASK`, so it must be set before `paramrun`.

* Does `<<tool prerequisite>>` set it for you? `<<yes, to N | no — export it in the .batch>>`

## Verifying

```bash
module avail 2>&1 | tr ' ' '\n' | grep -i launcher      # what exists
module load launcher_gpu && env | grep -i launcher      # what it really sets
ls $LAUNCHER_DIR/paramrun                               # the entry point
```

## Related

* Sizing, joblist contract, dispatch shapes and the dispatcher script — skill `launcher`
* Node hardware, GPUs per node, queue caps — `reference/taccLS6-nodes.md`
* Queue choice, `-N`/`-t`, allocation — skill `prepare-node` → `references/sbatch_header.md`
* The packed tool's builds and launch forms — `reference/<<TOOL>>.md`
