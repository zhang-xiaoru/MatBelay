# VASP success check

How to tell a finished VASP run actually succeeded — the default gate for a node
whose plan does not state a bespoke one.

**A clean SLURM exit is not the answer.** VASP exits 0 after hitting its ionic
limit with forces nowhere near the target, so `sacct` saying `COMPLETED` and the
run being usable are different claims. The canonical case on record: a relax
"completed" at `NSW=200` with max force ~49 meV/Å against a 5 meV/Å gate.

VASP's answers to the four questions the `## Success check` contract asks. Read
this when a VASP job has **finished** and you need a verdict — `run-workflow`
Step 6, or a direct "did this converge". It is not needed to write inputs, which
is why it lives here rather than in `SKILL.md`.

Four questions, in order. Stop at the first that fails.

## 1. Did it exit cleanly?

```bash
grep -c "General timing and accounting" OUTCAR      # 1 = clean, 0 = died
```

VASP writes that block last. Absent means the process died mid-run — look at
`vasp.out` and the SLURM `.e` file for the reason (the same signatures
`scripts/probe.sh` greps for).

## 2. Did it meet its own criterion?

Which criterion depends on what the run is:

| Run type | Converged when | Command |
|---|---|---|
| relax (`NSW>0`, `IBRION` 1/2) | VASP says so | `grep -c "reached required accuracy" OUTCAR` |
| static (`NSW=0`) | the electronic loop converged | see below |
| MD (`IBRION=0`) | it completed the requested steps | ionic count == `NSW` |
| linear response (`LEPSILON`, `IBRION=7/8`) | clean exit is the criterion | question 1 only |

Electronic convergence, for any run type — every ionic step must have ended on
`EDIFF`, not on `NELM`:

```bash
grep -c "aborting loop because EDIFF is reached" OUTCAR   # = ionic steps done
grep -c "F=" OSZICAR                                      # = ionic steps done
```

Equal counts mean every ionic step converged electronically. Fewer of the first
means at least one step exhausted `NELM` — the forces from that step are
unconverged, and a relax built on them is not trustworthy even if it later
"reached required accuracy".

## 3. If it did not converge — budget, or failure?

This is the question that decides whether the run is **continuable**, and it is
the one a run driver needs to get right. Budget means *this run ran out of room*;
failure means *running it longer will not help*.

```bash
grep -c "F=" OSZICAR        # ionic steps actually taken
grep NSW INCAR              # ionic steps allowed
```

| Evidence | Verdict |
|---|---|
| ionic steps == `NSW`, clean exit, valid `CONTCAR`, forces falling | **budget** — the run ran out of steps. Continuable |
| SLURM `TIMEOUT`, clean `CONTCAR` written, forces falling | **budget** — ran out of walltime. Continuable |
| ionic steps < `NSW` and it stopped anyway | **failure** — VASP gave up. Not continuable; find out why |
| any signature from `scripts/probe.sh`'s `FATAL` list | **failure**. Not continuable |
| forces flat or rising across rounds | **failure disguised as budget** — more steps will not help |

That last row is the one worth being strict about. "Hit the limit" and "is
converging" are separate facts, and only both together justify another round.

## 4. If it is continuable — what carries over, and what changes?

The recipe a run driver applies to build the next round. It is written here so
that continuing a run is **execution, not decision**: the branches below were
chosen once, in advance, and a driver picks among them rather than inventing one.

**Carries over into the fresh round directory:**

| From the finished round | Becomes | Why |
|---|---|---|
| `CONTCAR` | `POSCAR` | the relaxed geometry is the next round's start |
| `WAVECAR` | `WAVECAR`, with `ISTART=1` | warm restart; skips re-converging the electronic ground state from scratch |
| `INCAR`, `KPOINTS`, `POTCAR`, `<name>.batch` | unchanged | the basis must be identical across rounds, or the rounds are not comparable |

Never overwrite a previous round — each is its own directory, so the whole
trajectory stays auditable.

**Progress metric:** `max |F|` from `scripts/check_forces.py`. Falling across
rounds justifies another; flat or rising does not, whatever the run's exit state.

**What a next round may switch — the ionic algorithm, and only that:**

```
max|F| < gate                 → converged; the chain is done
gate ≤ max|F| ≲ 0.30, falling → quasi-Newton   (IBRION=1)  — near the minimum
max|F| ≳ 0.30, or oscillating → conjugate grad (IBRION=2)  — still far out
```

The 0.30 eV/Å boundary is where quasi-Newton's quadratic assumption starts to
hold. Below it, `IBRION=1` converges in far fewer steps; above it, or on an
oscillating trajectory, it overshoots and `IBRION=2` is the safe choice.

For **MD** (`IBRION=0`), nothing switches: the next round continues the trajectory
with identical settings, and the progress metric is the ionic step count.

Anything not on this list — `ENCUT`, `ALGO`, `AMIX`, `EDIFF`, `KPAR`, the k-mesh,
the node count — is **not** a continuation change. Needing one means the run has
a problem a longer run will not solve, and that is a question for the user.

## The force metric

`scripts/check_forces.py` is the measurement all of the above turns on. It reads
only the tail of `OUTCAR` (1 MiB, seeked from the end), so it is safe on a
multi-GB file:

```bash
python .claude/skills/vasp/scripts/check_forces.py OUTCAR --tol 0.05
```

```
atoms parsed : 216
max |F|      : 0.0413 eV/Ang
rms |F|      : 0.0092 eV/Ang
tolerance    : 0.0500 eV/Ang
OUTCAR flag  : reached required accuracy
verdict      : CONVERGED
```

Exit 0 = converged, 1 = not. `--tol` must be set to **the node's own gate**, not
left at the default — the default is a generic 0.05 eV/Å, and a node whose gate
is 5 meV/Å would read as converged at ten times its tolerance.

`max |F|` is also the quantity to compare **across rounds** of a multi-round
relaxation: falling means another round is justified, flat or rising means it is
not.
