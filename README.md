# MatBelay

*Choose the scientific route. Let the agent belay the computation.*

MatBelay is a human-led, agent-assisted workflow for computational materials
science. It helps a researcher plan a calculation as a dependency graph,
prepare reproducible run directories, submit jobs to an HPC system, and track
each result against a criterion chosen before the run starts.

The researcher remains responsible for the question, method, parameters, and
physical interpretation. MatBelay handles the operational work around those
decisions and keeps it visible on disk.

> [!IMPORTANT]
> The current workflow targets Claude Code, TACC Lonestar6, VASP 6.5, SLURM,
> and TACC's `launcher_gpu`. You must replace the site-specific placeholders in
> the configuration and reference files before using it.

## Why MatBelay

A materials calculation rarely follows a single script from start to finish.
Structures are relaxed, convergence choices are revisited, independent jobs
fan out, results feed later stages, and failed approaches create new branches.
Some of that work may finish in minutes; other jobs can wait in a queue or run
for days.

An agent can help with this process, but an unstructured conversation is a poor
record of a long-running computation. MatBelay gives the work a durable shape:

- each investigation is an **exploration**;
- each exploration has one directed acyclic graph (DAG);
- each DAG node is one local computation or one SLURM job;
- dependencies and job state are recorded in `workflow_dag.json`;
- generated inputs and scripts remain reviewable in local directories; and
- every node has a gate that defines what counts as an acceptable result.

## How it works

MatBelay separates planning, preparation, and execution. Each transition is a
human checkpoint.

1. **Plan**

   The agent turns the scientific task into a DAG: what must run, what each
   step depends on, where it runs, how independent tasks are dispatched, and
   the approximate resources and live queue wait for each remote node. Planning
   creates no calculation inputs and submits nothing.

2. **Prepare**

   The researcher reviews one node at a time. After approval, the agent writes
   its input files, batch script, optional pre- and post-processing scripts, and
   a `NODE.md` record under `implementation/<exploration>/`. Preparation is
   local and does not spend allocation.

3. **Run**

   After one explicit approval for the eligible set, MatBelay runs local nodes
   or uploads and submits remote nodes. It records job IDs and status changes,
   monitors scheduler and application errors, fetches only the files needed for
   evaluation, and checks the completed result against its gate.

An upstream node must be `completed` before a dependent node can run. Independent
branches can proceed in parallel, while a failed branch stops without blocking
unrelated work.

### Gates

Every prepared node states its acceptance criterion in `NODE.md` before it
runs.

| Gate type | Example | What happens after the run |
|---|---|---|
| `objective` | `max force < 5 meV/Å` | A script can evaluate it, so the workflow may continue automatically. |
| `judgement` | `no imaginary modes` | The workflow stops and presents the evidence for human review. |

A clean SLURM exit is not treated as proof that the calculation is physically
valid. Process status and scientific acceptance are separate decisions.

## Local and remote work

The local repository is the source of truth. Inputs and scripts are written
locally first, then copied into a designated project directory under the
cluster's scratch filesystem.

```text
local   implementation/<exploration>/<level>_<id>_<node>/
remote  <scratch>/MatBelay/<exploration>/<level>_<id>_<node>/
result  tacc_fetch/<exploration>/<level>_<id>_<node>/
```

The agent does not remain running on a compute node. SLURM owns the submitted
job, while a local watcher checks the scheduler through short SSH calls. The
workflow DAG holds the authoritative dependency and status record.

## What's included

| Component | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Session contract, vocabulary, directory invariants, and local/remote conventions. |
| [`scripts/`](scripts/) | Standard-library Python tools to create, validate, edit, and render workflow DAGs, plus the job watcher. |
| [`templates/`](templates/) | The DAG schema and a Lonestar6 SLURM batch skeleton. |
| [`reference/`](reference/) | Replaceable facts about software builds, launch commands, hardware, and queue limits. |
| [`dag_viewer/`](dag_viewer/) | A local browser-based DAG viewer and metadata editor. The prebuilt UI needs no Node.js installation. |
| [`tacc_mcp/`](tacc_mcp/) | FastMCP server for SSH checks, queue estimates, uploads, submissions, status, logs, cancellation, remote commands, and selective result fetching. |
| [`plans/`](plans/) | Approved, dated computation plans for each exploration. |
| [`project_workflow/`](project_workflow/) | One authoritative `workflow_dag.json` per exploration. |
| [`implementation/`](implementation/) | Prepared inputs and scripts, one directory per node. |
| [`tacc_fetch/`](tacc_fetch/) | Selected results fetched from the cluster. Contents are ignored by Git. |

The framework files are separate from exploration data. Site conventions and
reusable logic belong in the upper half of the table; one investigation's
inputs and results belong in the final four directories.

### Skills

| Skill | Purpose |
|---|---|
| [`plan-computation`](.claude/skills/plan-computation/SKILL.md) | Builds the high-level DAG for a new or continuing exploration. It maps dependencies, decides where each node runs and how work is dispatched, estimates resources and queue waits, and records the gates. It does not write calculation inputs or submit jobs. |
| [`workflow-dag`](.claude/skills/workflow-dag/SKILL.md) | Creates and edits `workflow_dag.json` with the repository's validation scripts. Those scripts keep node IDs, levels, edges, and lifecycle states consistent. |
| [`prepare-node`](.claude/skills/prepare-node/SKILL.md) | Takes one approved node, settles its parameters, and writes its run directory, inputs, scripts, and `NODE.md`. It does not upload or submit anything, and it leaves the DAG unchanged. |
| [`run-workflow`](.claude/skills/run-workflow/SKILL.md) | Works out which prepared nodes can run and asks for approval before spending allocation. It then runs local work or submits remote jobs, records their state, and checks finished results against their gates. |
| [`queue-wait`](.claude/skills/queue-wait/SKILL.md) | Asks the live scheduler when proposed SLURM requests would start and reports the current `qlimits`. It uses `sbatch --test-only`, so it never submits a job. |
| [`vasp`](.claude/skills/vasp/SKILL.md) | Generates VASP inputs and chooses parameters, including the parallel settings for CPU and GPU runs. It also defines how MatBelay checks whether a finished VASP calculation succeeded. |
| [`launcher`](.claude/skills/launcher/SKILL.md) | Fits independent tasks into one SLURM allocation. It chooses the dispatch shape and writes the job list, worker layout, and launcher script. |

### Rules

| Rule | Purpose |
|---|---|
| [`orchestrator-computation-workflow`](.claude/rules/orchestrator-computation-workflow.md) | Guides planning and preparation. It identifies the exploration, builds and reviews the DAG, asks which nodes to prepare, and prepares them one at a time. Execution is a separate workflow. |
| [`implementation-rule`](.claude/rules/implementation-rule.md) | Defines where prepared work belongs. Every node gets one directory, and those directories remain flat siblings under their exploration. |
| [`tacc-fetch-rule`](.claude/rules/tacc-fetch-rule.md) | Files fetched from TACC follow the same node layout as `implementation/`. The rule fetches named files instead of whole directories and keeps licensed `POTCAR` files out of the repository. |

### Agents

| Agent | Purpose |
|---|---|
| [`submit-node`](.claude/agents/submit-node.md) | Moves one prepared remote node into the SLURM queue. It uploads the directory, runs pre-processing, submits the batch script, and confirms that the job is queued. Node selection and result evaluation stay with `run-workflow`. |
| [`local-node`](.claude/agents/local-node.md) | Runs one prepared node on the local machine. It fetches any required parent output, runs the pre-processing, calculation, and post-processing scripts, then reports what happened. `run-workflow` still judges the scientific gate. |

## Requirements

- Claude Code, opened from the repository root
- a TACC Lonestar6 account, allocation, and working SSH alias
- an active SSH ControlMaster session for TACC's two-factor authentication
- Python 3.10 or newer for the MCP server
- [FastMCP](https://github.com/PrefectHQ/fastmcp) installed in the Python
  interpreter configured in `.mcp.json`
- GNU `rsync` for file transfers, especially on macOS where the system
  `openrsync` may be incompatible with TACC
- access to a licensed VASP installation and pseudopotential library
- a local Python environment with `pymatgen`, NumPy, and Matplotlib when local
  nodes use those packages

The DAG command-line tools and the production DAG viewer use only the Python
standard library. Node.js is needed only to change and rebuild the viewer UI.

## Setup

From a local clone:

```bash
cd MatBelay
python3 --version
python3 -m pip install fastmcp
cp .mcp.json.example .mcp.json
```

Then follow [`SETUP.md`](SETUP.md). It walks through four kinds of configuration:

1. account identity, allocation, scratch path, SSH alias, and email;
2. the local Python interpreter used for science tasks;
3. VASP builds, modules, launch commands, and pseudopotential locations; and
4. Lonestar6 node hardware and current queue limits.

Anything in angle brackets is a placeholder. Do not plan or submit a VASP node
until the site reference files are filled and verified.

After configuration, run the smoke checks in `SETUP.md`, then open Claude Code
from the repository root and describe a calculation. A useful first request is:

```text
Plan a new exploration for <scientific goal>. Do not prepare or run any node
until I have reviewed the DAG.
```

Once the DAG is approved, the workflow asks which nodes to prepare. Submission
is a separate request, for example `Run <exploration>`, and includes a final
allocation estimate and approval before jobs are sent to SLURM.

## Inspect a workflow

Render a DAG in the terminal:

```bash
python3 scripts/check_dag.py project_workflow/<exploration>/workflow_dag.json
python3 scripts/render_dag.py project_workflow/<exploration>/workflow_dag.json
```

Or start the local viewer:

```bash
python3 dag_viewer/serve.py
```

Open the printed URL, normally <http://127.0.0.1:8765>. See the
[`dag_viewer` guide](dag_viewer/README.md) for editing and development options.

> [!WARNING]
> Close the viewer while the run driver is updating the same DAG. Both can write
> node metadata, and concurrent writes are not locked in this release.

## Safety model

MatBelay uses several procedural safeguards:

- planning, preparation, and allocation-spending execution are separate steps;
- preparation is reviewed one node at a time;
- execution has one explicit approval for the eligible set and estimated cost;
- queue estimates use `sbatch --test-only` and do not submit work;
- graph edits go through validation scripts instead of manual JSON edits;
- the remote work root is declared once and mirrors local node directories;
- fetched results use named-file allowlists in the normal workflow;
- VASP `POTCAR` files are assembled remotely, and result fetching excludes
  them; and
- the watcher reports state changes and known errors instead of streaming large
  output files into the agent context.

> [!CAUTION]
> This is not a security sandbox. Its MCP server can upload files, run commands
> on a login node, submit or cancel SLURM jobs, and consume an allocation. Review
> generated inputs and batch scripts, supervise the first runs closely, and use
> a dedicated scratch project directory.

## What MatBelay does not decide

MatBelay is not an autonomous research agent. It can gather information and
suggest a plan, but the researcher decides:

- which scientific problem to study;
- whether the computational method is appropriate;
- which physical assumptions and parameters are acceptable; and
- whether the resulting evidence supports a scientific conclusion.

You should understand the simulation software, HPC environment, and relevant
physics well enough to review those decisions.

## Current scope and limitations

- End-to-end support is limited to Claude Code and TACC Lonestar6.
- VASP is the only computational package with a complete preparation skill,
  application-specific health probe, and success-check contract.
- The watcher recognizes scheduler, runtime, and known application errors. It
  does not infer a hang from quiet output; SLURM walltime remains the backstop.
- The DAG viewer and run driver do not coordinate concurrent writes.

## Roadmap

- complete Stampede3 support and add other SLURM clusters;
- add preparation and validation skills for more materials-science tools;
- add Slack or Discord notifications;
- strengthen command and submission safeguards;
- add literature review and research-audit workflows;
- support workflows that include new method development; and
- expand automated and end-to-end testing.

## License

MatBelay is released under the MIT License. See [`LICENSE`](LICENSE).
