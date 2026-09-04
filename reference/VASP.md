# VASP reference

> **FILL THIS IN BEFORE USE.** This template supports both user-compiled VASP
> builds and provider-managed modules such as a TACC VASP module. Fill every
> operational field before planning a VASP node.
>
> A managed module may not expose its compiler flags, linked libraries, or
> internal build path. Write `NOT EXPOSED BY PROVIDER`, followed by the source
> and date you checked, in those fields. Do not guess. Missing build internals
> are acceptable; a missing parallel scheme or launch command is not.
>
> A filled worked example for two user-compiled builds is in
> [`examples/VASP.lonestar6.md`](examples/VASP.lonestar6.md). Read it alongside
> this template, but do not assume a managed module will expose the same detail.
>
> Delete this block once the file is filled.

Conventions and environment rules for using VASP at this site.

*Environment facts below were probed on **<<cluster>>** on **<<YYYY-MM-DD>>**.
Re-check with the commands in [Verifying](#verifying) if a build is moved or
rebuilt.*

## Availability

**Version(s):** <<e.g. 6.5.0>>

**How obtained:** <<a module | user-compiled | vendor install | container>>

| Build | Path or module | Binaries |
|-------|----------------|----------|
| <<CPU>> | <<`module load vasp/6.5.0` OR an absolute bin path>> | <<vasp_std, vasp_gam, vasp_ncl>> |
| <<GPU — delete if none>> | <<...>> | <<...>> |

<<**If there is no module**, say so explicitly and say where the binaries come
from instead. A reader who tries `module load vasp` and gets nothing, or gets a
different build than you use, has no way to know that was expected.>>

### What must be recorded

The workflow needs the public execution interface, not a reconstruction of a
provider's private build process.

| Required before use | Record when available |
|---|---|
| Exact module or prerequisite, version, CPU/GPU role, binary names, parallel scheme, launch command, thread environment when applicable, and supported hardware | Compiler, build flags, linked math libraries, optimization flags, toolkit versions, and internal build paths |

For a user-compiled build, take both columns from the build files and your test
records. For a managed module, use `module spider`, `module show`, provider
documentation, or a provider support response. Name the source and the date.
The module name and `which vasp_std` identify the executable, but they do not by
themselves prove whether a CPU build is pure MPI or hybrid.

### Hazards

<<Delete if none — but look first. The two that bite people:

  * **Two builds sharing binary names.** If a CPU and GPU build both provide
    `vasp_std`, whichever prerequisite ran last wins `$PATH`. A script that loads
    the GPU prerequisite and then calls the CPU launcher runs the wrong binary
    with no error. Say which prerequisite shadows which.
  * **A prerequisite that pulls in a conflicting toolchain**, so load order
    matters relative to other modules (a launcher module, for instance).>>

---

## CPU VASP

**Version:** <<...>>

### Build and execution information

| | |
|---|---|
| Provided as | <<provider-managed TACC module, user-compiled, vendor install, or container>> |
| Build path | <<build root, module-resolved installation path, or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Scheme | <<**pure MPI** OR **MPI + OpenMP hybrid**>> |
| Scheme evidence | <<`makefile.include` flags, provider documentation URL/title, support response and date, or `NOT VERIFIED`>> |
| Compiler | <<... or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Math libraries | <<MKL / OpenBLAS / ...; FFTW, BLAS, LAPACK, scaLAPACK; or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Optimisation | <<... or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Binaries | <<...>> |

> **The scheme decides which parallel tags go in the INCAR, so get it right.**
> For a user-compiled build, check `makefile.include`: `-D_OPENMP` in
> `CPP_OPTIONS` means hybrid. For a managed module, record the scheme stated by
> the provider. Do not infer it from the module name or executable name.
>
> * **hybrid** → **omit `NCORE` and `NPAR`**; `OMP_NUM_THREADS` plays `NCORE`'s role.
> * **pure MPI** → set `NCORE`; run one MPI rank per physical core.
>
> The `vasp` skill implements both. It reads which one from this line:
>
> **This build is: <<pure MPI | MPI + OpenMP hybrid>>**
>
> If the provider does not document the scheme, write **This build is: NOT
> VERIFIED**, record what you checked, and ask the provider before using the
> module. Compiler and library rows may remain unavailable; this line may not.

### Prerequisite

```bash
<<module load ...>>
```

<<If the prerequisite is a shell function or a sourced script rather than
modules, write out what it actually does — anything defined in a personal
dotfile is not reproducible for another user.>>

**Does the prerequisite set the OpenMP environment for you?**
<<no | yes — it sets OMP_NUM_THREADS=<<n>>, OMP_PLACES, OMP_PROC_BIND>>

If it does, do not set those again unless overriding deliberately.

### OpenMP threads  <<delete this section for a pure-MPI build>>

`OMP_NUM_THREADS` is the number of cores collaborating on one band.

```bash
export OMP_NUM_THREADS=<T>
export OMP_STACKSIZE=<<512m>>
export OMP_PROC_BIND=close
export OMP_PLACES=cores
```

**A compute node here is <<N>> cores** — <<sockets × cores/socket, threads per core>>.

How to combine that with rank counts — the rank/thread/`KPAR` protocol — is in
the `vasp` skill, so the arithmetic lives in exactly one place.

### Parallelisation run

Launch with **<<`ibrun` | `mpirun` | `srun`>>**.

```bash
<<ibrun vasp_std > vasp.out>>
```

<<Say what NOT to use if there is a wrong-but-plausible alternative at your
site — e.g. "do not use mpirun for this build".>>

---

## GPU VASP  <<delete this whole section if you have no GPU build>>

**Version:** <<...>>

### Build and execution information

| | |
|---|---|
| Provided as | <<provider-managed TACC module, user-compiled, vendor install, or container>> |
| Build path | <<build root, module-resolved installation path, or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Scheme | <<OpenACC offload or CUDA>> |
| Scheme evidence | <<build flags, provider documentation URL/title, support response and date, or `NOT VERIFIED`>> |
| Compiler | <<... or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Toolkit | <<CUDA version or `NOT EXPOSED BY PROVIDER`, source and date>> |
| MPI | <<which MPI and whether CUDA-aware, or `NOT EXPOSED BY PROVIDER`, source and date>> |
| GPU libraries | <<cuBLAS, cuSOLVER, cuFFT, NCCL, or `NOT EXPOSED BY PROVIDER`, source and date>> |
| Targets | <<compute capabilities or provider-supported GPU partitions>> |
| Binaries | <<...>> |

Build internals may be unavailable for a managed GPU module. The GPU execution
model, supported hardware, prerequisite, and launch command are still required.
If the provider does not document them, mark the build `NOT VERIFIED` and do not
prepare a GPU node with it.

### Prerequisite

```bash
<<...>>
```

### Parallelisation run

Launch with **<<mpirun | srun>>**. Record the exact provider command and how
many ranks should drive each GPU. Name the MPI implementation when that
information is available.

**Single MPI process:**
```bash
<<...>>
```

**Multiple MPI processes:**
```bash
<<...>>
```

`N` is the number of MPI ranks and should **match the number of GPU cards on the
node** — one rank drives one GPU.


---

## Recommended values

Cluster-tuned starting points. The rules that consume them are in the `vasp`
skill; these are the numbers another site replaces.

| Cluster | `NCORE` (pure MPI) | `OMP_NUM_THREADS` (hybrid) | `NSIM` (GPU, per card) |
|---------|--------------------|----------------------------|------------------------|
| <<...>> | <<e.g. 8, 16, 32>> | <<e.g. 8, 16, 32>> | <<e.g. 32, 16, 8>> |

Larger systems take the larger value in each column — more cores or threads per
band, fewer independent ranks.

## Pseudopotential libraries

Assemble POTCAR by concatenating per-element files from these libraries in
POSCAR species order.

| Cluster | Functional | Location |
|---------|-----------|----------|
| <<...>> | <<PBE>> | <<absolute path>> |
| <<...>> | <<LDA>> | <<absolute path>> |

Assemble these **on the cluster** rather than uploading a POTCAR — the library is
already there, and the files are large and licence-restricted.

**This table is the single place these paths appear.** `generate_POTCAR.sh` and
`query_enmax.sh` take the library as an argument and hold no default of their
own, so adopting this setup elsewhere means editing the rows above and nothing
else.

## Verifying

For a provider-managed module, run these commands in a fresh shell and record
the output date:

```bash
module spider <<module name>>
module show <<module/version>>
module load <<module/version>>
module list
which vasp_std vasp_gam vasp_ncl
```

These commands confirm the module and binary paths. Use the provider's
documentation or a support response for the parallel scheme and launch command;
`module show` may not expose either one.

For a user-compiled build, or whenever the build tree is readable, use the
original build files as evidence:

```bash
which vasp_std vasp_gam vasp_ncl              # which build is on PATH
<<gpu prerequisite>> && which vasp_std        # does a GPU build shadow it?
grep -E "^FC |CPP_OPTIONS" <<build>>/makefile.include   # hybrid? offload?
```

Check the hardware and pseudopotential library for either installation type:

```bash
lscpu | grep -E "^CPU\(s\)|Core\(s\) per socket"
ls <<pseudopotential library root>>
```

## Related

* Generating INCAR/KPOINTS/POSCAR/POTCAR and choosing `KPAR`/`NSIM` — skill `vasp`
* Queue choice and the `#SBATCH` header — `reference/taccLS6_nodes.md`, skill
  `prepare-node` → `references/sbatch_header.md`
* Launcher packing — skill `launcher`, `reference/taccLS6-launchers.md`
* A filled worked example — [`examples/VASP.lonestar6.md`](examples/VASP.lonestar6.md)
