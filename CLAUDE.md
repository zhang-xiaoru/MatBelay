# CLAUDE.md
This is a repository that generate plan and scripts for condensed matter/material calculations and manage high throughput calculation in the HPC server

## Core principles
* **Plan first implementation** -- for non-trivial tasks (implement new or change exsistance computation), enter plan mode.
* **Work in designited directory** -- Only work under desiginited directory on remote server. See **Server Info** below.
* **No reading hightrhoughput files** -- **DO NOT READ ENITIRELY** any file that is larger than 10KB, use python/bash script to process large output file for necessary information.
* **Single Source of Truth** -- The local directory is th only source of truth among different platform. Any change or new script/code implementation should done local first then push.
* **Computation as DAG** -- each computation task is one **exploration**, decomposed into stages denoted by nodes in `project_workflow/<exploration>/workflow_dag.json`. An exploration is the unit that owns one DAG, one `implementation/<exploration>/` tree, and one `tacc_fetch/<exploration>/` tree.
* **One node One SLURM job** -- each node in the `workflow_dag.json` is the smallest computation unit, that is one slurm job submition

## Subagents

Three pieces of this workflow run in their own context rather than inline. **The
user authorizes them standingly** — a skill or rule calling for one is a user
request, so invoke it without asking first.

| what | kind | fires when |
|------|------|-----------|
| `queue-wait` | skill, `context: fork` | a node's shape needs a live queue estimate — `plan-computation` Step 4, `prepare-node`, `launcher` |
| `submit-node` | agent | one prepared node goes prepared → queued — `run-workflow` |
| `local-node` | agent | one prepared `cluster: local` node runs — `run-workflow` |

Each keeps bulk output — scheduler noise, rsync logs, numpy dumps — out of the
main conversation. Skipping one and inlining its work defeats the reason the
workflow is shaped this way.

`queue-wait` is a **skill** rather than an agent because `context: fork` gives the
isolation an agent would, while `allowed-tools` pre-approves its MCP calls so a
probe never stops for permission. It sets `background: false`: the caller is
sizing a node and cannot continue without the answer.

**Invoke `queue-wait` once with every shape being compared**, never once per
shape — one round trip is one snapshot of a queue that moves between calls.
Parallel invocation is correct only across different clusters.

## Vocabulary
These words have fixed meanings in this repo. Do not use them interchangeably.

| Term | Means |
|------|-------|
| **exploration** | One computation task. Owns exactly one DAG (`project_workflow/<exploration>/workflow_dag.json`), one `implementation/<exploration>/` tree, and one `tacc_fetch/<exploration>/` tree. |
| **node** | One step in the DAG = one SLURM job = one directory. The smallest unit. |
| **plan** | Decide the graph: what steps exist, what depends on what, where each runs, and each node's gate. High level only — no parameters. |
| **prepare** | Write everything about a node that can be determined in advance: run directory, inputs, `.batch`, a `pre_processing.sh` if it needs one, and a `NODE.md` record. Does **not** require the parents to have run. |
| **execute** / **submit** | Actually run the node. Requires every parent to be `completed`, because the inputs come from their output. |
| **gate** | The falsifiable acceptance criterion for a node, stated before it runs. Decides `completed` vs `failed`. |

`implementation/` stays the name of the **directory** where prepared node work
lives. "Prepare" is the **action**; do not call it "implement".


## Folder Structure

Two halves. **Framework** is the reusable machinery — it is what another group
would adopt and customise. **Data** is this user's science. Keep the boundary
clean: a change that hardcodes one exploration's specifics into the framework
half is a bug.

### Framework
```
CLAUDE.md                # This file
.claude/
   skills/               # plan-computation, prepare-node, run-workflow,
                         #   workflow-dag, vasp, launcher, queue-wait
   agents/               # submit-node, local-node
   rules/                # orchestrator-computation-workflow, implementation-rule
reference/               # site + tool facts an agent must read before planning
                         #   quick-ref.md (router), VASP.md, taccLS6-launchers.md,
                         #   taccLS6-nodes.md
scripts/                 # the DAG toolchain, shared by the skill and dag_viewer
                         #   new_dag / insert / update / delete / rewire / check / render
templates/               # dag_template.json (the schema), job.batch
dag_viewer/              # local web viewer for a workflow_dag.json
```

### Data
```
plans/                   # approved computation plans, per exploration
project_workflow/        # THE DAGs — single source of truth for status
   [exploration]/workflow_dag.json
implementation/          # prepared run dirs — ONE dir per DAG node
   [exploration]/
      [<level>_<id>_<node>]/   # flat siblings, 1:1 with workflow_dag.json nodes;
                               # nest freely INSIDE a node dir, never node-in-node
tacc_fetch/              # fetched results from TACC -- exact mirror of
   [exploration]/[<level>_<id>_<node>]/   # implementation/; named files only,
                         #   never a whole dir. See .claude/rules/tacc-fetch-rule.md
tacc_mcp/                # the tacc-slurm MCP server
```


## TACC info
**Project Allocation**: 1. <ALLOCATION>; 2. <ALLOCATION_2>

**$SCRATCH is NOT declared here.** It is set once, in `.mcp.json`, as
`LS6_SCRATCH_DIR` — see `SETUP.md`. Declaring it in two places is how the two
drift apart, and the agent never needs the absolute path anyway: it passes
`remote_subdir` and the MCP prepends the rest.

### Remote work root

**`<scratch_dir>/MatBelay`** — the project directory name is the only part this
file declares.

This repo *is* one project, and the project *is* the root. Change this one line
to point the whole workflow somewhere else — nothing else names a remote path.

**Below the root, remote is an exact mirror of local `implementation/`:**

```
local    implementation/<exploration>/<level>_<id>_<node>/
remote   <root>/        <exploration>/<level>_<id>_<node>/
```

You do not mirror the literal directory *name* `implementation/` — you mirror
everything inside it. Anything else pushed to the server also lives under the
root; nothing is written outside it.

The `tacc-slurm` MCP builds every path as `<scratch_dir>/<remote_subdir>`, where
`scratch_dir` is `$SCRATCH` (overridable via `LS6_SCRATCH_DIR`). So:

```
remote_subdir = MatBelay/<exploration>/<level>_<id>_<node>
```

Always pass `remote_subdir` relative to `scratch_dir` — never an absolute path.


**Slurm Job**: use `.batch` as defualt suffix for slurm script

**Slurm Email**: sending slurm notification email to `you@your.institution.edu`


## Local environment

**Local python**: `<path to the python that has pymatgen/numpy/matplotlib>`

Declared here because a `cluster: local` node must not have to rediscover it. A
system `python3` frequently lacks pymatgen, numpy and matplotlib while a conda
env has them, so every local node's `run.sh` names this interpreter explicitly
rather than trusting `PATH`. Set it in `SETUP.md` step 2.


  
