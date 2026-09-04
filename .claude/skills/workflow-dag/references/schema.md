# workflow_dag.json — full schema and CLI reference

Read this when you need an exact field name, an exact flag, or the precise
required/cleared set for a status transition. The workflow itself is in
`../SKILL.md`.

## Contents

- [Top level](#top-level)
- [Node fields](#node-fields)
- [Status lifecycle: required and cleared](#status-lifecycle-required-and-cleared)
- [Script reference](#script-reference)
- [Legacy `stage`-keyed files](#legacy-stage-keyed-files)

## Top level

Exactly four keys. The schema source is `templates/dag_template.json`; the
`_comment` and `_node_format` keys in it are documentation and must **never**
appear in a real file (`new_dag.py` strips them).

| Key | Type | Notes |
|---|---|---|
| `exploration` | string | exploration tag; matches the `project_workflow/<exploration>/` dir |
| `description` | string | one-line exploration summary |
| `status_legend` | list of string | must equal the template's legend, in order |
| `nodes` | list of object | may be empty in a freshly stamped file |

Current legend, in order:
`pending`, `ready`, `queued`, `running`, `completed`, `failed`, `blocked`,
`terminated`.

## Node fields

Canonical order (this is `insert_dag_node.FIELD_ORDER`, mirrored by the
template's `_node_format`). All fields are strings unless noted.

| # | Field | Type | Meaning |
|---:|---|---|---|
| 1 | `name` | string | unique; matches the run dir `<level>_<id>_<name>` |
| 2 | `description` | string | one line, ≤ ~120 chars, summarising what the node computes |
| 3 | `status` | string | one of the legend |
| 4 | `id` | **int** | unique identity — the value `prev`/`next` reference |
| 5 | `level` | **int** | derived depth, `max(parent levels)+1`; root = 0 |
| 6 | `cluster` | string | `local` \| `lonestar6` \| `frontera` \| … — the **cluster**, not an ssh alias. `ls6` is the alias `submit-node` and the `tacc-slurm` MCP connect through; it is not a `cluster` value |
| 7 | `allocation` | string | `<ALLOCATION>` \| `<ALLOCATION_2>` \| `-` for local |
| 8 | `partition` | string | SLURM queue: `normal` \| `development` \| `gpu-a100` \| …; `''` for local |
| 9 | `num_nodes` | string | compute nodes requested (SLURM `-N`), e.g. `'4'`; `''` for local |
| 10 | `expected_start` | string | queue ETA, e.g. `2026-07-04 09:00`; `''` if unknown |
| 11 | `request_time` | string | requested walltime `HH:MM:SS`. Cluster: the SLURM `-t`. Local: **optional** wall-clock cap for `local-node`; `''` takes its 10-minute default |
| 12 | `job_id` | string | SLURM job id once submitted |
| 13 | `job_name` | string | SLURM `-J` name |
| 14 | `elapsed_time` | string | live elapsed while running (`squeue %M`) |
| 15 | `running_time` | string | final runtime once finished (`sacct` elapsed) |
| 16 | `blocked_on` | string | **optional** — present only while `status == blocked` |
| 17 | `terminated_reason` | string | **optional** — present only while `status == terminated` |
| 18 | `prev` | **list[int]** | upstream node ids |
| 19 | `next` | **list[int]** | downstream node ids; `[]` if terminal |

`num_nodes` is a **string**, not an integer, so that an unset value can be `''`
like every other optional field — a local node has no node count, and `0` or
`null` would both read as a claim rather than an absence.

Fields 1–15, 18 and 19 are always present (empty string when unset). Fields 16
and 17 are *sticky*: the scripts add them on entering their status and drop them
on leaving it, so a node never carries a stale explanation.

`id` vs `level`: before 2026-07-17 a single `stage` integer served as both.
`id` is now identity (stable, referenced by edges) and `level` is depth
(re-derived from the graph after every structural edit). Never author `level`
by hand — `insert`, `delete` and `rewire` all call `relevel()`.

## Status lifecycle: required and cleared

Enforced by `update_dag_node.py`. "Requires" must be supplied on the command
line (or, for the two sticky fields, already be on the node). "Clears" is reset
to `''` unless you pass `--no-clear`.

| Status | Requires | Clears |
|---|---|---|
| `pending` | — | `job_id`, `expected_start`, `elapsed_time`, `running_time` |
| `ready` | — | `job_id`, `expected_start`, `elapsed_time`, `running_time` |

`ready` is a statement about the **graph** only — every parent `completed`. It does
not assert that the node has been prepared (its run dir and `NODE.md` written);
that is a filesystem fact, and `check_dag.py` reports the two together.
| `blocked` | `--blocked-on` | — |
| `queued` | `--job-id`, `--expected-start` | `elapsed_time`, `running_time` |
| `running` | `--elapsed-time` | `expected_start` |
| `completed` | `--running-time` | `expected_start`, `elapsed_time` |
| `failed` | — | `expected_start` |
| `terminated` | `--terminated-reason` | `expected_start`, `elapsed_time` |

`terminated` deliberately keeps `job_id`, `job_name` and `running_time`: the
provenance and SU cost of a retired branch are the reason to keep the node
rather than delete it.

## Script reference

All live in `scripts/`. The five writers — `new_dag`, `insert_dag_node`,
`update_dag_node`, `rewire_dag_node`, `delete_dag_node` — each accept both
`--dry-run` and `--render`; `check_dag.py` and `render_dag.py` do not (they only
read, apart from `check_dag --fix`). `update`, `rewire` and `delete` select their
target with `--id N` **or** `--name S` (mutually exclusive, one required).

### `new_dag.py` — stamp a new file

`--exploration` (required) · `--description` · `--out` (default
`project_workflow/<exploration>/workflow_dag.json`) · `--template` · `--force`
(overwrite; **discards every node**) · `--render`.

### `insert_dag_node.py` — add a node

`--name` (required) · `--description` · `--status` (default `pending`) ·
`--id` (explicit slot) · `--level` (hint only; always re-derived) ·
`--prev A,B` · `--next A,B` · `--between A:B` (splice onto that edge, re-routing
it) · `--shift` (open an occupied slot by bumping ids ≥ it) · `--cluster` ·
`--allocation` · `--partition` · `--num-nodes` · `--expected-start` ·
`--request-time` · `--job-id` ·
`--job-name` · `--elapsed-time` · `--running-time` · `--blocked-on`.

A new node is never born `terminated`; retire one with `update_dag_node.py`.

### `update_dag_node.py` — drive the lifecycle

`--status` (required) · `--tool` · `--cluster` · `--allocation` ·
`--partition` · `--num-nodes` · `--job-id` ·
`--job-name` · `--expected-start` ·
`--request-time` · `--elapsed-time` · `--running-time` · `--blocked-on` ·
`--terminated-reason` · `--no-clear` · `--print-node` (emit the updated node as
JSON on stdout, for the calling agent to consume).

Setting `terminated` prints every live node stranded downstream.

### `rewire_dag_node.py` — move an existing node's dependencies

`--prev A,B` / `--next A,B` (replace the list outright) ·
`--add-prev` / `--drop-prev` / `--add-next` / `--drop-next` (incremental).

Mirrors the result onto both endpoints, so passing a node's existing `prev`
back in also **repairs** a one-directional edge left by a hand-edit. Re-derives
levels for the whole subtree.

### `delete_dag_node.py` — remove a node

`--bridge` (reconnect its parents straight to its children, so the chain is not
broken) · `--renumber` (compact ids to `0..N-1` — **breaks any external
reference to the old ids**, so avoid it on a live exploration).

Without `--bridge` it warns about children left with no parent.

### `check_dag.py` — verify

Takes one or more paths. `--fix` (canonical field order + top up
`status_legend`; nothing destructive) · `--quiet` (exit code only) ·
`--warnings-as-errors`.

Errors (exit 1): unexpected/missing fields, wrong types, duplicate name or id,
status outside the legend, a sticky field present in the wrong status or missing
in the right one, one-directional edges, cycles, a `level` that disagrees with
the graph.

Warnings: a node stranded below a terminated one; `pending` when every parent is
`completed`; `ready` when a parent is not; `running` on a cluster with no
`job_id`; the legacy schema.

### `render_dag.py` — ASCII view

`python scripts/render_dag.py DAG.json`. Status tags: `[done] [redy] [que.]
[run.] [pend] [FAIL] [blkd] [TERM]`. Terminated nodes show their reason on an
`x terminated:` line.

## Legacy `stage`-keyed files

`project_workflow/legacy_bandoffset/workflow_dag.json` predates the
`id`/`level` split and keys nodes by `stage`. Every script falls back to it via
`_nid()`, and `check_dag.py` relaxes its field checks (still verifying edges and
levels) rather than rewriting it. Leave it in that shape — reshaping it would
churn a finished exploration's record for no benefit. New explorations always get the
current schema from `new_dag.py`.
