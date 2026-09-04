---
name: vasp
description: >-
  Choose VASP parameters and generate VASP input files for condensed-matter /
  computational-materials calculations. Holds the default INCAR settings used
  here, the rules for deriving ENCUT / KPAR / NCORE / OMP_NUM_THREADS / NSIM for a
  given machine and system size, the standard patterns for POSCAR, POTCAR and
  KPOINTS, and how to tell a finished run actually succeeded. Use whenever a task
  needs VASP inputs written or a VASP parameter decided — "set up an INCAR", "make
  VASP inputs for this structure", "what KPAR should I use", "how many OpenMP
  threads for a 216-atom cell", "did this relax converge" — do not wait for the
  user to name the skill. Environment facts (which builds exist, their
  prerequisites, launchers, node layout, recommended per-cluster values) live in
  `reference/VASP.md`, not here. This skill does NOT choose the queue, node count
  or wallclock — that is `prepare-node`.
---

# VASP: defaults, parameter rules, input generation

This skill is *how we do VASP* — the parameter values preferred here, the rules
for deriving the rest, and the standard shape of each input file.

It deliberately holds no environment facts. Where the builds are, what to load
before running, which launcher to use, how many cores a node has, and the
per-cluster recommended values are all in **`reference/VASP.md`**. That split is
what lets someone else adopt these conventions on a different machine by
replacing one file.

## Defaults

Starting values for a standard calculation. Override deliberately, and say why in
the node's report — an overridden default should never be silent.

| Tag | Default | Note |
|-----|---------|------|
| `ENCUT` | **1.25 × max ENMAX** over the POTCARs in use | derived per structure, not a fixed number. Get the ENMAX values by running `scripts/query_enmax.sh` on the cluster **while preparing the node** — it reads them from the library directly, so it needs neither an assembled POTCAR nor a POSCAR. Round up to a clean value and **pin it across every node whose results get differenced** — an IFC difference only cancels if the basis is identical. |
| `ALGO` | `Normal` | |
| `NELM` | `300` | |
| `EDIFF` | `1E-6` | electronic convergence |
| `ISMEAR` | `0` | Gaussian smearing |
| `SIGMA` | `0.05` | |
| `EDIFFG` | `-0.05` | force criterion for ionic relaxation |

## Parameter rules

### `KPAR` — k-point groups

`KPAR` is the number of k-point groups worked on simultaneously; each group
handles one set of k-points. The MPI ranks working on each k-point are
`total_mpi_ranks / KPAR`, so **`total_mpi_ranks` must be an integer multiple of
`KPAR`** — otherwise the ranks cannot split evenly into groups.

### Pure-MPI CPU VASP

* `NCORE` — MPI ranks working on a single band, parallelising the FFTs.
* `NPAR` — bands treated in parallel. Do not set it when `NCORE` is set; prefer
  `NCORE`. (`NPAR = per_k_mpi_ranks / NCORE`.)

In a pure-MPI build, run **one MPI rank per physical core**.

**Protocol**
1. Set total MPI ranks = number of physical cores.
2. Pick `KPAR` and `NCORE`.
3. Check `total_mpi / KPAR` is an integer multiple of `NCORE` — equal is allowed
   but not recommended.

A larger system generally wants a larger `NCORE`. Recommended values are
cluster-specific; take them from `reference/VASP.md`.

### MPI + OpenMP hybrid CPU VASP

Set `$OMP_NUM_THREADS` instead of `NCORE`. It is the number of OpenMP threads in
one MPI rank — the hybrid equivalent of `NCORE`. Setting it to `1` reduces the
build to a pure-MPI scheme.

Threads are bound one per physical core, so
**`total_mpi_ranks × $OMP_NUM_THREADS = physical cores`**.

**Protocol**
1. Pick `$OMP_NUM_THREADS`.
2. Set total MPI ranks = physical cores / `$OMP_NUM_THREADS`.
3. Pick `KPAR`, with total MPI ranks an integer multiple of it.

A larger system wants more threads per rank, which means less MPI parallelism.
Cores per node and recommended thread counts are in `reference/VASP.md`.

### GPU VASP

The heavy work runs on the GPU, so beyond `KPAR` only `NSIM` controls
parallelism. `NSIM` is how many bands are worked on simultaneously per k-point —
higher can cut runtime but needs more VRAM. **One MPI rank drives one GPU card.**

**Protocol**
1. Determine the total number of MPI ranks (= GPUs available).
2. Pick `KPAR`, with total MPI ranks an integer multiple of it.
3. Pick `NSIM` per k-point.

Recommended `NSIM` per cluster is in `reference/VASP.md`.

**`KPAR = 1` across several GPUs is legitimate when the reason is memory.** A
Γ-only cell has one k-point, so `KPAR` can only be 1 — but the wavefunctions
still distribute over the ranks, which is what lets a cell too large for one
card's memory run at all. Expect capacity, not speed: roughly 2–2.5× usable
memory from 3 GPUs (grid and charge-density arrays are partly replicated per
rank), and little acceleration, since band and plane-wave parallelism scale
poorly in the GPU port. Lower `NSIM` when VRAM is the binding constraint.

## Fixed patterns

### POSCAR

* **Fresh structure** — If the Material Project API exists, use the structural data from the Materials Project database via `pymatgen`, and **keep the generation script**
  so the structure is reproducible. Other wise, use experimental parameters.
* **User-specified or experimental parameters** — build the cell from those
  values instead.
* **Continuing from an upstream node** — the structure comes from the parent's
  `CONTCAR`. <!-- STUB: standard conversion pattern not yet written -->

### POTCAR

POTCAR is **assembled on the cluster at run time**, not written during
preparation and not uploaded — the library is already there, and the files are
large and licence-restricted.

Use `scripts/generate_POTCAR.sh`. Copy it into the node directory while preparing
the node, and put its invocation in that node's `pre_processing.sh`:

```bash
./generate_POTCAR.sh --library <library path from reference/VASP.md> \
                     --species "Ti_pv Nb_pv O"
```

The library path is deliberately **not** built into the script — it is a site
fact, and it lives in `reference/VASP.md`. Pass it in full, so the node's
`pre_processing.sh` records which library actually produced the POTCAR.

**The species list is explicit, including semicore variants, and this matters.**
POSCAR line 6 carries bare element symbols, so a script that derives the list
from POSCAR silently builds `Ti` when `Ti_pv` was approved — no error, and a
POTCAR that is wrong in a way nothing downstream detects. The script therefore
takes the approved list as an argument and uses POSCAR only to *verify* it:
species count and each entry's base element must match, in order, or it refuses
to write.

It prints the `TITEL` of each species it used, so the run directory documents
its own basis. It does **not** report `ENMAX` — `ENCUT` is decided at prepare
time by `scripts/query_enmax.sh`, long before this runs. See the `ENCUT` row of
the Defaults table.

The pseudopotential choice materially affects the result, so **ask the user to
approve it before proceeding**, and record the library and the exact variants.
Library locations and available functionals are in `reference/VASP.md`.

### KPOINTS

**Monkhorst-Pack mesh by default.**

Switch to Gamma-centred when the mesh must contain Γ. At 1×1×1 the two schemes coincide, so a Γ-only run can be written
either way.

Line 1 of the file carries the mesh *and* its justification, the same rule the
INCAR follows.

## Writing the files

INCAR and KPOINTS are written **by hand from the templates**, not generated.

The reason is that the justification is the point. An INCAR here carries an
inline `#` comment on every value that is not a default — why this `ENCUT`, why
`ISYM = 0`, why `GGA` is deliberately unset. That reasoning is what makes the
file reviewable later and what tells a reader whether two nodes can legitimately
be differenced. A generator emits `TAG = value` and cannot produce it.

**The rule:** every value that differs from the default, and every deliberate
omission, carries an inline rationale. A tag a reader could question and you
cannot explain is not finished.

Two ordering traps worth stating, because they are silent when wrong:

* `MAGMOM` takes one value per atom **in POSCAR species order** — write the
  species counts in a trailing comment (`# Ti(71) Nb(1) O(144)`) so the ordering
  can be checked by eye.
* POTCAR is concatenated in that **same** species order.

Start from `assets/INCAR.template` and `assets/KPOINTS.template`. Copy, fill the
`<<...>>` slots, delete what does not apply.

One INCAR template covers every calculation done here, because the electronic,
spin and parallel blocks are identical across them — only the **run mode** block
changes. It holds four variants (relax / single-point forces / DFPT / DOS); keep
one and delete the rest. Keeping them side by side means choosing is a read
rather than a recall.

A second template would be earned by a mode that changes the *electronic* block —
a non-SCF band structure along a k-path, or a hybrid functional. Not by another
ionic setting.

## Report block

What §1 of a `prepare-node` report must show for a VASP node. Follow this shape
every time — a reviewer who knows VASP should find the same things in the same
order on every node, so a missing one is visible.

### Structure
Formula, atom count, cell, and what it was built from.

### KPOINTS
Mesh and scheme, with the one-line justification.

### POTCAR
The full spec, exactly as it will be built: library, then species **with variants,
in POSCAR order** — e.g. `potpaw_LDA.52 :: Ti_pv Nb_pv O`. A bare element list is not
enough: `Ti` and `Ti_pv` are different calculations, and the variant is the part
that needs approving.

### Run mode
`relax` | `single-point forces` | `DFPT` | `DOS`

### INCAR — review-critical tags only

| tag | value | why this value |
|-----|-------|----------------|

Include a tag when it (a) differs from the **Defaults** table above, (b) is
derived from this particular structure, or (c) has to match another node.
Everything else is the template default — say so explicitly and give the path to
the full file, so the reader knows nothing is being hidden.

**Always include these four**, because they are where a VASP node silently goes
wrong and a reader cannot infer them:

* **`ENCUT`** — and whether it is *pinned* to another node. A difference of two
  results only cancels if the basis is identical, so this is the tag most worth
  stating even when it equals the default.
* **`ISYM`** — a defect or displacement that breaks symmetry needs `ISYM = 0`;
  leaving the default silently symmetrises the forces.
* **`ISPIN` with `MAGMOM`** — including the species-count comment that makes the
  POSCAR ordering checkable by eye.
* **the run-mode block** — `IBRION`/`NSW` decide whether this is a relaxation or
  a single point at all.

### Example

```
POSCAR   Nb_Ti r-TiO2 3x3x4, 216 atoms, lattice fixed to pristine
KPOINTS  1x1x1 Gamma (supercell; matches the 5x5x7 IFC baseline)
POTCAR   Ti Nb O  (LDA, POSCAR order)
Mode     relax

| tag    | value               | why |
|--------|---------------------|-----|
| ENCUT  | 600.0               | pinned to the pristine run so dPhi cancels |
| ISYM   | 0                   | defect breaks symmetry |
| ISPIN  | 2                   | Nb is a single donor -> odd electron count |
| MAGMOM | 71*0.0 1.0 144*0.0  | Ti(71) Nb(1) O(144), POSCAR order |
| ISIF   | 2                   | ions only, cell fixed to pristine |

Everything else is INCAR.template's default. Full file: inputs/INCAR
```

## Success check

How to tell a finished VASP run actually succeeded — the default gate for a node
whose plan does not state a bespoke one.

**A clean SLURM exit is not the answer.** VASP exits 0 after hitting its ionic
limit with forces nowhere near the target, so `sacct` saying `COMPLETED` and the
run being usable are different claims. The canonical case on record: a relax
"completed" at `NSW=200` with max force ~49 meV/Å against a 5 meV/Å gate.

**This heading is a contract.** `run-workflow` is tool-free — it knows a result
must be judged and nothing about how — so it reads four questions from here and
acts on the answers:

| | Question | The driver's response |
|---|---|---|
| 1 | did the job exit cleanly? | no → stop the branch |
| 2 | did it meet its criterion? | yes → `completed`, proceed |
| 3 | if not — **budget** or **failure**? | failure → stop. Budget → question 4 |
| 4 | what is the progress metric, what carries over to the next round, and what changes? | the continuation recipe |

**VASP's answers: `references/success_check.md`.** Read it when a job has
finished; it is not needed to write inputs, which is the rest of this skill.

Adding a tool means writing its own answers to those four. Missing them is not a
degraded mode — a driver that cannot evaluate a gate **stops**, because inventing
a criterion produces a result that looks fine and is not.



## What goes in `pre_processing.sh`

`prepare-node` writes a node's tool-specific setup into a fixed-name
`pre_processing.sh`, whose contract is: **leave the directory ready to submit, or
exit non-zero.** Whatever runs the node afterwards executes it by name and knows
nothing about VASP — so everything VASP-specific has to be in here.

Write no file at all when the node needs nothing from upstream and nothing built
on the cluster. Absence is the signal that this node is self-contained.

Start with `set -eu`, so a failed step stops the script rather than letting the
next one run on a file that was never produced.

```bash
#!/bin/bash
set -eu

# 1. structure from the parent
cp ../1_1_relax_dopant/CONTCAR POSCAR

# 2. transform it (only if the node needs a different cell)
python3 ../helper/build_supercell.py --in POSCAR --dim 3 3 5 --out POSCAR

# 3. POTCAR — assembled here, never uploaded: licence-restricted, ~700 KB,
#    and the library already lives on the cluster
./generate_POTCAR.sh --library <path from reference/VASP.md> \
                     --species Ti_pv O --out POTCAR
```

Three VASP-specific things worth stating, because they are what a generic
submitter cannot know:

* **POSCAR usually comes from a parent's `CONTCAR`**, not from a file written at
  prepare time. A relax hands its relaxed structure to whatever follows.
* **POTCAR is built here, not shipped.** `generate_POTCAR.sh` is copied into the
  node directory during preparation and runs on the cluster. It verifies the
  species against POSCAR and fails before writing if they disagree — which is why
  no separate check is needed afterwards.
* **`ENCUT` is not computed here.** It was fixed at prepare time by
  `query_enmax.sh` and is already in the INCAR. Recomputing it at run time could
  silently change the basis between two nodes whose results get differenced.

## What goes in `post_processing.sh`

Only what a *child node* consumes. Write no file when the output is already the
handoff — a following node that just needs `CONTCAR` reads it directly.

Typical: extract force constants, pull energies or forces into a small summary
the next node reads. Keep whatever it emits small: a downstream node reading a
number is cheap, and a large VASP output crossing into an agent's context is not.

## Bundled resources

- `assets/INCAR.template` — one fill-in INCAR covering all four run modes.
- `assets/KPOINTS.template` — fill-in KPOINTS.
- `scripts/query_enmax.sh` — read ENMAX for a species list straight from the
  library and report the resulting ENCUT. Run it on the cluster **at prepare
  time**; needs no POSCAR and no assembled POTCAR. Does not ship with the node —
  its answer is baked into the INCAR.
- `scripts/generate_POTCAR.sh` — assemble POTCAR on the cluster from an explicit
  species list, verified against POSCAR, at **run time**. Builds and verifies
  only; ENMAX is `query_enmax.sh`'s job. Copy it into the node directory during
  preparation; it runs there, not here.
- `assets/launch.sh` — starts VASP for one packed task when this node runs under
  a launcher.
- `references/success_check.md` — the four-question verdict on a finished run:
  clean exit, criterion met, budget-vs-failure, and the continuation recipe.
  Read at **judgement** time, not while writing inputs.
- `scripts/check_forces.py` — max/RMS force from the **last** ionic step of an
  OUTCAR, read from a 1 MiB tail so it is safe on a multi-GB file. Exit 0 if
  under `--tol`, 1 if not. This is the measurement the `## Success check` turns
  on, and the metric a multi-round relaxation compares across rounds. Runs
  **locally or on the cluster**, against a finished run; does not ship with the
  node. *(Moved here from `implementation/helper/` — a skill must not depend on
  a file in the data half of the repo.)*
- `scripts/probe.sh` — error probe for a running VASP job, run **locally** by
  `scripts/watch_jobs.sh` against the node's remote directory. Emits `ERROR=`
  and `WARN=`, each attributed to the file it came from — which for a launcher
  job names the failing task directory. Reads bounded tails of `vasp.out`,
  `*/vasp.out` and the SLURM `.e` file in one round trip; OUTCAR and OSZICAR are
  never touched. **This is where VASP failure signatures accumulate** — add a
  newly-learned pattern to its `FATAL` / `CONCERN` lists and it applies at the
  next poll, including to jobs already running. Does not ship with the node.

  It reports what VASP *said*, never what a counter implies. There is no
  progress metric and no hang detection: how long a healthy step takes depends
  on the cell, the calculation type and the hardware, so any fixed threshold
  gives false alarms on a slow linear-response step and useless slack on an MD
  run. A job that hangs silently is caught by SLURM at walltime, as `TIMEOUT`.

## Interactive patterns
This records the patterns needed when VASP has to interact with another tool.

### Use with Launcher

The `launcher` skill's dispatcher is tool-agnostic — it places tasks and runs
whatever binary it is handed. VASP supplies the two values it needs, exported in
the batch script alongside the placement variables:

```bash
export TASK_STDOUT=vasp.out
export TASK_DONE_CHECK='grep -q "reached required accuracy\|General timing" OUTCAR'
```

VASP also supplies the **launch**: copy `assets/launch.sh` into the node
directory, serves as a tool specific running script for the writting `launcher_gpu` script. 

`TASK_DONE_CHECK` is what makes resubmitting a whole joblist safe after a
walltime kill: an already-finished displacement skips itself instead of starting
over. It is deliberately **only question 1** of the success check — one `grep`,
run per task at launch — because it answers "should I redo this task", not "is
this result good". A task that exits cleanly with unconverged electronics passes
`TASK_DONE_CHECK` and still fails the gate, which is correct: the launcher should
not redo it, and the gate should still reject it.

## Scope boundary

In scope: VASP parameter defaults and the rules for deriving the rest, input-file
generation, and how to tell a run succeeded.

Out of scope: **environment facts** (builds, prerequisites, launchers, node
layout, per-cluster recommended values) — `reference/VASP.md`. **Queue, node
count and wallclock** — `prepare-node` -> `references/sbatch_header.md`. When a
full `.batch` is needed, this skill supplies the parallel parameters and
`prepare-node` owns the `#SBATCH` header.
