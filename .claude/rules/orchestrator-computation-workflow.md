# Computation Workflow Orchestrator

Use this orchestrator whenever the user asks for a computation task.

## The protocol

0. Establish the exploration
1. Decompose the task and construct the workflow DAG — skill `plan-computation`
2. Ask which nodes to prepare in this round — `AskUserQuestion`
3. Prepare those nodes — skill `prepare-node`
4. Report what was prepared, and what each node is waiting on

---

### Step 0 — establish the exploration

Settle which exploration this work belongs to. `plan-computation` resolves fresh
vs continuation in its own Step 0 and records accordingly — this step only has to
make sure the question is asked before planning starts.

The exploration name it fixes governs the DAG directory, the
`implementation/<exploration>/` tree, and the `exploration` key in the JSON.

### Step 1 — plan the DAG (high level only)

The user's computation task (or a file summarising it) is decomposed into a
workflow DAG and recorded, using the `plan-computation` skill, which:

1. enters plan mode, proposes and iterates the DAG structure with the user until
   it is settled;
2. records the node structure using the `workflow-dag` skill.

What is decided here is the **graph**: what steps exist, what depends on what,
where each runs, the job-dispatch strategy (launcher vs serial),
and a node-count / walltime estimate per remote node with its expected queue wait.
What is *not* decided is any actual artifact — no input files, no submission
script. Those belong to Step 3.

The queue wait comes from the `queue-wait` skill, invoked by `plan-computation`
Step 4. It runs as a fork and is pre-authorized — spawn it without asking. The
"main agent, not a subagent" rule in Step 3 governs *writing node files* only,
and does not apply here.

### Step 2 — choose what to prepare

Not every planned node should be prepared in this round.

**Preparation is not execution.** Preparing a node means writing its directory,
inputs, batch script and `NODE.md` record. It does not mean running it.
A node whose parent has not run yet is still preparable — its parameters are known
in advance, and its `pre_processing.sh` encodes how the parent's output becomes
this node's input. Execution is gated on the parent finishing; preparation is not.

**Exclude a node from this round when:**

* **No tool** — the required software is not available locally or on the cluster.
* **Needs substantial custom code** — a solver or analysis script must be authored,
  not merely configured.
* **Its parameters depend on an upstream *result*, not just an upstream *file*.**
  If the parent only hands over a file, this node is preparable: the file's path
  is known even though its contents are not. If a *value* in this node has to be
  read off the parent's result, it is not — that decision does not exist yet.
  *(Example, VASP: a relax following an MD is preparable, since only the
  structure comes from the MD. A production run whose `ENCUT` is chosen from a
  convergence sweep is not.)*
* **Deprioritised** — not worth the effort yet.

Default: prepare everything not excluded. Propose the exclusion list with a
one-line reason each, then `AskUserQuestion` to approve or adjust — one decision,
not one per node.

### Step 3 — prepare the chosen nodes

**Loop, one node at a time, in level order.** A child's parameters may need to
match its parent's (a shared basis, so two results can be differenced), so settle
the parent first.

For each node:

1. `prepare-node` — settles the remaining parameters, works out the pre- and
   post-processing, and presents a report for that node alone. Iterate with the
   user until approved, then `ExitPlanMode`.
2. Write the node's files yourself: the run directory, its inputs, its
   submission script, `pre_processing.sh` if the node needs one, and `NODE.md`.
3. Move on to the next node.

One approval per node, deliberately. A single report covering ten nodes is either
too long to read or too shallow to review, and revising one line in it would
re-open the approval for all ten.

**Write the files in the main agent, not a subagent.** A fresh subagent inherits
none of this conversation — not the approved values, not the tool's defaults or
templates — so it would have to reconstruct the inputs from the report. Since the
report shows decisions rather than whole files, that reconstruction is where an
approved value silently becomes a different one. The main agent already holds
every decision, so writing is both faster and faithful.

**Preparation stops there.** Nothing is uploaded, nothing is submitted, and
`workflow_dag.json` is not touched — a node's status is a fact about the graph
and about jobs, and preparing changes neither. Running a prepared node is a
separate act: `submit-node` runs the node's `pre_processing.sh` and submits its
`.batch`.

A node counts as prepared exactly when its `NODE.md` exists, which is what
`check_dag.py` reports. So an interrupted loop resumes by re-running it: finished
nodes are skipped, with no bookkeeping.

### Step 4 — report

State plainly:

* which nodes were prepared, and where their directories are;
* what each one is waiting on before it can run — an unfinished parent, or
  nothing at all;
* which nodes were excluded in Step 2, and why.

**This protocol ends here.** Running the prepared nodes — submitting, watching,
judging each result against its gate, and deciding whether to continue — is the
skill `run-workflow`. Do not submit from this protocol.

The break is deliberate, and it is not merely a checkpoint for the user.
Preparation is one bounded conversation that ends in a report; running spans
hours, survives context compaction, and is re-entered on every watcher event, so
it has to rebuild its state from disk rather than inherit it from here. Those are
different protocols, not two halves of one.
