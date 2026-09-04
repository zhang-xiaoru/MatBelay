#!/usr/bin/env python3
"""Report the max/RMS atomic force from the LAST ionic step of a VASP OUTCAR.

Reads only the tail of the file (seek from the end), so it stays cheap and
token-light on multi-GB OUTCARs -- never loads the whole file. Prints a one-line
verdict against the relaxation force tolerance and exits 0 if converged, 1 if not.

Usage:
    python check_forces.py path/to/OUTCAR [--tol 0.05]

The TOTAL-FORCE block is:
    POSITION                    TOTAL-FORCE (eV/Angst)
    -----------------------------------------------------------
      x y z   fx fy fz
      ...
    -----------------------------------------------------------
Forces are the last three columns; max|F| is the largest force vector magnitude.
"""
import argparse
import math
import os
import sys

TAIL_BYTES = 1 << 20  # 1 MiB from the end is plenty for the final force block


def read_tail(path, nbytes):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > nbytes:
            f.seek(size - nbytes)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def last_force_block(text):
    """Return list of (fx, fy, fz) from the last TOTAL-FORCE block, or None."""
    idx = text.rfind("TOTAL-FORCE")
    if idx == -1:
        return None
    lines = text[idx:].splitlines()
    forces = []
    started = False
    for ln in lines[1:]:
        if set(ln.strip()) <= {"-"} and ln.strip():   # dashed separator
            if started:
                break                                   # end of block
            started = True
            continue
        if not started:
            continue
        parts = ln.split()
        if len(parts) != 6:
            break
        try:
            fx, fy, fz = (float(parts[3]), float(parts[4]), float(parts[5]))
        except ValueError:
            break
        forces.append((fx, fy, fz))
    return forces or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outcar")
    ap.add_argument("--tol", type=float, default=0.05,
                    help="EDIFFG force tolerance, eV/Ang (default 0.05)")
    ap.add_argument("--tail", type=int, default=TAIL_BYTES,
                    help="bytes to read from the end of OUTCAR")
    args = ap.parse_args()

    if not os.path.isfile(args.outcar):
        sys.exit(f"error: {args.outcar} not found")

    text = read_tail(args.outcar, args.tail)
    forces = last_force_block(text)
    if not forces:
        # tail may have started mid-block; retry with a bigger window once
        text = read_tail(args.outcar, args.tail * 8)
        forces = last_force_block(text)
    if not forces:
        sys.exit("error: no complete TOTAL-FORCE block found in OUTCAR tail")

    mags = [math.sqrt(fx * fx + fy * fy + fz * fz) for fx, fy, fz in forces]
    fmax = max(mags)
    frms = math.sqrt(sum(m * m for m in mags) / len(mags))
    converged = fmax < args.tol
    reached = "reached required accuracy" in text

    natoms = len(forces)
    print(f"atoms parsed : {natoms}")
    print(f"max |F|      : {fmax:.4f} eV/Ang")
    print(f"rms |F|      : {frms:.4f} eV/Ang")
    print(f"tolerance    : {args.tol:.4f} eV/Ang")
    print(f"OUTCAR flag  : {'reached required accuracy' if reached else 'not printed'}")
    if converged:
        print("verdict      : CONVERGED")
        # guidance for the next round, per RELAX_NOTES protocol
    elif fmax <= 0.30:
        print("verdict      : NOT converged -> next round quasi-Newton (INCAR.qn)")
    else:
        print("verdict      : NOT converged -> next round CG (INCAR.cg)")
    sys.exit(0 if converged else 1)


if __name__ == "__main__":
    main()
