---
name: prepare-node
description: >-
  Prepare ONE workflow-DAG node for execution: settle its remaining parameters,
  work out how the upstream node's output becomes this node's input, and write
  the run directory, inputs, batch script, a `pre_processing.sh` when the node
  needs one, and a NODE.md record. Use after the DAG exists and a node has been chosen — "prepare
  the relax node", "set up the inputs for stage 2", "write the batch script for
  ifc_dopant", or as step 3 of the computation orchestrator. Preparing does NOT
  require the node's parents to have run: its parameters are knowable in advance.
  This skill only prepares — it never uploads, never submits, and never touches
  `workflow_dag.json`. One node per invocation; the caller loops.
---

# Prepare one node

Turn a planned node into a directory that is ready to run.

**Prepare is not execute.** Preparing writes the node's directory, inputs, batch
script and `NODE.md`. A node whose parent has not run yet is still preparable —
its parameters are known in advance, and `NODE.md` records how the parent's
output will become this node's input.

Preparation stops at the written directory. **Nothing is uploaded, nothing is
submitted, and `workflow_dag.json` is not touched** — a node's status is a fact
about the graph and about jobs, and preparing changes neither. Running the node
is a separate act, driven by `NODE.md`.

**One node per invocation.** A caller preparing several nodes loops, approving
one at a time. That keeps each approval small enough to read properly, and means
a change to one node costs only that node.

## Before you start

Arriving from the orchestrator, you already hold what you need — `plan-computation`
has just read or written the DAG, the approved plan names this node's purpose,
and the tool list is in context. Do not re-read them.

Invoked directly instead, load first:

* the node's row in `project_workflow/<exploration>/workflow_dag.json` —
  `cluster`, `partition`, `num_nodes`, `request_time`, `prev`;
* its entry in the approved plan under `plans/<exploration>/`;
* what each parent produces (its run directory, or its plan entry if unrun);
* the tool(s) it needs, via `reference/quick-ref.md`.

## Step 1 — settle the remaining parameters

The plan already fixed the **task-specific** choices. Do not revisit them.

This step fixes the **general** ones, from the tool's own skill:

* its **Defaults** table, and its **Parameter rules** for anything that has to be
  derived from the structure or the chosen potentials (for VASP, `ENCUT` is such
  a value);
* the **parallel parameters**, from this node's `partition` and `num_nodes`
  together with the tool's sizing protocol.

`AskUserQuestion` where the choice is genuinely open rather than derivable — the
tool's skill may mandate an approval step of its own — `vasp`, for instance,
requires the pseudopotential choice to be approved before proceeding. Honour
those rules rather than restating them here.

## Step 2 — pre-processing

What does this node need that a parent produces, and what turns one into the
other? Three cases, in increasing effort:

* **nothing** — a root node bringing its own structure;
* **a copy** — a file the parent produced becomes this node's input unchanged;
* **a transformation** — extract, modify, rebuild (substituting an element,
  building a supercell).

Anything past the first case goes into **`pre_processing.sh`** in the node
directory. Its contract is one sentence:

> **Leave the directory ready to submit, or exit non-zero.**

Start it with `set -eu` so a failed step stops the script instead of letting the
next one run on a file that was never produced. Success then *is* the
verification — the submitter needs no separate check, and needs to know nothing
about the tool.

Some inputs are **built on the cluster rather than written here** — anything
large, licence-restricted, or assembled from a library that already lives there.
Those are `pre_processing.sh` lines too.

**And some have to come back from the cluster.** When this node consumes a file a
*remote* parent produced, name the files — in `NODE.md`'s `## From upstream`
table, below. Which files is a **task** question, not a tool question: no local
node here reads a raw VASP output, and two VASP parents of one child routinely
hand over different filenames (`SPOSCAR` from a farm with a supercell,
`POSCAR` from one where `dim = 1 1 1` makes the POSCAR *be* the supercell). You
are the one who knows which, because you have just settled the parameters.

Name files, never a directory — see `.claude/rules/tacc-fetch-rule.md`.

**When there is nothing to do, write no file.** An empty `pre_processing.sh`
claims this node takes something from upstream when it does not; its absence is
the honest signal, and absence is exactly what the submitter tests for.

Write real, executable commands. This script runs later, on the cluster, driven
by someone who was not present for this conversation — so it can afford no
interpretation.

## Step 3 — post-processing

What does this node produce that its children consume, and what extracts it?
When extraction is needed, it goes in **`post_processing.sh`**, under the same
rules as above: `set -eu`, real commands, and no file at all when the node's
output is already the handoff.

A node whose output nothing reads is worth questioning before it is written.

## Step 4 — present the report

Fixed skeleton. Only §1 changes with the tool.

```markdown
# Prepare: <node name> — exploration <e>, id N, level L
Depends on: <parents>      Runs on: <cluster>/<partition>/-N × <time>

## 1. Main calculation
## 2. Pre-processing
## 3. Post-processing
## 4. Execution
## 5. From upstream
## 6. Gate
```

**§1 shows decisions, not file dumps.** A whole input file pasted in gets
skimmed; the handful of parameters that decide whether the run is right, each
with its justification, get read. Close it with "everything else is the template default"
so the reader knows nothing is hidden.

### Where §1's shape comes from

Look up the tool in `reference/quick-ref.md` and open what it points at. **If the
tool's skill has a `## Report block` section, follow it exactly** — that section
defines what §1 must show for this tool, including which values it considers
review-critical every time. It is a template, not a suggestion: a reviewer who
knows the tool expects the same things in the same order on every node.

If the tool has no `## Report block`, do not block. Fall back to: list the input
files, show what differs from the tool's own defaults, and **say in the report
that no template exists for this tool**, so the reader knows the highlighting is
generic rather than curated.

That fallback is also the signal to write one — a tool used more than once earns
a `## Report block` in its skill.

**A packed node has two report blocks, and needs both.** When this node's job
dispatches several tasks through a launcher, §1 shows the tool's block **and**
the `launcher` skill's `## Report block`, in that order — what each task computes
first, then how the tasks are placed.

Look this one up by the node's *dispatch*, not by its `tool` field. A launcher
job's `tool` is the packed code (`vasp`), never the launcher, so resolving from
`tool` alone reaches the tool's block and silently misses the placement one —
and `-N`, `LAUNCHER_PPN`, the wave count and the per-task GPU/core split are
exactly the values a reviewer cannot re-derive from the inputs. The two blocks
are additive, not alternatives: neither is complete for a packed node.

Iterate with the user until approved, then `ExitPlanMode`.

## Step 5 — write the files

Write them yourself, immediately after approval. Do not delegate this to a
subagent: a fresh subagent inherits none of this conversation — not the approved
values, not the tool's defaults, not its templates — so it would have to
*reconstruct* the inputs from the report. The report deliberately shows decisions
rather than whole files, so that reconstruction is exactly where an approved
value silently becomes a different one. You already hold every decision; writing
takes seconds.

Create `implementation/<exploration>/<level>_<id>_<name>/` — a flat sibling,
never nested inside another node's directory — and write:

* the main calculation inputs, from the tool's templates, with the approved values;
* the `.batch` script from the report's Execution section — start from
  `templates/job.batch`; choosing the queue, size and walltime is
  `references/sbatch_header.md`;
* `pre_processing.sh` / `post_processing.sh` — **only if the node needs them**;
* `NODE.md`.

**Copy in any skill-bundled script the node needs.** A script that has to run on
the cluster is copied from its skill into the node directory during preparation
and travels with the node — there is no shared remote helper directory to keep in
sync. The skill's copy is the source of truth; the node's copy is the version
that actually ran, which is what makes a finished run reproducible months later.

Keep every inline `#` rationale the report carries. Those comments are why the
file can be reviewed months later, and they cannot be recovered from the values.

Then stop. The node is prepared and its status is unchanged.

## Bundled resources

- `references/sbatch_header.md` — how to choose `-p`, `-N`, `-t` and the rest of
  the `#SBATCH` block, and where `-n` comes from. Read when writing the header;
  not needed for the rest of preparation.

Outside this skill but used constantly: `templates/job.batch` (the skeleton),
`reference/taccLS6-nodes.md` (node sizes, queue caps, charge rates), and
`reference/quick-ref.md` (which skill owns which tool).

## The node directory

Fixed names, so that whatever runs the node afterwards needs to know nothing
about the tool.

| File | Required | What it is |
|---|---|---|
| `NODE.md` | **yes** | the record. Its presence is what marks the node prepared — `check_dag.py` reads exactly this |
| `<name>.batch` | **cluster nodes** | the SLURM script |
| `run.sh` | **`cluster: local` nodes** | how this node runs on this machine, in one command. Fixed literal name — see below |
| `pre_processing.sh` | only if needed | leaves the directory ready to submit, or exits non-zero |
| `post_processing.sh` | only if needed | runs once the job has completed |
| `launch.sh` | launcher jobs only | how the tool starts one packed task — supplied by that tool's skill |
| the tool's inputs | — | whatever that tool needs |

Everything tool-specific lives *inside* those scripts. That is what lets one
submitter serve every tool: it runs `pre_processing.sh` **by name** and never has
to recognise a filename or parse a command out of prose.

### `run.sh` — the local node's entry point

A node with `cluster: local` gets no `.batch` and never reaches a queue. It gets
`run.sh` instead, with the same shape of contract as `pre_processing.sh`:

> **Produce this node's outputs in this directory, or exit non-zero.** Start with
> `set -eu`.

Usually one or two lines — `python build_dphi.py`, `python plot_kappa.py` — but
write it even then. `local-node` runs it **by name**, exactly as `submit-node`
submits a `.batch` by name, and that is what lets one runner serve every kind of
local node without recognising a filename.

A **fixed literal** `run.sh`, not `<name>.sh`. The variable-named `.batch` already
forces `submit-node` to read a filename off the directory; a name being invented
now should not inherit that.

Unlike `pre_processing.sh`, it is **not optional**. "Write no file when there is
nothing to do" does not extend here: a local node with nothing to run is not a
node. Its absence is what `local-node` tests to decide it was handed the wrong
kind of node.

Assume nothing about the environment: `local-node` caps threads to this machine's
budget and runs under a wall-clock limit, so `run.sh` should not spawn its own
parallelism or expect a long time to finish.

**The health probe is not a node artifact.** It lives in the tool's own skill and
runs locally against the node's remote directory — see `scripts/probe_generic.sh`
and, for VASP, `.claude/skills/vasp/scripts/probe.sh`. Keeping it out of the node
is deliberate: a probe copied in at preparation time would have its error
signatures frozen, while a local one applies a newly-learned signature at the
next poll, including to jobs already running.

## NODE.md

The **record** — not an executable. The scripts are the truth about what runs;
`NODE.md` says what this node is, what it takes from upstream, what it hands
downstream, and how you would know it worked.

The section headings are fixed for every tool; only what fills them changes. The
example below is a VASP node — read the shape, not the filenames.

```markdown
# <node> — id N, level L
Depends on: <parent> (#id)

## Inputs written here
INCAR, KPOINTS, run.batch — ready as written, need nothing from upstream.

## From upstream
`CONTCAR` from `1_1_relax_dopant` becomes `POSCAR`, with Ti→Nb substituted at site
71 and expanded to a 3×3×5 supercell. POTCAR is assembled on the cluster.
Performed by `pre_processing.sh`.

| from node | file | why |
|---|---|---|
| `1_1_relax_dopant` | `CONTCAR` | the relaxed geometry this node substitutes into |

## Main
    sbatch run.batch          # a cluster node
    bash run.sh               # a cluster: local node

## Produces
`FORCE_CONSTANTS`, extracted by `post_processing.sh`. Consumed by `3_4_dphi_extract`.

## Expected
~540 atoms, ~80 irreducible displacements, 4 nodes × 8h

## Gate
**objective** — the calculation completes without error.
```

**The `## From upstream` table is what a fetch is built from.** Include it
whenever this node reads a file a remote parent produced: one row per file, with
the producing node and one clause of justification. Omit the table entirely when
the node takes nothing from a remote parent — absence is the honest signal, the
same way a missing `pre_processing.sh` is.

The justification column is not decoration. `SPOSCAR` vs `POSCAR` from two
otherwise identical IFC farms is the kind of choice that looks like a typo six
months later, and the one clause explaining it is what stops someone "fixing" it.

**Describe the scripts; do not restate them.** If `NODE.md` also carried the
commands, the two could disagree — and a reader has no way to tell which one the
job actually ran. Name the script and say what it accomplishes.

**Expected** and **Gate** are what a later check compares reality against —
specifically `run-workflow`, which reads the `## Gate` section to decide
`completed` vs `failed`, and whether it may proceed without asking.

## The gate

**Default: the calculation completes without error.** Write that sentence
explicitly rather than leaving it implied.

A bespoke gate replaces the default only when the plan or the user supplies one
— *e.g. for a VASP relax, "max force < 5 meV/Å"; for a phonon node, "ΔΦ decays
before the supercell boundary"*. Do not invent scientific criteria — record the
one you were given, or the default.

How a gate is *evaluated* belongs to the tool and to whatever checks results
later. This skill's job is to write it down — and to say which **kind** it is.

### Mark the kind: objective or judgement

Every gate is one of two things, and the difference decides whether a run driver
may proceed past it on its own. Write the marker in bold as the first thing in
the `## Gate` section:

| Marker | Means | Examples |
|---|---|---|
| `**objective**` | a machine can decide it — a threshold, a flag, a count, a file that exists | "completes without error"; "max force < 5 meV/Å"; "a = 4.33 ± 0.02 Å" |
| `**judgement**` | deciding it means *reading* a result | "ΔΦ decays to ~0 before the boundary"; "no imaginary modes"; "τ⁻¹ → 0 as V → 0" |

`run-workflow` proceeds automatically past an objective gate and **stops** at a
judgement gate to show the user the evidence. An unmarked gate is treated as
judgement — the safe direction, and the one that gets the marker added.

The test is not how hard the criterion is, but whether two careful people would
reach the same verdict from the same file. "Three short bonds and one long"
is objective despite having no number in it; "the decay looks clean" is not.

### Iterative nodes: declare it continuable, and give the numbers

A node meant to run in rounds — a large-cell relax, a long MD — needs one more
thing, or a run driver cannot continue it without inventing a decision.

**Do not restate the mechanics here.** How continuation works for a given code —
which files hand over, what the progress metric is, which setting a next round
may switch — belongs to that tool's skill, under its `## Success check`, question 4 (for
VASP: `references/success_check.md`).
Copying it into `NODE.md` creates a second copy that will drift, and the drifted
one is the one a driver reads.

`NODE.md` carries what is specific to *this node*: the numbers.

```markdown
## Gate
**objective** — max force < 5 meV/Å.

### Continuation
Continuable — recipe: skill `vasp`, `references/success_check.md` §4.
Force gate 0.005 eV/Å. Round budget 3. Round 1 is CG; later rounds follow §4.
```

Same split as every other parameter: **the skill holds the rule, `NODE.md` holds
the value.** A driver reads both — the tool's skill to know what a round change
may be, this file to know which one applies here.

**If the tool's skill has no question 4, do not mark the node continuable.**
"Continuable" with nothing behind it is worse than nothing: it invites a driver
to choose parameters, which is precisely what a continuation exists to avoid. An
unmarked node stops and asks, which is the correct outcome.

## Adding a tool

This skill does not change when a tool is added. A new tool needs its own docs to
answer three questions, and §1 works for it:

1. Which files are the main calculation?
2. Which few parameters decide whether this run is right?
3. What does each of them get justified against — a convergence test, a paper, a
   gate, a hardware limit?

## Scope boundary

In scope: one node's remaining parameters, its `#SBATCH` header, its
pre/post-processing, its files and its `NODE.md`.

Out of scope: **what the nodes are and how they depend on each other** —
`plan-computation`. **Writing `workflow_dag.json`** — `workflow-dag`. **Tool
defaults and parameter rules, including `-n` and the thread count** — that tool's
own skill. **Packing several tasks into one job** — `launcher`.
