# Quick reference for the tools

A tool listed here is available in this setup. Where it runs, and how it is
invoked, is in the reference it points at — this table carries no facts of its own
beyond "this exists, go here".

A tool that is **not** listed cannot be planned against. Stop and report it rather
than assuming it exists somewhere.

| Tool | Where to learn |
|------|----------------|
| VASP | `reference/VASP.md` — builds, prerequisites, launch commands, node layout. Input generation and parameter choice: skill `vasp`. |
| SLURM / queues / node sizing | `reference/taccLS6-nodes.md` — node hardware, queue caps, charge rates. Writing the `#SBATCH` header: skill `prepare-node` → `references/sbatch_header.md`. Skeleton: `templates/job.batch`. |
| gpu_launcher | `reference/taccLS6-launchers.md` — module, variables, entry point, and how the launcher must agree with the packed tool. Dispatch shapes, sizing, joblist and the dispatcher: skill `launcher`. |

Rows marked *(not written yet)* are known to be in use but have no environment
notes here. You can plan around them, but you are working from general knowledge
rather than this setup's conventions — say so in the plan rather than implying the
invocation is confirmed.

**And say what it will cost at run time.** A tool with no skill has no
`## Success check`, so `run-workflow` **stops** at that node rather than judging
it — see the contract table below. Planning such a node is allowed; planning it
*silently* is not, because the stop then arrives as a surprise after the
allocation is already spent. State in the plan that the node will halt for a
human verdict, or write the tool a skill first.

**`gpu_launcher` is a module, not a `tool` value.** The `tool` field names the
code being packed — `vasp` for a VASP displacement farm — never the launcher that
packs it. That matters because the probe path *is* the tool name (below), and
`.claude/skills/gpu_launcher/` does not exist: the skill is `launcher`, and it is
reached through the dispatch, not through `tool`.

## What a tool skill owes the framework

Two protocols here are deliberately tool-free — the job watcher and the run
driver. Each knows *that* something must be judged and nothing about how, so each
reads a named section from the tool's own skill. A tool used for batch jobs owes
both:

| Contract | Where it lives | Read by | If missing |
|---|---|---|---|
| a **health probe** | `.claude/skills/<tool>/scripts/probe.sh` | `scripts/watch_jobs.sh` | falls back to the generic probe — degraded, not blocked |
| a **`## Success check`** answering four questions | that tool's `SKILL.md` | skill `run-workflow` | **stops.** A gate cannot be guessed |

The two fallbacks differ on purpose. Missing a probe means you learn less about a
running job; missing a success check means you would have to invent a criterion,
and a wrong criterion produces a result that looks fine.

The four questions: *did it exit cleanly · did it meet its criterion · if not,
budget or failure · if budget, what carries over to the next round and what
changes.* The `vasp` skill is the worked example.

## Health probes

A DAG node that submits a batch job declares which software it runs in its
**`tool`** field. That value is copied verbatim into the watchlist, and
`scripts/watch_jobs.sh` turns it into a probe **by convention**:

```
.claude/skills/<tool>/scripts/probe.sh     if it exists
scripts/probe_generic.sh                   otherwise
```

Nothing maps names to paths — the path *is* the name. A registry would be a
second place to keep in step, and the failure it produces is silent: a stale
entry disables monitoring for a job that looks perfectly watched.

| `tool` value | Probe | What it reads |
|---|---|---|
| `vasp` | `.claude/skills/vasp/scripts/probe.sh` | `vasp.out`, `*/vasp.out` (launcher tasks) and the SLURM `.e` file — VASP's own panics plus the runtime beneath it |
| `phonopy` | *(none yet — generic)* | |
| `shengbte` | *(none yet — generic)* | |
| `thirdorder` | *(none yet — generic)* | |
| *(empty)* | `scripts/probe_generic.sh` | the SLURM `.e` file only — SLURM / MPI / OS errors, which look the same for every code |

**A probe reports what the code said. It does not judge whether the run is going
well.** No counters, no rates, no timing. A threshold for "too quiet" would have
to depend on the code, the system size and the calculation type at once, and
being wrong in the noisy direction is worse than missing a hang — a channel that
cries wolf stops being read. A job that hangs without complaining is caught by
SLURM at walltime, as `TIMEOUT`.

The generic probe is a real fallback, not a placeholder: a segfault, an OOM kill
and an MPI abort look identical whatever the binary was. What it cannot see is
anything the code says in its own vocabulary.

**Writing one is how a tool graduates.** ~40 lines: one ssh, bounded tails of
whatever files that code complains into, and two `grep` lists — signatures you
have actually seen in a failed run, not ones you expect to exist. Put it at the
conventional path and it is picked up at the next poll, including by jobs
already running, which is why probes live here rather than being copied into
node directories.

Two things every probe must do: **exit 0 always** (a probe that fails must not
take the watcher with it) and **use `ssh -n`** (the watcher calls probes from
inside a `while read` loop, and an ssh without `-n` drains that loop's stdin, so
only the first job of each tick would ever be polled).

## Adding a tool

* **Needs real judgement** — how to parallelise it, when to split a run, which of
  several modes to use → give it a **skill**, and point this table at the skill.
* **Environment facts only** — module lines, binary name, where outputs land, how
  to check it is installed → write a **reference file** here and point at that.

Keep each tool's availability, environment and verify command in that one
destination. Two documents describing the same tool will drift, and the one you
happen to read will be the stale one.

A tool that will run **batch jobs** also wants a `probe.sh` at the conventional
path above, and a row in the probe table. Until it has one its jobs are still
watched, just less specifically.
