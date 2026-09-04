---
name: workflow-dag
description: >-
  Create and edit an exploration's workflow_dag.json — the single source of truth for
  every computation node's dependencies and status. Use this whenever you are
  about to write or change a workflow_dag.json for ANY reason: standing up a new
  exploration's DAG, adding / splicing / deleting a node, re-pointing a dependency,
  or moving a node through its job lifecycle (submitted → queued → running →
  completed / failed), including retiring a node as `terminated` when its result
  is judged invalid. Trigger even when the user only says things like "add a node
  for the phonon run", "mark stage 3 done", "job 3301574 is running", "that
  supercell was too small, drop it", "set up the DAG for this exploration", or "why
  is nothing ready" — do not wait for them to name the file. Trigger BEFORE
  opening the JSON in an editor: hand-editing silently breaks the id/level/edge
  invariants the scripts maintain. Scope is the FILE only: the schema, the
  scripts that edit it, and which status a node should carry. It does NOT decide
  what the computation stages should be, how the science is decomposed, or
  whether a result is good physics — it records the graph you have already
  decided.
---

# workflow_dag.json — the exploration's computation graph

`project_workflow/<exploration>/workflow_dag.json` is the **only** authoritative
record of what an exploration computes, in what order, and where each piece stands.
Progress reports, the terminal renderer and the web viewer all read from it, so
a DAG that disagrees with reality is worse than no DAG at all.

**Scope.** This is about writing that file correctly — its schema, the scripts
that edit it, and which status each node should carry. *What* the stages are,
how the calculation is decomposed, and whether a result is scientifically sound
are decided elsewhere and arrive here as given.

## The one rule: edit it with the scripts, never by hand

Four invariants hold this file together, and three of them are non-local — you
cannot check them while looking at a single node:

1. **`id` is identity.** `prev`/`next` are lists of `id`s, not names, not positions.
2. **Edges agree in both directions.** If `b.prev` contains `a`, then `a.next`
   must contain `b`. Half an edge is invisible in the JSON but makes the renderer
   and viewer draw a disconnected node.
3. **`level` is derived, never authored.** `level = max(parent levels) + 1`
   (root = 0). Splicing a node in deepens its entire subtree.
4. **Field order and field set are fixed** by `templates/dag_template.json`.

Every script below maintains all four and refuses to write a graph that violates
them. Hand-editing maintains none of them, and the breakage is silent — which is
why `scripts/check_dag.py` exists as the gate.

| To do this | Run |
|---|---|
| Start an exploration's DAG | `scripts/new_dag.py --exploration X --description "..."` |
| Add a node | `scripts/insert_dag_node.py DAG.json --name n --description "..." --prev 3` |
| Insert one *into* an edge | `scripts/insert_dag_node.py DAG.json --name n --between 1:3` |
| Change a node's status | `scripts/update_dag_node.py DAG.json --id 3 --status running --elapsed-time 02:14:00` |
| Move a dependency | `scripts/rewire_dag_node.py DAG.json --id 4 --drop-prev 3 --add-prev 10` |
| Remove a node entirely | `scripts/delete_dag_node.py DAG.json --id 3 --bridge` |
| Verify the file | `scripts/check_dag.py DAG.json` |
| Look at it | `scripts/render_dag.py DAG.json`, or `dag_viewer/serve.py` |

The five that write (`new_dag`, `insert`, `update`, `rewire`, `delete`) all take
`--dry-run` (print the result, write nothing) and `--render`. Preview with
`--dry-run` when an edit is structural and you are unsure. `check_dag.py` and
`render_dag.py` are read-only — `check_dag --fix` is the one exception.

## Creating a new DAG

`new_dag.py` stamps the file from `templates/dag_template.json`, dropping the
template's `_comment` / `_node_format` documentation keys and its placeholder
node. Copying the template by hand is how those keys leak into real files, so
let the script do it:

```bash
python scripts/new_dag.py --exploration defect_kappa \
    --description "T-matrix phonon-defect scattering in r-TiO2"
```

Then add nodes root-first, so each one's parents already exist:

```bash
python scripts/insert_dag_node.py project_workflow/defect_kappa/workflow_dag.json \
    --name pristine_import --description "Fetch relaxed POSCAR + FORCE_CONSTANTS; pin settings" \
    --cluster local --allocation -
python scripts/insert_dag_node.py .../workflow_dag.json \
    --name relax_defect --description "Relax Nb_Ti 3x3x4 supercell, ions only, lattice fixed" \
    --prev 0 --tool vasp --cluster lonestar6 --allocation <ALLOCATION> --request-time 08:00:00
```

`--prev` is all the wiring you need: the id, the level and the parent's `next`
are all derived. Omit `--prev` only for a root.

### Field conventions

These are about the record, not about what the node should compute:

- `name` must match the node's run directory,
  `implementation/<exploration>/<level>_<id>_<name>/`, since the two are looked up
  against each other.
- Keep `description` to one line (≤ ~120 chars). Results, findings and analysis
  belong in the node's run directory — this file stays small enough to read whole
  and to diff meaningfully.
- `tool` is the software the node's batch job runs, lowercase, spelled exactly as
  its directory in `.claude/skills/` — it is what routes the node to a health
  probe (`reference/quick-ref.md` → Health probes). `""` for a node that submits
  no job. `check_dag.py` warns on any node with a remote `cluster` and no `tool`,
  because such a job is watched only generically and nothing else would say so.
- Leave a field as `""` rather than guessing a value. An invented walltime or a
  placeholder job id is worse than a blank one, because it reads as recorded fact.

## Choosing a status

Recording the right status is the one judgement this file exists to hold, so make
it from evidence (`squeue` / `sacct` via the `tacc-slurm` MCP, plus the node's own
outputs) rather than from what you expect to have happened. Where a status turns
on whether a result is acceptable, that criterion is an **input** — it comes from
the plan, the node's description, or the user. This skill does not supply it.

| Status | What it asserts | Decide it when | Must supply |
|---|---|---|---|
| `pending` | authored, not yet runnable | created, and at least one `prev` is not `completed` | — |
| `ready` | dependencies satisfied | **every** `prev` is `completed` (vacuously true for a root) | — |
| `blocked` | stalled on something outside the graph | waiting on a decision, a missing structure, an allocation — something **no node** will produce | `--blocked-on` |
| `queued` | in the SLURM queue | `sbatch` returned an id; `squeue` shows `PD` | `--job-id`, `--expected-start` |
| `running` | executing on a compute node | `squeue` shows `R` | `--elapsed-time` |
| `completed` | finished **and the result is usable** | `sacct` says `COMPLETED` **and** the node's acceptance criterion is met | `--running-time` |
| `failed` | did not produce its result; **retryable** | `sacct` says `FAILED`/`TIMEOUT`/`CANCELLED`, or it exited clean but the acceptance criterion was not met | — |
| `terminated` | judged invalid; **retired from the graph** | the node's *purpose* is void, whatever its exit status | `--terminated-reason` |

### `ready` does not mean "submittable"

Status answers **one** question: *are my dependencies done?* It is a fact about
the graph. Whether a node has anything to submit is a fact about the **disk** —
its run directory and `NODE.md` exist because the node has been *prepared*.

```
ready        = every parent completed          (the DAG knows this)
prepared     = implementation/<exploration>/<level>_<id>_<name>/NODE.md exists
submittable  = ready AND prepared
```

Keep them apart deliberately. A status field that mirrors the filesystem goes
stale the moment a directory is moved or deleted, and nothing catches it; a
status derived purely from the graph cannot. `check_dag.py` reports the
combination, so you never have to track it by hand.

The transition also clears fields that no longer apply (`expected_start` once
running, `elapsed_time` once finished), so the node never carries a stale
timestamp from an earlier state. Pass `--no-clear` only if you have a specific
reason to keep one.

### The decision, in order

1. **Has it run yet?** No → `pending` / `ready` / `blocked` / `queued`.
   The split between `pending` and `ready` is mechanical and depends **only on
   the graph**: every parent `completed` → `ready`. A root has no parents, so
   nothing gates it — mark it `ready` when you intend to work on it. `blocked` is
   *not* for waiting on a parent node — that is what an edge is for; use it when
   the thing you are waiting for is outside the DAG.
2. **Is it running now?** → `running`.
3. **It finished. Is this node still wanted at all?**
   - **No** → `terminated`. Say why in one line.
   - **Yes** → **did it deliver a usable result?**
     - Yes, criterion met → `completed`.
     - No → `failed`. A clean exit code is not enough on its own: SLURM reports
       `COMPLETED` whenever the binary exited normally, which it does even when
       the calculation did not reach what it was asked for.

The last point is the one that goes wrong most often. `completed` is a claim that
the node's acceptance criterion was met, not that the job exited zero. If you do
not know the criterion, ask — do not infer it from the exit code.

## `terminated` vs `failed` vs deleting

These three look similar and mean very different things:

- **`failed`** — the node is still wanted, this attempt did not deliver. You will
  fix the inputs and resubmit, or spawn a continuation node. The node stays live.
- **`terminated`** — the node itself should no longer exist in the live graph.
  The run may have finished perfectly: the cell was too small, the settings were
  superseded, the approach was a dead end. It will never be retried. A terminated
  node **never reaches `completed`**, so by the readiness rule *nothing below it
  can ever run* — it is a dead end by construction, not just a label.
- **deleting** (`delete_dag_node.py`) — the node should never have been authored
  at all: a duplicate, a typo, a planning mistake with no compute behind it.
  Nothing happened, so there is nothing to remember.

## Continuation nodes

A calculation that runs in rounds — a large-cell relax, a long MD — is a **chain
of nodes**, one per round, grown as the rounds happen. One node is one SLURM job,
so an open-ended loop cannot be a single node.

Name each round `<name>_r2`, `_r3`; an infrastructure retry of a node that died
on a bad compute node is `<name>_retry2`. **The number lives in the name on
purpose:** it makes "how many rounds has this chain had" a question the DAG
answers, so a driver that lost its context can still enforce a round cap.

A round that ran cleanly to its ionic or walltime limit is **`completed`**, not
`failed` — the job did what it was asked. Whether the science criterion is met is
a separate question, and it decides whether another round is spawned rather than
being a verdict on this one. Recording it `failed` would block the whole chain:
nothing below a non-`completed` node can ever become ready, including the next
round.

Spawn it in two steps, so existing ids stay stable:

```bash
python scripts/insert_dag_node.py <dag> --name relax_BC_r2 --prev <finished id> …
python scripts/rewire_dag_node.py <dag> --id <child> \
    --drop-prev <finished id> --add-prev <new id>      # once per child
```

**Not `insert --between`.** It takes the downstream node's id slot and shifts
every id at or above it, which renames those nodes' directories both locally and
on the cluster.

The splice deepens the graph, so descendants' `level` changes while their
directory names still carry the old one. That is harmless — directories are
matched on `<id>_<name>` — and `check_dag.py` warns about the stale prefix.

Deciding *whether* to spawn a round belongs to `run-workflow`; this skill only
records it.

Prefer `terminated` over deleting whenever real compute or a real decision sits
behind the node. The DAG is an audit trail; the SU cost of a dead branch and the
reason it died are exactly the things you want to still know in three months.

```bash
python scripts/update_dag_node.py DAG.json --id 3 --status terminated \
    --terminated-reason "3x3x4 supercell too small; superseded by 3x3x5"
```

`terminated_reason` is required, is kept only while the node is terminated (it
disappears if the node is ever revived), and should be one line — the diagnosis
belongs in the run directory. `job_id` and `running_time` are deliberately
preserved: the provenance of a dead branch still matters.

### Handling the branch below a terminated node

Terminating warns you about every live node stranded beneath it, and
`check_dag.py` keeps warning until you resolve them. Do not leave them dangling —
a node that can never become ready but still reads `pending` is exactly the kind
of quiet lie this file exists to prevent.

**Which resolution applies is not this skill's call** — whether a branch is dead,
or gets redone from a replacement, is a decision about the work itself. If it has
not been settled, ask rather than assume. The file-level mechanics for each:

1. **The whole branch is dead** → terminate each one, reason
   `"upstream <name> terminated"`.
2. **The work is still wanted, from a replacement node** → author the replacement,
   then re-point the children at it:
   ```bash
   python scripts/insert_dag_node.py DAG.json --name ifc_dopant_335 \
       --description "2nd-order IFCs, 3x3x5 supercell (replaces terminated ifc_dopant)" --prev 1
   python scripts/rewire_dag_node.py DAG.json --id 4 --drop-prev 3 --add-prev 10
   ```
   Re-pointing keeps each child's own history (`job_id`, timings) intact, which
   deleting and re-inserting would throw away.
3. **The child never actually needed that parent** → just drop the edge:
   `rewire_dag_node.py DAG.json --id 4 --drop-prev 3`.

## The schema contract

A real `workflow_dag.json` has **exactly four** top-level keys — `exploration`,
`description`, `status_legend`, `nodes` — and each node has **exactly** the
fields the template presets, in the template's order. Two fields are optional and
appear only while their status holds: `blocked_on` and `terminated_reason`.

Do not invent fields. If you want to record a purpose, a result, a directory
path or a parameter set, it goes in the node's run directory
(`implementation/<exploration>/<level>_<id>_<name>/`), not here — this file stays
small enough to read whole and to diff meaningfully.

Full field-by-field reference, including every CLI flag:
[`references/schema.md`](references/schema.md).

## Finish every edit with a check

```bash
python scripts/check_dag.py project_workflow/<exploration>/workflow_dag.json
```

It verifies the schema against the template (stray or missing fields, legend,
types), the graph (acyclicity, both-direction edges, derived levels), the sticky
status fields, and lints statuses that disagree with the graph — a node still
`pending` when all its parents are `completed`, a node stranded under a
terminated one, a `running` node with no `job_id`. Exit 0 means safe to commit.

`--fix` applies only the safe normalizations (canonical field order, topping up
`status_legend`); everything else it reports for you to decide. Run it on all
explorations at once with
`python scripts/check_dag.py project_workflow/*/workflow_dag.json`.
