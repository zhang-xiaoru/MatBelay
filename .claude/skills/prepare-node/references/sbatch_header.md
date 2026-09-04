# Writing the `#SBATCH` header

How to choose the queue, the size and the walltime for one node's `.batch`
script. Read this when writing the header; it is not needed for the rest of
preparation, which is why it lives here rather than in `SKILL.md`.

Start from **`templates/job.batch`**. Hardware, queue caps and charge rates are
in **`reference/taccLS6-nodes.md`** — and the live scheduler beats that file, so
confirm anything near a cap with `qlimits`.

## What is already decided before you get here

`plan-computation` fixed `cluster`, `partition`, `num_nodes` and `request_time`
per node, probed the wait with the `queue-wait` skill, and recorded them as
DAG fields. **Read them from the DAG rather than re-deciding.** If they are
present and plausible, your job is to transcribe them into the header, not to
re-litigate the plan.

Re-open the sizing only when the plan's assumption has since been falsified —
the cell got bigger, the displacement count came in higher than expected, the
run mode changed. Then say so explicitly, because the DAG says otherwise and
someone will read it.

## The four values

### `-p` — the queue

From `reference/taccLS6-nodes.md`. Two facts drive the choice:

* **caps**: a queue you exceed is not a candidate. `development` stops at 2 h.
* **charge rate**: a GPU node bills ~4× a CPU node, so an under-filled GPU node
  is expensive as well as slow. That is what the `launcher` skill is for.

When two queues both fit, the tie-break is wait time, not preference — and the
probe is the `queue-wait` skill, live against the current queue. It is
pre-authorized — invoke it rather than asking first. Heuristics are a fallback,
and if you use one, say so.

### `-N` and `-n` — the size

`-N` comes from the plan. `-n` **does not come from here.**

`-N × cores_per_node` is the budget; how it divides into MPI ranks and threads
is a property of the code, not the hardware. Ask the tool's skill — for VASP,
`vasp` → `## Parameter rules`, which owns the rank/thread/`KPAR` protocol and
its divisibility constraint.

Two failure modes to recognise rather than to solve yourself:

* **one rank per core by default.** For a hybrid MPI+OpenMP build this starves
  each rank of memory and is usually slower than fewer, fatter ranks. If the
  tool's skill says hybrid, `OMP_NUM_THREADS=1` is a bug.
* **`-n` and `OMP_NUM_THREADS` disagreeing.** They are one coupled choice; if
  the script sets both and they do not multiply to the core count, cores idle.

### `-t` — the walltime

From the plan's runtime estimate, **padded ~25%**, and under the queue cap.

Both directions cost you. Too short kills the job mid-run and wastes everything
it had done. Too long delays the start: the scheduler backfills short jobs into
gaps, so an over-padded request waits behind work it could have run ahead of.

For a node the plan marks **continuable**, prefer a shorter `-t` and more rounds.
A round that ends on its walltime with progress is a normal, recoverable outcome
under `run-workflow`; one that dies at hour 40 of 48 is the same lost work with a
longer wait attached.

### `-A` and the rest

Allocation `<ALLOCATION>` or `<ALLOCATION_2>`; mail to `you@your.institution.edu`; `-J` the
node name; `-o`/`-e` as `<name>.o%j` / `<name>.e%j`. All from `CLAUDE.md`, unless
the user overrides.

**Keep the `.e%j` spelling.** Health probes read `*.e[0-9]*` for the failures
that never reach the code's own stdout — OOM kills, MPI aborts, signals. Rename
it and those go unseen.

## Where the header stops

At the `#SBATCH` block. The `module load` lines and the launch command belong to
the tool's skill — look the node's `tool` up in `reference/quick-ref.md`. For a
job packing several tasks into one allocation, the joblist and dispatcher are the
`launcher` skill; it fixes `LAUNCHER_PPN`, and `-n` must match it.

One cross-check worth doing every time: on TACC, a CPU MPI job launches with
`ibrun`, never `mpirun`. `mpirun` in a CPU script is nearly always a GPU recipe
pasted into the wrong node type.
