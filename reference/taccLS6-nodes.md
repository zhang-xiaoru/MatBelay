# TACC node hardware & queue limits

**Source of truth is the live scheduler, not this file.** Node hardware below is
stable; queue caps drift. The cheapest refresh is the **`estimate_start`** MCP
tool — it prints live `qlimits` under every probe, so checking the caps costs
nothing extra once you are asking about wait times anyway:

```
estimate_start(configs=[{"partition": "normal", "nodes": 4, "walltime": "08:00:00"}],
               account="<ALLOCATION>")        # table + live qlimits
```

Treat any mismatch as **`qlimits` wins**, and correct this file when you find one.
That has already been needed once: `development` was recorded here as a 2-node
cap for two months and is actually 8.

LS6 queue caps below were read from `qlimits` on **2026-09-01**. Node hardware is
from TACC docs and the user's own `relax.batch` (2026-07). Charge rates have
their own dated caveat under the queue table — `qlimits` does not report them.

---

## Lonestar6 (LS6)

### Node hardware

| Node type      | Cores/node | RAM/node | GPUs/node        |
|----------------|-----------:|---------:|------------------|
| AMD Milan CPU  | 128        | 256 GB   | —                |
| A100 GPU       | 128        | 256 GB   | 3 × NVIDIA A100 40GB |
| H100 GPU       | 96         | 384 GB   | 2 × NVIDIA H100 80GB |
| vm-small       | 16         | 32 GB    | —                |

**A Milan node is 128 cores, and `-N × cores_per_node` is the whole budget.**
How those cores are divided into MPI ranks and threads is the *tool's* decision,
not a property of the hardware — it depends on the code's build and its
parallelisation tags. Ask the tool's skill for `-n` and `OMP_NUM_THREADS`; for
VASP that is `vasp` → `## Parameter rules`, which owns the rank/thread/`KPAR`
protocol. This file tells you how many cores and GPUs you have, and nothing about
how to spend them.

On a GPU node the count that matters is GPUs, not cores: 3 per A100 node, 2 per
LS6 H100 node.

### Queue limits — `qlimits`, LS6, 2026-09-01

| Queue            | Node type | Min–Max nodes/job | Max wallclock | Nodes/user | Jobs running/user | Jobs queued/user |
|------------------|-----------|------------------:|--------------:|-----------:|------------------:|-----------------:|
| `development`    | Milan CPU | 1–8               | 2:00:00       | 8          | 1                 | 3                |
| `normal`         | Milan CPU | 1–64              | 48:00:00      | 64         | 20                | 100              |
| `large`          | Milan CPU | **65**–256        | 48:00:00      | 256        | 1                 | 4                |
| `vm-small`       | vm-small  | 1–1               | 48:00:00      | 4          | 4                 | 16               |
| `gpu-a100`       | A100      | 1–8               | 48:00:00      | 12         | 8                 | 32               |
| `gpu-a100-dev`   | A100      | 1–2               | 2:00:00       | 2          | 1                 | 3                |
| `gpu-a100-small` | A100      | 1–1               | 48:00:00      | 3          | 3                 | 12               |
| `gpu-h100`       | H100      | 1–1               | 48:00:00      | 1          | 1                 | 4                |

Refresh with `estimate_start`, which prints live `qlimits` alongside every
probe — that is the cheapest way to keep this table honest, since it costs no
extra round trip. Pass every shape you want compared in ONE call.

**The last three columns are the ones that change a plan.** A cap on *concurrent*
jobs is invisible in the per-job caps and routinely decides the dispatch shape:
`gpu-a100-small` runs **3 jobs at once**, so three single-GPU jobs can start
together, while `development` and `gpu-a100-dev` run **one job at a time** no
matter how many you queue. `large` has a *minimum* of 65 nodes — it is not a
bigger `normal`, and a 64-node request cannot use it.

### Charge rates — *not* verified by `qlimits`

| Queue | Charge rate |
|---|---|
| `development`, `normal`, `large` | 1× |
| `vm-small` | fractional |
| `gpu-a100`, `gpu-a100-dev` | 4× |
| `gpu-a100-small` | fraction of 4× (1 GPU + ¼ node) |
| `gpu-h100` | higher than 4× |

`qlimits` has no charge-rate column, so these remain at their **2026-07**
provenance and were not confirmed by the 2026-09-01 probe. The LS6 user guide is
the source if they matter to a decision.

Billing: `SUs = nodes × wallclock_hours × charge_rate`, minimum 15 min charged.
GPU nodes bill ~4× a CPU node, so packing small jobs onto one node is both faster
(less waiting) and cheaper — one node-hour, not three.

---
