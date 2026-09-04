---
name: plan-computation
description: >-
  Decompose a computation task into a high-level workflow DAG and record it, so
  the work can later be prepared and executed node by node. Use this whenever the
  user brings a computation they want done — "calculate the thermal conductivity
  of X", "I want to run defect scattering for Nb_Ti", "set up the workflow for
  this paper's method", "here's a plan file, turn it into stages" — and also when
  they want to extend an exploration that already exists ("add a convergence
  check", "we also need the 3x3x5 supercell"). Takes a task description or a file
  summarising one. Works in plan mode: it proposes the stage breakdown, the
  dependencies, where each stage runs, and the job-dispatch strategy, iterates
  with the user until approved, then hands the result to the `workflow-dag` skill
  to write `workflow_dag.json`. It decides the GRAPH only — no input files, no
  submission script, no submission. Preparing individual nodes is the
  `prepare-node` skill's job; running them is `run-workflow`.
---

# Plan a computation as a workflow DAG

**Input:** `$ARGUMENTS` — a description of a computation task, or a file
summarising one (e.g. a methodology review or an existing plan document).

The output of this skill is an approved plan document plus a recorded DAG. No
input files, no batch scripts, no submissions — those come later, node by node.
Keeping this step to the graph is what makes it reviewable before allocation is
spent.

## The plan protocol

1. Deconstruct the task and determine the requirements
2. Learn the environment and tool conventions
3. `EnterPlanMode`, determine the workflow DAG
4. Size each remote node and probe the expected wait
5. Present the plan, iterate with the user until approved, then `ExitPlanMode`
6. Record the DAG using the `workflow-dag` skill

Before Step 1, settle **which exploration this belongs to.**

## Step 0 — fresh or continuation

List `project_workflow/` and decide whether this is a new exploration or work
added to one that exists. `AskUserQuestion` if it is ambiguous — guessing wrong
here is expensive in both directions.

**Fresh** — no exploration covers this task. Choose the exploration name now: it
names the DAG directory, the `implementation/<exploration>/` tree, and the
`exploration` key inside the JSON.

**Continuation** — the exploration exists. Before planning anything, read its
`workflow_dag.json` and summarise for the user which nodes are `completed`,
`failed`, `terminated`, and which are still `pending`/`ready`. Then plan **only
the delta**: if a step you were about to propose already exists as a node, reuse
that node as a parent instead of proposing it again. A continuation may add new
downstream work, or replace a node that has been judged invalid — say which.

## Step 1 — deconstruct the task

Understand the goal first, then break it into practical computing steps. For each
step, determine which computation tool it needs.

Tools can be established software (VASP for DFT, LAMMPS for MD, phonopy for
phonons, ShengBTE for transport) or a language and its packages (python + numpy
for a custom solver). Both count — a node that runs a python script is still a
node.

For each step decide **where it runs**: locally, or on a remote cluster. Drive
this from the actual cost, not habit — a two-minute post-processing script does
not belong in a queue, and a 200-atom SCF does not belong on a laptop.

## Step 2 — learn the environment and conventions

Knowing *what* tool you need is not enough to plan well; you also need to know how
that tool is invoked here and how it parallelises, because those change the shape
of the graph. A tool that packs 80 displacements into one launcher job produces a
different DAG than one that needs 80 separate jobs.

Start from `reference/quick-ref.md` at the repo root. It lists every tool this
setup can plan against and points at where each one is documented — the tool
references live outside the skills so they can be swapped for another site's
conventions without editing a skill. For each tool the task needs:

1. **Look it up.** A tool listed there is available; one that is not cannot be
   planned against — **stop and report to the user** rather than assuming it
   exists somewhere. A plan built on a missing tool wastes the whole review cycle.
2. **Read what it points at** — the tool's environment conventions, and its skill
   if it has one — a tool's skill is where its parallelisation judgement lives,
   which you need in Steps 3 and 4. That destination is also where the check for "is it really
   installed" lives, if the plan hinges on it.

## Step 3 — determine the DAG
`EnterPlanMode` from here.

Decide the workflow structure.  Three things drive it:

* **Computing logic** — the input/output dependencies. A node's parents are
  whatever produces the files it consumes.
* **Parameter and method choice** — different parameters and methods change
  runtime by orders of magnitude, which changes what is worth splitting.
* **Queue behaviour and dispatch** — how jobs are packed affects both wall-clock
  and how long you wait for them.

### What the plan states about each node

* **level** — its depth in the DAG; nodes that can run in parallel share a level.
* **id** — an integer identity, starting from 0.
* **relation** — the dependency structure, expressed as each node's parents.

State level and id in the plan so the layout is readable, but treat the
**relation** as the authoritative part. When the DAG is recorded in Step 6,
`workflow-dag` derives the final id and level from the structure — so name parents
explicitly and do not fight the values it assigns. On a continuation, ids continue
from the existing graph rather than restarting at 0.

### Plan nodes according to SLURM dispatch

One node holds one SLURM job. That does not mean one node holds one *computing
task* — a launcher can dispatch a list of jobs inside a single SLURM job.

**Parallel jobs via launcher.** A launcher submits many tasks in one SLURM job.
Prefer it when:

* several independent jobs exist,
* they are similar and share a similar expected runtime,
* the number of SLURM submissions is limited.

**Use only a launcher listed in `reference/<cluster>-launchers.md` § Availability**
— that file is the record of what is actually installed and verified here. Jobs
with serial dependencies **cannot** go through a launcher — the launcher runs
them concurrently, so a dependency would be violated.

**Serial jobs.** Two options:

1. a separate node per job, chained by dependency;
2. one node whose SLURM script runs the jobs in sequence.

Option 1 is preferred — a break in the middle costs you only that job, and the
DAG records where it stopped. Option 2 is preferred when the queue is long, since
you wait once instead of once per job.

`AskUserQuestion` when it is genuinely unclear which fits; the trade-off depends
on the current queue, which the user may know better than you do.

## Step 4 — size the remote nodes

For each remote node, decide the **node count** and the **expected runtime**, then
invoke the `queue-wait` skill to probe the expected wait for that shape. It is
pre-authorized (CLAUDE.md § Subagents) and runs as a fork, so invoke it directly
rather than asking permission, and pass **every** shape in one invocation.

This is what makes the plan judgeable rather than aspirational: a decomposition
that looks elegant but puts a 40-hour job in a 48-hour queue is worth knowing about
before the user approves it, not after.

Node sizes, queue caps and charge rates are in `reference/taccLS6-nodes.md`; the
wait comes from the `queue-wait` skill, live. Do not guess either.

### When the probe cannot answer

The probe is not always available — the cluster may be unreachable, or a site
submit filter may refuse every shape before the scheduler costs it. `queue-wait`
reports that as **`probe unavailable`**, distinct from a per-shape rejection.

**This path opens only after `queue-wait` has actually run and returned
`probe unavailable`.** Not having invoked it is not a probe failure — invoke it
first. An `unprobed` row is a report about the scheduler, never about your own
reluctance to spawn the fork.

**Do not let this stall the plan, and do not quietly guess.** Size from
`reference/taccLS6-nodes.md` and from what comparable nodes in this repo actually
took — a sibling's recorded `running_time` is the best evidence available — and
then **mark every affected row in the plan as `unprobed`**, with one line naming
what the estimate is based on.

Sizing is only *rough* at this stage; `prepare-node` re-opens it when the plan's
assumption is falsified, and the queue can be re-probed at submit time when it is
actually about to matter. What must not happen is an unprobed number reaching the
user looking like a measured one — that is the failure the marker exists to
prevent. A plan that says "8 h, unprobed, from `relax_dopant`'s 1:58" is honest and
reviewable; one that says "8 h" is neither.

**Where a local node follows a remote one, say what has to come back.** Not
filenames — those need parameters that do not exist yet, and they are
`prepare-node`'s job. But a plot or an analysis step is only as good as the
artifact its parent produces, and "this node needs the IFCs, so the parent must
emit `FORCE_CONSTANTS` rather than leaving raw forces on the cluster" is a
*graph* fact. Catching it here costs a sentence; catching it at run time costs a
re-run of the parent.

**When the sizing is ambiguous or undecided, `AskUserQuestion` instead of
choosing silently.** Typical cases:

* two or more shapes are viable and the wait probe does not clearly separate them
  (e.g. 2 nodes in `development` vs 4 in `normal`);
* the runtime depends on something not yet known — final cell size, k-mesh, how
  many displacements the symmetry actually yields;
* the job is close to a queue cap, so a small change in `-N` or `-t` changes which
  queue it can use at all.

A guessed node count reads in the plan exactly like a measured one, and the user
cannot tell them apart when they approve it. Asking costs one question; a wrong
number costs a re-plan after the allocation is spent.

## Step 5 — present the plan

### Where the plan goes

Entering plan mode assigns you a **plan file** and names its path. That file is the
only thing the approval box can render — a plan typed into the conversation cannot
appear there, however well formatted it is.

So **write the plan, in the format below, to the plan file**, and do not also
paste it into the conversation. Two copies drift, and the one the user actually
approves is always the file.

### Plan iteration

1. Write the plan to the plan file, in the format below.
2. `ExitPlanMode` — this is what shows the plan and asks for approval.
3. If the user comments, **edit the plan file** and `ExitPlanMode` again.
4. Loop until they approve.

Approval is the user accepting an `ExitPlanMode` presentation, and nothing else.
Do **not** use `AskUserQuestion` to ask whether the plan is acceptable: plan mode
forbids it, and the approval box already asks. `AskUserQuestion` remains correct
for the *clarifying* questions in Steps 3 and 4 — which dispatch shape, which node
count, anything whose answer changes what the plan says.

The report's shape depends on the mode settled in Step 0.

The plan format depends on the scenario.

### Fresh exploration

Every node is new, so one table describes the whole graph:

```markdown
# A table summary

| level | id | name | tool | cluster | partition | -N | time | prev | next |
|-------|----|------|------|---------|------|----|------|------|------|

# Summary

## <node 1>
Briefly describe what the node is supposed to do. Highlight the important facts
and parameter choices.
```

Every node in the table gets a Summary entry.

### Continuation

The reader needs to recall where the exploration stands before they can judge a
change to it, so the report has three parts.

**1. Current state.** Summarise the DAG as it is now:

```markdown
# Current workflow

| level | id | name | status | tool | cluster | partition | -N | time | prev | next |
|-------|----|------|--------|------|---------|-----------|----|------|------|------|
```

Read this **from `project_workflow/<exploration>/workflow_dag.json`**, not from
any previous plan document. The DAG is where status is actually written, so it is
the only version guaranteed to be current; a plan document may predate the last
three things that happened.

The columns map straight onto DAG fields — `tool`, `partition`, `num_nodes`
(`-N`) and `request_time` are all recorded per node, so this table is a faithful
read of the file rather than a reconstruction. The one addition over the fresh table is
`status`: showing where the work stands is the whole point of this section.

**2. Modifications.** State every change, and be explicit about where each new
node attaches:

```markdown
# Modifications

| change | name | attach to | level | tool | cluster | partition | -N | time | goal |
|--------|------|-----------|-------|------|---------|-----------|----|------|------|
```

`change` is one of:

* **add** — a new node. `attach to` names its parents; write existing ones as
  `name (#id)` so there is no ambiguity about which node in the table above it
  hangs from. This column is the whole point of the section — a new node with an
  unstated attachment point cannot be recorded.
* **terminate** — an existing node whose result is judged invalid. Give the reason
  in `goal`; leave the sizing columns blank. Use this whenever real compute sits
  behind the node: the DAG keeps it as a record of what was tried and why it was
  dropped.
* **delete** — an existing node that should never have been authored at all (a
  duplicate, a planning mistake with nothing run). Nothing to remember, so the
  node is removed outright.
* **re-point** — an existing node whose parents change; `attach to` gives the new
  parents. This is usually needed alongside a `terminate`: the retired node's
  children must be moved onto its replacement, or they can never run.

No `id` column here. Ids are assigned when the DAG is recorded, and naming one
that already exists either fails or renumbers the whole graph.

**3. Summary of each newly added node.** One entry per `add` row, in the same
shape as the fresh report. Existing nodes do not need one — they were described
when they were planned.

Write this to the plan file and `ExitPlanMode` to present it. Record the DAG only
once the user has approved.

### Both cases

Do not state acceptance gates here. A node's gate — the condition that decides
`completed` vs `failed` — is a node-level detail that belongs with its parameters,
and is written into `NODE.md` when the node is prepared. Naming it at plan time
would fix it before the parameters it depends on exist.

**The approved plan is archived in Step 6**, to
`plans/<exploration>/<YYYY-MM-DD>_<short-name>.md` — not here. Plan mode permits no
write but the plan file, so that copy cannot happen until after approval. A
continuation gets its own dated file rather than editing an earlier one, so each
planning session stays a readable snapshot of what was decided that day.

## Step 6 — record the DAG

**Precondition — do not begin this step until the user has approved the plan.**
Approval means they accepted an `ExitPlanMode` presentation. A plan file that
merely exists is not approval: you can write one without ever showing it, and
`ExitPlanMode` can be rejected. If you cannot point to the approval, you are still
in Step 5 — go back and present it.

This is the one hard gate in the protocol, because everything downstream reads the
DAG as settled fact: `prepare-node` writes inputs against it, `run-workflow` spends
allocation on it, and nothing later re-asks whether the graph was wanted. A DAG
recorded without approval makes the file assert a decision nobody made.

Hand the approved plan to the `workflow-dag` skill. For each row state only what
kind of change it is:

* **new** — a node that does not exist yet, with its parents named;
* **terminate** — an existing node judged invalid, with the reason;
* **re-point** — an existing node whose parents change.

`workflow-dag` owns the schema and the tooling: it creates the DAG if the
exploration has none, inserts new nodes, derives every id and level, wires both
directions of each edge, and verifies the result. Do not name scripts or flags
here — describing the change is enough.

**Then archive the approved plan** to
`plans/<exploration>/<YYYY-MM-DD>_<short-name>.md`, copied from the plan file the
user approved. Plan mode's own file is scratch and does not survive as a record;
this copy is what makes the decision readable months later, and it is why nothing
is lost by keeping the plan out of the conversation.

## Scope boundary

In scope: the graph — what steps exist, what depends on what, where each runs, how
jobs are dispatched, and rough sizing.

Out of scope: acceptance gates, input-file generation, writing the submission
script, uploading, and submitting. Those belong to `prepare-node`, which runs once
per node after this plan is recorded.
