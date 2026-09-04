<!-- EXAMPLE -- NOT YOUR SITE. Do not plan against this file. -->

> ### Example only
>
> This is **one site's** filled-in VASP reference: TACC Lonestar6, with two
> user-compiled builds. It is kept as a worked example of what
> `reference/VASP.md` should contain once filled — nothing reads it, and no
> agent should plan against it.
>
> Your own answers go in **`reference/VASP.md`**. Read this one alongside it to
> see the level of detail that is useful, especially the two hazard notes: two
> builds sharing binary names, and a prerequisite that silently shadows `PATH`.

---

# VASP reference — EXAMPLE (TACC Lonestar6, user-compiled)

Conventions and environment rules for using VASP in this setup.

*Environment facts below were probed on Lonestar6 on **2026-08-28**. Re-check with
the commands in [Verifying](#verifying) if a build is moved or rebuilt.*

## Availability

**Version(s):** 6.5.0

**How obtained:** User-compiled in two separate build trees on **Lonestar6
(ls6)**. Both builds provide the same three binaries.

| Build | Path or module | Binaries |
|-------|----------------|----------|
| CPU | `$WORK/.../bin` | `vasp_std`, `vasp_gam`, `vasp_ncl` |
| GPU | `$WORK/.../bin` | `vasp_std`, `vasp_gam`, `vasp_ncl` |

There is **no VASP module** — the binaries come from `$PATH`, set in `.bashrc`.
Never `module load vasp`.

### Hazard: the two builds share binary names

`.bashrc` puts the **CPU** bin on `PATH`. The `nvhpc` command **prepends** the GPU
bin, so after running it `vasp_std` resolves to the *GPU* build instead.

```bash
which vasp_std     # → .../vasp.6.5.0/bin/vasp_std       (CPU)
nvhpc
which vasp_std     # → .../vasp.6.5.0_gpu/bin/vasp_std   (GPU)
```

A job script that sources `nvhpc` and then calls `ibrun vasp_std` launches the GPU
binary under the CPU launcher. Decide CPU or GPU first, then use only that
build's prerequisite and launcher — the two are not interchangeable.

---

## CPU VASP

### Lonestar6

**Version:** 6.5.0

#### Build and execution information

| | |
|---|---|
| Provided as | User-compiled |
| Build path | `$WORK/...` |
| Scheme | **MPI + OpenMP hybrid** |
| Scheme evidence | `-D_OPENMP` in `$WORK/.../makefile.include` |
| Compiler | `mpiifort -fc=ifx -qopenmp` (Intel ifx, Intel MPI) |
| Math libraries | Intel MKL — FFTW, BLAS, LAPACK, scaLAPACK (`-qmkl`, `mkl_scalapack_lp64`, `mkl_blacs_intelmpi_lp64`) |
| MKLROOT | `/scratch/projects/compilers/intel24.1/oneapi/mkl/2024.1/` |
| Optimisation | `-O2`, `-xHOST` |
| Binaries | `$WORK/.../bin/{vasp_std,vasp_gam,vasp_ncl}` |

**This build is: MPI + OpenMP hybrid**

Because the build is hybrid, **omit `NCORE` and `NPAR` from the INCAR.**
`OMP_NUM_THREADS` plays the role `NCORE` plays in a pure-MPI build.

#### Prerequisite

```bash
module load intel/24
module load hdf5/2
```

**Does the prerequisite set the OpenMP environment for you?** No. The batch
script sets it explicitly below.

#### OpenMP threads

`OMP_NUM_THREADS` is the number of cores collaborating on one band.

```bash
export OMP_NUM_THREADS=<T>
export OMP_STACKSIZE=512m
export OMP_PROC_BIND=close
export OMP_PLACES=cores
```

Recommended values for this cluster are in [Recommended values](#recommended-values).
How to combine them with the core count — the rank/thread/`KPAR` protocols — is in
the `vasp` skill, so the arithmetic is stated in exactly one place.

#### Parallelisation run

Launch with **`ibrun`** — Intel MPI on TACC. Do not use `mpirun` for the CPU build.

```bash
ibrun vasp_std > vasp.out
```

---

## GPU VASP

### Lonestar6

**Version:** 6.5.0 (separate build tree from the CPU one)

#### Build and execution information

| | |
|---|---|
| Provided as | User-compiled |
| Build path | `$WORK/...` |
| Scheme | **OpenACC offload** |
| Scheme evidence | `-DACC_OFFLOAD -DNVCUDA -DUSENCCL` in `$WORK/.../makefile.include` |
| Compiler | `nvfortran` / `mpif90 -acc -gpu=cc80,cc90,cuda12.8 -mp` |
| Toolkit | NVHPC 25.3, CUDA 12.8 |
| MPI | CUDA-aware OpenMPI bundled with NVHPC |
| GPU libraries | cuBLAS, cuSOLVER, cuFFT, NCCL (multi-GPU) |
| Optimisation | `-fast`, `-Mwarperf` |
| Targets | `cc80` (A100) and `cc90` (H100) — runs on both GPU node types |
| Binaries | `$WORK/.../bin/{vasp_std,vasp_gam,vasp_ncl}` |

**This build is: OpenACC offload**

`-mp` means OpenMP is enabled in this build too, but threads are a secondary
concern here because most of the work runs on the GPU. Some work still runs on
the CPU and uses OpenMP.

#### Prerequisite

```bash
nvhpc
```

`nvhpc` is a **bash function** exported from `.bashrc`; it sources
`$WORK/.../nvhpc-env.sh`, which:

1. `module load gcc/13` and `fftw3`;
2. puts the NVHPC 25.3 compilers, the CUDA-aware OpenMPI, NCCL and CUDA 12.8 on
   `PATH` / `LD_LIBRARY_PATH`;
3. points `HDF5_ROOT` at the NVHPC-built HDF5 and adds MKL libs;
4. **prepends `$WORK/.../bin` to `PATH`** — see the warning above;
5. sets the OpenMP environment for you:

```bash
OMP_NUM_THREADS=32   OMP_PLACES=cores   OMP_PROC_BIND=close   OMP_STACKSIZE=4G
```

**Does the prerequisite set the OpenMP environment for you?** Yes. It sets the
four values shown above.

Because step 5 already sets `OMP_NUM_THREADS`, do not set it again unless you are
deliberately overriding it.

#### Parallelisation run

Launch with **`mpirun`** — the NVHPC OpenMPI, not `ibrun`.

**Single MPI process:**
```bash
mpirun --bind-to none -np 1 vasp_std > vasp.out
```

**Multiple MPI processes:**
```bash
mpirun -np N --map-by ppr:N:PE=$OMP_NUM_THREADS --bind-to core vasp_std > vasp.out
```

`N` is the number of MPI ranks, and should **match the number of GPU cards on the
node** — one rank drives one GPU.


## Recommended values

Cluster-tuned starting points. The rules that consume them are in the `vasp`
skill; these are the numbers a different site would replace.

| Cluster | `NCORE` (pure MPI) | `OMP_NUM_THREADS` (hybrid) | `NSIM` (GPU, per card) |
|---------|--------------------|----------------------------|------------------------|
| LS6 | 8, 16, 32 | 8, 16, 32 | 32, 16, 8 |

Larger systems take the larger value in each column — more cores or threads per
band, fewer independent ranks.

## Pseudopotential libraries

Assemble POTCAR by concatenating per-element files from these libraries in POSCAR
species order. Probed 2026-08-28.

| Cluster | Functional | Location |
|---------|-----------|----------|
| LS6 | PBE (`potpaw_PBE.64`) | `$WORK/.../potpaw_PBE.64` |
| LS6 | LDA (`potpaw_LDA.52`) | `$HOME/.../potpaw_LDA.52` |

Assemble these **on the cluster** rather than uploading a POTCAR — the library is
already there, and the file is large and licence-restricted.

**This table is the single place these paths appear.** `generate_POTCAR.sh` and
`query_enmax.sh` take the library as an argument and hold no default of their
own, so adopting this setup elsewhere means editing the rows above and nothing
else. A script that carried a fallback path would quietly work against the wrong
library on someone else's machine.

## Verifying

Run these on the login node if a build may have moved or been rebuilt:

```bash
which vasp_std vasp_gam vasp_ncl          # CPU build on PATH
nvhpc && which vasp_std                   # GPU build shadows it
lscpu | grep -E "^CPU\(s\)|Core\(s\) per socket"
module spider intel/24 ; module spider hdf5/2
grep -E "^FC |CPP_OPTIONS" $WORK/.../makefile.include
grep -E "^FC |CPP_OPTIONS" $WORK/.../makefile.include
ls $WORK/sync_files/vasp_pot/                 # pseudopotential libraries
```

## Related

* Generating INCAR/KPOINTS/POSCAR/POTCAR and choosing `KPAR`/`NSIM` — skill `vasp`
* Queue choice and the `#SBATCH` header — `reference/taccLS6-nodes.md`, skill
  `prepare-node` → `references/sbatch_header.md`. Launcher packing — skill `launcher`
