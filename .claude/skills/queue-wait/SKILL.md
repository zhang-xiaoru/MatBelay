---
name: queue-wait
description: >-
  Probe the live TACC scheduler for how long a HYPOTHETICAL SLURM job would wait
  in the queue, given a partition, a node count and a walltime. Use this whenever
  a job's start time or queue wait is in question — "how long will 4 nodes for 8h
  in normal wait", "is development faster for this", "would 2 nodes start sooner
  than 4", "check the queue before I submit", "which queue should this go in" —
  and ALWAYS when sizing a remote DAG node in `plan-computation` Step 4 or
  choosing a partition in `prepare-node`, even if nobody says the words "queue
  wait". Asks the scheduler via `sbatch --test-only` and submits nothing. Returns
  estimated start and wait per configuration, the raw scheduler messages, and the
  live `qlimits` caps. Do NOT use this to submit a job, to write a .batch script,
  or to size ranks/threads — it only reads the queue.
argument-hint: "<shapes to probe: partition, nodes, walltime — one per line>"
context: fork
background: false
allowed-tools: mcp__tacc-slurm__estimate_start, mcp__tacc-slurm__check_connection, mcp__tacc-slurm__list_clusters, Read, Grep
---

# Queue wait estimator

Answer one question: **given these job shapes, when would the scheduler start
each of them?** Ask the scheduler itself, live. Never submit anything.

Shapes to probe: **$ARGUMENTS**

This runs as a fork, so the caller is waiting on the answer and cannot be asked a
follow-up question mid-probe. Everything needed is in the arguments above; if a
required field is genuinely absent, say which one and stop rather than inventing
it — a made-up node count produces a confident number for a job nobody intends to
run, which is worse than an unanswered question.

Do not compose the probe command yourself. `mcp__tacc-slurm__estimate_start` does,
and that is the point: `--test-only` and `--wrap=hostname` are literals inside the
tool with no code path that omits them, so there is no route from "estimate the
wait" to "submit the job". Call the tool; report what it returns.

## 1. Read the shapes

Each configuration needs `partition`, `nodes` and `walltime`. `ntasks` and
`cpus_per_task` are optional and only change the answer in shared queues.

Worth having: `account`. This repo's allocations are `<ALLOCATION>` and `<ALLOCATION_2>`.
Priority is per-allocation, so an estimate without one uses the default account
and may not match the job actually submitted. Default to `<ALLOCATION>` unless the
arguments name the other.

Walltime is SLURM format: `MM:SS`, `HH:MM:SS`, `D-HH:MM:SS`.

Do **not** pre-screen shapes against remembered queue caps. Everything runs in
one round trip, so rejecting a shape early saves nothing, and the scheduler's own
refusal is more reliable than a table — the caps written down in this repo have
been wrong before (`development` was documented as 2 nodes; it is 8).

## 2. Probe — one call, all shapes

```
estimate_start(
  configs=[
    {"partition": "gpu-a100-small", "nodes": 1, "ntasks": 1,          "walltime": "08:00:00"},
    {"partition": "gpu-a100",       "nodes": 2, "ntasks": 6,          "walltime": "04:00:00"},
    {"partition": "development",    "nodes": 1, "cpus_per_task": 128, "walltime": "02:00:00"},
  ],
  account="<ALLOCATION>",
)
```

Put **every** shape in one call. All of them are probed in a single ssh round
trip, ~0.14 s apart — measured: one shape costs 1.46 s, six cost 2.15 s, so an
extra shape is 140 ms while an extra call is a whole connection. Shapes probed in
separate calls are snapshots from different moments, and comparing them is the
whole job.

**Never fan out one call per shape, in parallel or otherwise.** Parallel calls are
not more simultaneous — they are *less*: inside one round trip the probes land
140 ms apart, whereas separate calls land seconds apart. Parallelism here belongs
only **across clusters**, since `ls6` and `sp3` are different hosts that cannot
share a connection; those are two `estimate_start` calls, issued together.

Other parameters: `cluster` selects a machine other than the default
(`list_clusters` if the arguments name one).

If the tool cannot connect, say the probe could not run and stop — do not
substitute a guess. `check_connection` confirms whether the cluster is reachable
at all; the fix is usually for the user to run `ssh ls6`.

## 3. Report

The tool already returns the table, the raw scheduler messages, the live
`qlimits` caps and the staleness caveat. **Pass that through as it stands**
rather than retyping it — the raw messages in particular name the reason for a
rejection more reliably than your reading of them.

A row showing `**rejected**` means the scheduler declined: an invalid partition,
a shape over a cap, or an account with no balance. Its raw line says which.

**When *every* shape is rejected, suspect the site, not the shapes.** A submit
filter can abort a `--test-only` before the scheduler ever costs it, and it does
so identically for a 1-node and a 64-node request — so a table that is rejected
top to bottom is usually one cause, not N. The tool flags this as
**`probe unavailable`**; relay that rather than a per-shape verdict. Distinguish
it from a connection failure: the ssh worked, the tool ran, the scheduler
declined to answer. The two need different fixes and only one of them is
`ssh ls6`.

That distinction matters because the caller's next step differs. A per-shape
rejection is information — that shape is not viable, pick another. A blanket
refusal is an *absence* of information, and the caller has to size without it.

*(Known cause, fixed 2026-09-01: a non-login ssh left `$WORK2` unset, and TACC's
server-side `job_submit.lua` aborts every submission whose environment cannot
resolve it. If a blanket refusal names an environment variable, that is this
class of bug, not a queue fact.)*

Add only what the table cannot say: **one or two lines naming the shorter option
and what it costs.** Waiting less usually means running longer, a smaller queue,
or a tighter walltime cap, and that trade is why anyone asked.

Flag any disagreement between the live `qlimits` block and
`reference/taccLS6-nodes.md`. That file is a last-known snapshot and `qlimits` wins,
but a drift is worth reporting rather than silently absorbing.

Because this runs as a fork, the caller sees only what is returned — the main
conversation never sees the raw scheduler dump unless it is in the report. Keep
the table and the raw messages in; leave the reasoning out.

Stay inside your lane: report queue timing. Choosing ranks, threads or `KPAR`,
and writing the `.batch` file, belong to `prepare-node` and the tool's own skill.
