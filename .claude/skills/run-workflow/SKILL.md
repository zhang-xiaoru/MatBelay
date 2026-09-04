---
name: run-workflow
description: >-
  Drive an already-prepared exploration's DAG to completion: work out which nodes
  can run, submit them, watch them, judge each result against its gate, and keep
  going until the graph is done or something needs a human. Use whenever the user
  wants prepared work to actually run or to keep running — "run it", "submit
  these", "go ahead", "launch the ready nodes", "the parent finished, continue",
  "what's still running", "check on the jobs" — and re-enter it every time the
  job watcher reports something. This is the SEQUEL to the computation
  orchestrator: that protocol plans and prepares, this one executes. It does NOT
  plan a graph (`plan-computation`), write a node's inputs (`prepare-node`), or
  upload and sbatch one node (`submit-node` subagent) — it decides what should
  run, and what a finished run means.
---

# Run a workflow

Take an exploration whose nodes are prepared and drive it to completion.

**One exploration per invocation.** "Run `defect_kappa`." The watcher is
repo-wide and already covers every job, but reason about one DAG at a time: the
state rebuild stays simple, the approval stays reviewable, and a stop in one
exploration cannot be mistaken for another. If the user did not name one, ask.

## Remember nothing

This skill is re-entered constantly — after every watcher event, after every
"continue", and after a context compaction twenty hours and two jobs later. **Any
fact you hold in conversation instead of on disk is a fact you will lose.**

So every question has a file that answers it:

| Question | Answered by |
|---|---|
| what is in flight | DAG `status` ∈ {queued, running}, and `project_workflow/.watchstate` |
| what already finished | DAG `status` = `completed` |
| what can run now | `check_dag.py --list-submittable` |
| how many rounds has this chain had | the node names along its `prev` chain |
| is the watcher running | the Monitor task list |

Never carry a count, a pending decision or a "waiting on" in your head. Write it
to the DAG or derive it again.

---

## Step 0 — rebuild state

Before anything else, every time:

```bash
python scripts/check_dag.py project_workflow/<exploration>/workflow_dag.json
python scripts/check_dag.py project_workflow/<exploration>/workflow_dag.json --list-submittable
cat project_workflow/.watchstate 2>/dev/null
```

Then reconcile:

1. **Regenerate the watchlist from the DAG.** The DAG holds `job_id`, so every
   watchlist row is reconstructible from it; the reverse is not true. Read the
   remote work root from `CLAUDE.md` — it is declared in exactly one place —
   and rebuild atomically:

   ```bash
   python scripts/check_dag.py project_workflow/*/workflow_dag.json \
       --watchlist --remote-root <root from CLAUDE.md> \
       > project_workflow/.watchlist.tmp \
     && mv project_workflow/.watchlist.tmp project_workflow/.watchlist
   ```

   Rebuild rather than append: a derived file cannot drift, and finished jobs
   drop out on their own instead of accumulating. Use `mv`, so the watcher never
   reads a half-written file. Pass **every** exploration's DAG here even though
   you are driving one — the watcher is shared, and rebuilding from one DAG alone
   would delete the other explorations' live rows.

2. **Arm the watcher if it is not running.** Check the Monitor task list first;
   do not arm a second one.

   ```
   Monitor(command: "bash scripts/watch_jobs.sh",
           description: "SLURM jobs for <exploration>",
           persistent: true)
   ```

   **Arm it from the main conversation, never from a subagent** — a Monitor's
   events arrive in the conversation that armed it, and a subagent's ends when it
   returns, so anything it armed would report to nobody.

3. **Reconcile orphaned local runs.** A node with `status: running`,
   `cluster: local` and no `job_id` was interrupted. `local-node` runs in the
   foreground, so nothing can still be driving it — the only way to observe that
   state is if the agent that wrote it is gone. Record it `failed`, say which
   node and that it was interrupted, and stop the branch.

   **Do not re-run it.** The directory holds half-written output, and re-running
   from a dirty state is the "work around" the autonomy boundary forbids. Without
   this clause an interrupted local node sits at `running` forever, or worse gets
   re-run over its own partial results.

4. **Report the picture** before doing anything: what is running, what finished
   since last time, what is stopped and why.

## Step 1 — the submittable set

`--list-submittable` applies three conditions, all necessary:

* every `prev` is `completed` — the graph permits it;
* a `NODE.md` exists — it has actually been prepared;
* its own status is not already `queued`, `running`, `completed` or `terminated`.

`failed` is excluded deliberately: it means a human decision is outstanding, and
resubmitting unchanged would repeat whatever went wrong.

If the set is empty, say which of the three conditions is blocking, per node.
"Nothing to submit" is unhelpful when the cause is a missing `NODE.md` that
`prepare-node` would fix in a minute.

## Step 2 — one approval

Ask once, at the start of a run, not per node and not per round:

> These N nodes are ready to submit: … That is roughly X node-hours against
> allocation Y. Proceed?

After that, proceed automatically under the rules below. This is the deliberate
human break — preparation writes files, submission spends allocation.

## Step 3 — run each node, by where it runs

`--list-submittable` emits `cluster` as column 4. Split on it:

| `cluster` | agent | how |
|---|---|---|
| anything else (`lonestar6`, `frontera`, …) | `submit-node` | **one per node, in parallel** — they are independent and the rsync/sbatch noise stays out of this conversation |
| `local` | `local-node` | **one node at a time, sequentially** |

Give each the node's directory and the exploration; both derive the paths they
need themselves.

**Local nodes run sequentially on purpose.** This machine has a small core
budget, and two numpy or phonopy jobs competing for it finish later than the same
two in sequence — with the user sitting at the machine while they do.

Both agents run but do not judge. `submit-node` is forbidden to evaluate a gate;
`local-node` reports that `GATE_dphi.md` was written and never what it says. The
artifact comes back to you, and you read it — a summary of the evidence is not
the evidence.

## Step 4 — record

**Local nodes take none of this step.** They have no job id, never enter the
watchlist, and are never watched — `check_dag.py --watchlist` already excludes
them by requiring a `job_id`. Record `running` **before** handing one to
`local-node` (that write is what Step 0's orphan clause detects), then the
outcome when it returns, with a measured `--running-time`.

**Write each submission to the DAG as its subagent returns. Never batch the
writes to the end.**

```bash
python scripts/update_dag_node.py <dag> --name <node> --status queued \
    --job-id <id> --job-name <name> --expected-start <ISO>
```

A node is submittable only while its status is not `queued`, so that write is
what stops a re-entry from submitting it twice. The window between `sbatch`
returning and this write is the only exposed one — keep it short.

Then rebuild the watchlist (Step 0.1 again). **DAG first, watchlist second**: a
crash between them is repaired silently at the next Step 0.

If a subagent reports `do not add to watchlist`, the job died inside its sanity
window. Record `failed` and treat it as a branch stop.

**Only this agent writes `workflow_dag.json`.** `update_dag_node.py` is an
unlocked read-modify-write, and `submit-node` is forbidden to touch it for
exactly that reason. *(Known hazard: `dag_viewer/serve.py` also writes node
fields. If the viewer is open on this DAG during a run, a status write can be
clobbered — close it, or expect to re-check.)*

## Step 5 — react to what the watcher says

Events arrive as notifications. They are not replies from the user, and one can
land while you are mid-task or waiting on a question.

| Event | Action |
|---|---|
| `QUEUED` | `--status queued`, record `expected_start`. Say nothing further |
| `RUNNING` | `--status running --elapsed-time …`. Say nothing further |
| `SETTLED` | nothing — it means no errors in the first ten minutes |
| `NOTE <msg>` | record it. Informational; no action |
| `WARN <sig>` | record it. Act only if it recurs, or the tool's skill calls that signature fatal |
| `ERROR <sig>` | **stop the branch.** Report the signature and the file it names |
| `COMPLETED` | → Step 6 |
| `TIMEOUT` | continuable and all five conditions hold → spawn a round; otherwise **stop the branch** |
| `NODE_FAIL` / `BOOT_FAIL` / `PREEMPTED` | infrastructure retry (≤ 2); beyond that **stop the branch** |
| `FAILED` / `OUT_OF_MEMORY` | **stop the branch** |
| `CANCELLED…` | **stop the branch.** Say plainly that it was cancelled — if the user did it, they need no explanation; if they did not, the reason matters. Never auto-resubmit a cancelled job |
| `DEADLINE` | **stop the branch.** A QOS or reservation deadline, not the job's own walltime — the fix is a scheduling decision, so it is the user's |
| `GONE` | **stop the branch** — the job id is wrong, or the record was purged. Do not resubmit on a guess |
| `watcher is BLIND` | tell the user to run `ssh ls6`. Do not submit anything while blind |

This table is exhaustive against `scripts/watch_jobs.sh` — every line that
script can emit appears above. If you meet an event that is not here, the
watcher has grown a new one: **stop the branch** and say so, rather than
choosing an action by analogy.

**Stopping a branch needs no mechanism.** Record the node as `failed` and the
DAG's own readiness rule does the rest: nothing below a non-`completed` node can
become ready, and nothing beside it is affected. Independent branches keep
running. `update_dag_node.py` will list what is now stranded.

**Every stop sends a `PushNotification`.** A branch that stops at 3 a.m. and sits
in a transcript nobody is reading has wasted the night. Push on stops and
judgement gates only — never on `QUEUED`, `RUNNING` or a clean `COMPLETED`.

## Step 6 — a node finished; did it work?

Two different arrivals lead here, and the difference decides step 1:

* a **cluster** node — the watcher reported `COMPLETED`;
* a **local** node — `local-node` returned.

`COMPLETED` is SLURM's opinion. It means the process exited, not that the result
is usable. Most solvers exit 0 after quietly giving up — hitting an iteration
cap, writing a half-converged answer — so the exit code and the verdict are
different claims. The same is true of a `run.sh` that exits 0 having drawn an
empty figure.

1. **Run `post_processing.sh` — cluster nodes only**, and only if the node has
   one. Non-zero exit → stop the branch; the node produced nothing its children
   can use.

   **A local node's post-processing has already run.** `local-node` runs it as
   its own step 4, immediately after `run.sh`, and reports the outcome. Running
   it again here would be a second execution of a script that is not required to
   be idempotent — one that appends to a file or moves it would corrupt the
   node's output silently, after a clean first pass. Read `local-node`'s report
   instead: it names the script and its exit status.

   The split follows from *when* the work can happen, not from who is allowed to
   do it. For a cluster node the job is still queued when `submit-node` returns,
   so post-processing has to wait for an event that arrives much later — here.
   For a local node `run.sh` finishing **is** that moment, and `local-node` is
   already in the directory.

2. **Evaluate the gate**, which is the `## Gate` section of the node's `NODE.md`.
   This step is the same for both kinds of node.

### Fetching results

**A local node's own fetch is `local-node`'s job**, done in step 1 of that agent
from the node's `## From upstream` table. You do not fetch on its behalf.

What you fetch is **on demand** — "fetch the OUTCAR of `2_5_ifc_BC`" — and
anything you need to evaluate a gate. Same call either way, into
`tacc_fetch/<exploration>/<producing node dir>/`, the same directory name it has
in `implementation/`:

```
fetch_results(remote_subdir="<root>/<expl>/<parent dir>",
              local_output_dir="tacc_fetch/<expl>/<parent dir>",
              include=["FORCE_CONSTANTS", "SPOSCAR"])
```

**Never omit `include`.** Without it rsync takes the whole directory *and* every
subdirectory, which for a displacement farm is hundreds of task dirs. That is how
this repo acquired 585 MB of fetched results of which ~140 MB has ever been
opened. `fetch_results` reports what landed, so check the line it returns.

A node with no `## From upstream` table needs nothing fetched — the normal case
when its child runs on the same cluster.

Full rules, including why the list is task-specific rather than tool-specific:
`.claude/rules/tacc-fetch-rule.md`.

### A node with no `tool` is judged by its own `NODE.md`

Seven of the eight local nodes here have `tool: ''` — a one-off python script, not
a shared code. They have no skill and never will.

The `## Success check` contract exists so a **shared** tool's judging rules live
in one place used by many nodes; `quick-ref.md` scopes it to *"a tool used for
batch jobs"*. A one-off script has exactly one user, so:

> **A node with an empty `tool` does not consult `quick-ref.md`. Its `NODE.md`
> `## Gate` section *is* its success check**, and the `**objective**` /
> `**judgement**` marker decides whether you may proceed.

Without this the rule below stops every local node forever, since there is no
skill to hold a `## Success check`. Expect most local gates to be
`**judgement**` and to stop — correct rather than a defect: these are analysis
nodes, what a plot means is the user's call, and re-running one costs a minute.

### You do not know how to judge a run — the tool's skill does

This protocol is tool-free on purpose, exactly like the job watcher and the
submitter. It knows *that* a result must be judged; it knows nothing about how.

Look the node's `tool` up in `reference/quick-ref.md` and open its skill. **A
tool skill that nodes can name must carry a `## Success check` section answering
four questions**, and those four are the entire interface between this protocol
and any code:

| | Question | What this protocol does with it |
|---|---|---|
| 1 | did the job exit cleanly? | no → stop the branch |
| 2 | did it meet its criterion? | yes → `completed`, proceed |
| 3 | if not — **budget** or **failure**? | failure → stop. Budget → question 4 |
| 4 | what is the progress metric, what carries over to the next round, and what changes? | the continuation recipe |

**If the tool's skill has no `## Success check`, stop.** Do not fall back on
general knowledge of that code. Inventing a criterion is precisely the judgement
the autonomy boundary exists to prevent, and a wrong one produces a result that
looks fine. Say which tool is missing the section — writing it is a small job and
it unblocks every node using that tool.

| Gate kind | Result | DAG | Then |
|---|---|---|---|
| **objective** | met | `completed` | recompute the submittable set and continue automatically |
| **objective** | not met, continuable | `completed` (the round ran) | spawn round N+1 |
| **objective** | not met, not continuable | `failed` | stop the branch, push |
| **judgement** | — | `blocked`, with `--blocked-on` | **stop. Present the evidence and let the user decide** |

A **judgement** gate is never auto-proceeded, even when it looks satisfied.
"ΔΦ decays before the boundary" and "no imaginary modes" are readings, not
measurements, and spending the next node's allocation on your reading of them is
the one thing this protocol will not do on its own.

**Record it `blocked`, not "leave it as it is":**

```bash
python scripts/update_dag_node.py <dag> --name <node> --status blocked \
    --blocked-on "judgement gate: <the question>; evidence in <file>" \
    --running-time <measured>
```

Three reasons it must be a written status rather than an open question in the
conversation. `blocked` is not `completed`, so the readiness rule keeps every
child unready and **the stop survives a compaction**. `--blocked-on` puts *what
is awaited* into the file instead of your head, which is this skill's whole
premise. And for a local node, leaving it at `running` is actively wrong — Step 0
reads a `running` local node as an orphan and would declare it `failed` on the
next entry.

When the user rules it becomes `completed` or `failed`. `blocked` clears no
fields, so the measured running-time survives the transition.

---

## The autonomy boundary

**Two actions are permitted without asking. Everything else stops.**

This is an allow-list on purpose. A deny-list fails open: a failure class nobody
anticipated reads as fine, and the agent keeps spending. Here, anything
unrecognised stops.

### A. Continuation

A node that `NODE.md` declares iterative — a relax or an MD — which ended on
*budget* rather than on *failure*. **All five** must hold:

1. `NODE.md` marks it continuable **and states the recipe** — exactly what
   changes between rounds;
2. it ended by exhausting its steps or its walltime, with valid output to
   continue from;
3. the tool's skill reports the gate metric moved **toward** the gate versus the
   previous round;
4. fewer than **3** automatic continuations on this chain already;
5. every branch condition in the recipe is answerable from the last round's
   output.

Condition 1 is the one that carries the weight. A continuation is safe because it
**decides nothing** — but only if the decision was already made, in two places
that must both be filled in:

* the **tool's skill**, `## Success check` question 4 — how continuation works
  for this code at all: which files hand over, what the progress metric is, which
  setting a next round may switch between;
* the node's **`NODE.md`**, `### Continuation` — this node's actual numbers: its
  thresholds, its round budget, which branch applies when.

Same split as every other parameter here: the skill holds the rule, `NODE.md`
holds the value. A next round may well use a different setting than the last one
— that is still not a decision you are making, because both the choices and the
condition selecting between them were written down before the run.

If either half is missing, **stop.** "Continuable" without a recipe is worse than
nothing: it invites you to choose parameters, which is the one thing a
continuation is supposed to avoid.

Condition 3 is what makes continuing after a `TIMEOUT` safe. A timeout with the
metric improving is a budget problem. A timeout with it flat or rising is a real
failure wearing a budget's clothes, and more walltime will not fix it.

### B. Infrastructure retry

`NODE_FAIL`, `BOOT_FAIL`, `PREEMPTED` — TACC hiccups, not science. Resubmit the
same inputs into a fresh directory. **Capped at 2:** a node that dies three times
is a bad node, not bad luck.

### Never, without asking

Change any input parameter · change `-N`, walltime or partition · re-plan the
graph · re-wire a dependency for any reason other than a continuation ·
`terminate` a node · work around a failed `pre_processing.sh` · decide a
judgement gate.

The danger is not that you fail. It is that a wrong fix **completes cleanly** — a
plausible number, nothing flagged, no way for anyone to notice. Continuing a run
that ran out of steps cannot do that. Choosing a solver's convergence algorithm
can.

---

## Continuation mechanics

### Two gates, not one

If a node that merely exhausted its step budget were recorded `failed`, the
round-2 node hanging off it
could never become ready, and its original children would stay blocked forever
even after round 2 succeeded. The way out is that an iterative node carries two
separate criteria:

| | asks | decides |
|---|---|---|
| **round gate** | did this job produce usable output to continue from? | the node → `completed` or `failed` |
| **chain gate** | is the science criterion met yet? | whether another round is needed |

A round that ran cleanly to its limit **did** complete its job. Record it
`completed`. The science gate then decides whether the chain continues — it is
not a verdict on the round.

### The surgery

Round N+1 is a **new DAG node**, named `<name>_r2`, `_r3` (infrastructure retries:
`_retry2`). The round number lives in the name so that "how many rounds has this
chain had" is a question about the DAG rather than about your memory.

```bash
# 1. the new round hangs off the finished one
python scripts/insert_dag_node.py <dag> --name <name>_r2 \
    --description "round 2, restarted from round 1" \
    --prev <finished id> --tool <same> --cluster <same> \
    --partition <same> --request-time <same>

# 2. move the finished node's children onto it — once per child
python scripts/rewire_dag_node.py <dag> --id <child> \
    --drop-prev <finished id> --add-prev <new id>
```

Step 2 runs **only** when a round is actually spawned. If the chain gate passes,
the children stay where they are and nothing moves.

**Do not use `insert --between` for this.** It takes the downstream node's id
slot and shifts every id at or above it — which renames those nodes' directories,
local and remote. Insert-then-rewire keeps every existing id stable.

Then prepare the new node's directory yourself, by **following the recipe** —
the tool's skill says which files hand over from the finished round and which
setting may change; the parent's `NODE.md` says which branch applies here. A
fresh directory every time; never overwrite a previous round, so the chain stays
auditable.

This one preparation skips `prepare-node`'s usual per-node approval, because
nothing in it is a decision — every value came from a document written before the
run. If you find yourself supplying one that did not, that is the signal to stop.

A continuation deepens the graph, so descendants' `level` values change while
their directory names still carry the old one. That is expected and harmless —
node directories are matched on `<id>_<name>`, and `check_dag.py` warns about the
stale prefix so you can rename if you want the listing to sort by depth.

---

## Scope boundary

In scope: which prepared nodes should run now, getting them submitted and
watched, what each result means against its gate, and how far to proceed without
asking.

Out of scope: **what the nodes are** — `plan-computation`. **Writing a node's
inputs, batch script or gate** — `prepare-node`. **Uploading and `sbatch`ing one
node** — the `submit-node` subagent. **The DAG file's schema and status
semantics** — `workflow-dag`. **Whether a given result is good physics** — the
tool's skill states how to check; the user decides what it means.
