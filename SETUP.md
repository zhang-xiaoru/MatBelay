# Set up MatBelay for your site

MatBelay needs a small amount of local and cluster-specific information before
it can plan or run a calculation. Some values come from you; the rest should be
measured on the cluster and recorded with their source and date.

The setup falls into four parts:

| Category | Examples | Where to record it |
|---|---|---|
| 1. Account identity | SSH alias, `$SCRATCH`, allocation, notification email, project root | `.mcp.json` and `CLAUDE.md` |
| 2. Local machine | Python interpreter with pymatgen and NumPy | `CLAUDE.md` |
| 3. Cluster software | VASP builds, modules, POTCAR libraries, launcher | `reference/VASP.md` and `reference/taccLS6-launchers.md` |
| 4. Cluster hardware and queues | Cores and GPUs per node, `qlimits` caps | `reference/taccLS6-nodes.md` |

> [!IMPORTANT]
> Replace every site-specific value in angle brackets before use. This command
> finds the common account and identity placeholders:
> `grep -rn "<ALLOCATION>\|<system-id>\|<username>\|<YOUR NAME>\|your.institution" .`
>
> The reference templates also contain descriptive placeholders such as
> `<<cluster>>` and `<<module>>`. Work through those files directly rather than
> treating the grep command as a complete audit.

## Step 0: check the repository settings

Choose the remote project directory name. The default is `MatBelay`, set in
   the **Remote work root** section of `CLAUDE.md`. Uploaded files will live
   under `$SCRATCH/<that name>/`.

Keep the remote root in one place. If you rename it, update the declaration in
`CLAUDE.md` rather than adding the path elsewhere.

## Step 1: connect the MCP server to your account

Create your local MCP configuration:

```bash
cp .mcp.json.example .mcp.json      # .mcp.json is gitignored; never commit it
```

Fill in these fields:

| Field | Value |
|---|---|
| `command` | The absolute path returned by `which python3`. This interpreter runs the MCP server, so it must be Python 3.10 or newer and have FastMCP installed. |
| `LS6_SSH_ALIAS` | The `Host` name from your `~/.ssh/config` entry for Lonestar6. |
| `LS6_SCRATCH_DIR` | The value of `echo $SCRATCH` when run on the cluster. |

Install FastMCP with `<path-to-python> -m pip install fastmcp`, using the same
interpreter path that you put in `command`.

In the **TACC info** section of `CLAUDE.md`, replace `<ALLOCATION>` or
`<ALLOCATION_2>` with your allocation code or codes, then set the SLURM
notification email.

`$SCRATCH` belongs only in `.mcp.json`. The agent passes a relative
`remote_subdir` to the MCP server, which prepends the scratch path. Repeating
the absolute path in `CLAUDE.md` would create two settings that can drift apart.

Test the SSH alias before continuing. `ssh <alias> hostname` must work without
another interactive login prompt. TACC requires two-factor authentication, so
this normally means opening a ControlMaster session with `ssh <alias>` first.
If the watcher later reports `BLIND`, reopen that session.

## Step 2: choose the Python interpreter for local nodes

Find the interpreter that has the local science packages:

```bash
python3 -c "import pymatgen, numpy, matplotlib" && which python3
```

If the system interpreter fails, activate the appropriate conda environment and
run the command again. Copy the resulting path into the **Local environment**
section of `CLAUDE.md`.

This interpreter may differ from the one configured for the MCP server. Local
nodes write its full path into `run.sh` instead of trusting `PATH`. An incorrect
path will therefore fail every local node that uses the science stack.

## Step 3: record the cluster software

First identify how you receive VASP. The setup supports a provider-managed TACC
module and a user-compiled build. Both need the same execution facts, but a
managed module may not expose its internal compiler or library configuration.

Record these facts for either installation type:

| Required fact | What to capture |
|---|---|
| Build identity | Exact module and version, or the path to the user-compiled build |
| Role | Whether each build is for CPU or GPU execution |
| Environment | The command that selects the build and the binary paths it produces |
| Parallel model | Pure MPI, MPI with OpenMP, OpenACC, or the provider's documented model |
| Execution | Launcher command, rank and thread expectations, and supported hardware |
| VASP data | Pseudopotential library locations available to your account |

Compiler flags, linked math libraries, optimization flags, and internal build
paths are useful provenance for a user-compiled build. They are optional when a
provider-managed module does not publish them.

### Option A: provider-managed TACC module

Run these probes on Lonestar6, replacing the module placeholder once
`module spider vasp` shows the available versions:

```bash
module spider vasp
module spider <vasp module/version>
module show <vasp module/version>
module load <vasp module/version>
module list
which vasp_std vasp_gam vasp_ncl
module avail 2>&1 | tr ' ' '\n' | grep -i launcher
ls <pseudopotential library root>
```

Write the module name, version, load command, binary paths, and probe date in
`reference/VASP.md`. Use `NOT EXPOSED BY PROVIDER` for internal build details
that are absent from the module help and TACC documentation, and state what you
checked. This is better than copying values from a different VASP build.

The parallel model and launch command are still required. Take them from TACC
documentation or a TACC support response and record that source. If neither
source establishes them, mark the build `NOT VERIFIED` and do not prepare jobs
with it yet. A module name or `which vasp_std` output does not prove whether a
CPU binary is pure MPI or hybrid.

### Option B: user-compiled build

Run these probes on Lonestar6 and record the results in `reference/VASP.md` and
`reference/taccLS6-launchers.md`:

```bash
which vasp_std vasp_gam vasp_ncl          # CPU build on PATH?
<gpu prerequisite> && which vasp_std      # does a GPU build shadow the CPU one?
grep -E "^FC |CPP_OPTIONS" <build>/makefile.include   # hybrid MPI+OpenMP, or OpenACC?
module spider <compiler> ; module spider <hdf5>       # prerequisites
ls <pseudopotential library root>         # e.g. $WORK/.../vasp_pot/
module avail 2>&1 | tr ' ' '\n' | grep -i launcher    # which launchers exist
```

The CPU and GPU builds may use the same executable names, so record exactly
which prerequisite selects each build. A hybrid MPI and OpenMP build uses
`OMP_NUM_THREADS` and launches with `ibrun`. An OpenACC build uses one rank per
GPU and launches with `mpirun`. The wrong combination can launch a different
binary without producing an obvious configuration error.

`reference/examples/VASP.lonestar6.md` records a set up of self-compiled VASP as an example.

## Step 4: verify the hardware and queues

Run these commands on the cluster:

```bash
qlimits                                   # queue caps -- these drift, re-check often
sinfo -p <partition> -h -o "%n %c"        # cores per node
scontrol show node <node> | grep -E "CPUTot|Sockets|Gres"
```

Write the results and probe date in `reference/taccLS6-nodes.md`. Queue limits
change, so the live scheduler remains authoritative.

The `estimate_start` MCP tool, used by the `queue-wait` skill, prints current
`qlimits` below every estimate. Compare that output with the reference file
whenever you check a queue wait, and update the file when they disagree.

`qlimits` does not report charge rates. Take those from the site's user guide
and give them a separate source date, as the shipped reference file does.

## Step 5: verify the setup

Run the local smoke test from the repository root:

```bash
python3 scripts/new_dag.py --exploration smoke --description "setup check"
python3 scripts/check_dag.py project_workflow/smoke/workflow_dag.json   # expect: ok
python3 dag_viewer/serve.py                                             # expect: no "dist not built"
rm -rf project_workflow/smoke
```

When the viewer starts, open the URL it prints and confirm that the empty
`smoke` exploration appears. Stop the server with `Ctrl-C`, then remove the
temporary exploration with the final command.

Next, ask the agent for a queue-wait estimate. That request checks the MCP
server, SSH alias, and allocation in one pass. The probe uses
`sbatch --test-only`, so it does not submit a job.

## Record what you could not verify

Every reference file should say when and how its facts were checked. Mark any
value you could not confirm instead of filling the gap with a guess. For example,
the shipped `taccLS6-nodes.md` notes that SLURM returned `Gres=(null)`, so its GPU
count did not come from that probe.

This distinction matters downstream. A guessed value that looks measured can
silently produce the wrong job size; an explicit unknown forces the workflow to
stop and ask.

## Supported scope

This release targets TACC Lonestar6. Its partition names (`gpu-a100` and
`gpu-h100`), GPU counts, `ibrun` command, `qlimits` output, Lmod modules, and
`launcher_gpu` conventions are LS6 facts written directly into the current
skills and references.

The reusable and site-specific pieces divide as follows:

| Portable | LS6-specific |
|---|---|
| DAG command-line tools in `scripts/` | Site facts in `reference/*.md` |
| Plan, prepare, and run orchestration skills | The `tacc-slurm` MCP server |
| `workflow-dag` schema and validation rules | Partition names and node counts in `launcher` |
| VASP parameter rules for pure MPI and hybrid builds | Build prerequisites and launch commands |

Adapting MatBelay to another SLURM cluster requires new reference files and
launch commands. The current `launcher` skill also contains hardcoded LS6
partition names. Other TACC systems and HPC centers have not been tested as
supported configurations. Support for those systems is planned, but it is not
part of this release.
