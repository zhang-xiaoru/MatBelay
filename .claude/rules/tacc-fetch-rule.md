---
paths: tacc_fetch/**
---
# Fetched-results Protocol

`tacc_fetch/` holds what came back from the cluster. Three rules, and they exist
because the tree currently holds **585 MB of which ~140 MB has ever been opened**.

## 1. The same structure as `implementation/`

```
implementation/<exploration>/<level>_<id>_<node>/     prepared here
<remote root>/<exploration>/<level>_<id>_<node>/      ran there
tacc_fetch/<exploration>/<level>_<id>_<node>/         came back here
```

One shape for all three, so `<id>_<name>` identifies a node wherever you are.
Fetched output is filed under **the node that produced it**, never under a
semantic name.

The cost of not doing this is already on disk: `tacc_fetch/defect_kappa/`
holds `host_ifc`, `defect_ifc`, `pristine_5x5x7`, `gplus_mesh_8x8x8` — and you
cannot tell which node produced any of them without knowing the science.

*(Those legacy directories stay as they are. This rule governs new fetches.)*

## 2. Name the files. Never fetch a directory

Pass `include` to `fetch_results`. Without it rsync takes everything, including
subdirectories — and a displacement farm has hundreds:

```
2_5_ifc_BC/     remote: ~300 task dirs      fetched: 4 files, 13 MB   ✓
1_2_host_ifc/   remote: 2 task dirs         fetched: all of them,
                                            duplicated POTCARs, 0-byte
                                            vasp.out                  ✗
```

Same node type, opposite outcomes, purely because one farm was small enough that
nobody noticed. `include` also stops the recursion, so the task dirs stay put.

What to fetch is **task-specific, not tool-specific**: no local node here reads a
genuine VASP output file — what they consume from a `tool: vasp` node is
`FORCE_CONSTANTS`, `SPOSCAR`, `POSCAR`, `BORN`. The list belongs in the consuming
node's `NODE.md` → `## From upstream`, written when the task is understood.

## 3. Never `POTCAR`

Licence-restricted, ~700 KB, and assembled on the cluster by the `vasp` skill's
`generate_POTCAR.sh` — so a local copy is both a licence problem and redundant.
`fetch_results` refuses it. Five copies predate the refusal; leave them, but do
not add more.

## Fetching by hand

```
fetch_results(remote_subdir="hpc_project/<expl>/<level>_<id>_<node>",
              local_output_dir="tacc_fetch/<expl>/<level>_<id>_<node>",
              include=["OUTCAR"])
```

The remote root is declared in `CLAUDE.md` in exactly one place — read it there.
`fetch_results` reports the file count and total size of what landed, so an
accidental whole-directory pull announces itself instead of being discovered
months later.

## Symlinks

`fetch_results` passes `-L`, which copies what a symlink *points at*. Without it
rsync copies the link, and a link to an absolute remote path dangles the instant
it lands here — the file looks present and cannot be opened.
`tacc_fetch/defect_kappa/gplus_mesh_8x8x8/` has three such files
(`BORN`, `FORCE_CONSTANTS`, `POSCAR`) from before the fix.
