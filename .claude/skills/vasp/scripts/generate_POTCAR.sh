#!/bin/bash
#
# generate_POTCAR.sh — assemble a VASP POTCAR from an EXPLICIT species list.
#
# The species list is the approved choice, including semicore variants
# (Ti_pv, O_h, Sb_GW, ...). POSCAR is used to VERIFY that list, never to derive
# it: POSCAR line 6 carries bare element symbols, so deriving the list from it
# silently discards whichever variant was approved -- you ask for Ti_pv and get
# Ti, with no error and a POTCAR that is wrong in a way nothing downstream
# detects.
#
# Run this on the cluster, where the pseudopotential library already lives.
# POTCARs are large and licence-restricted; do not upload assembled ones.
#
# Usage:
#   ./generate_POTCAR.sh --library /path/to/potpaw_LDA.52 --species "Ti_pv Nb_pv O"
#   ./generate_POTCAR.sh --library /abs/path/to/lib --species "Si C" --poscar POSCAR.init
#
# Options:
#   --library NAME|PATH   library directory; a bare name resolves under --pot-root
#   --species "A B C"     species IN POSCAR ORDER, with variants
#   --poscar FILE         structure to verify against            (default POSCAR)
#   --out FILE            output                                 (default POTCAR)
#   --pot-root DIR        root for resolving a bare --library name; defaults to
#                         $VASP_POT_ROOT. Unset by design -- library paths are a
#                         site fact and live in the VASP tool reference, not here.
#
set -euo pipefail

# No default: a pseudopotential library path is a site fact, and this script
# is meant to be shareable. Pass an absolute --library, or set a root.
POT_ROOT="${VASP_POT_ROOT:-}"
LIBRARY=""; SPECIES=""; POSCAR="POSCAR"; OUT="POTCAR"

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --library)  LIBRARY="${2:-}"; shift 2 ;;
    --species)  SPECIES="${2:-}"; shift 2 ;;
    --poscar)   POSCAR="${2:-}";  shift 2 ;;
    --out)      OUT="${2:-}";     shift 2 ;;
    --pot-root) POT_ROOT="${2:-}";shift 2 ;;
    -h|--help)  usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done

[ -n "$LIBRARY" ] || die "--library is required (absolute path, or a bare name with --pot-root)"
[ -n "$SPECIES" ] || die "--species is required (e.g. \"Ti_pv Nb_pv O\")"

case "$LIBRARY" in
  /*) LIB="$LIBRARY" ;;
  *)  [ -n "$POT_ROOT" ] || die "--library '$LIBRARY' is a bare name, but no library root is set.
       Pass an absolute --library path -- this site's pseudopotential libraries
       are listed in the VASP tool reference -- or set --pot-root / \$VASP_POT_ROOT."
      LIB="$POT_ROOT/$LIBRARY" ;;
esac
[ -d "$LIB" ] || die "library not found: $LIB"
[ -f "$POSCAR" ] || die "$POSCAR not found"

# ---- verify the requested species against the structure --------------------
# POSCAR line 6 is the species line in VASP 5+ format.
POSCAR_ELEMS=$(sed -n '6p' "$POSCAR" | tr -s ' ' | sed 's/^ *//;s/ *$//')
[ -n "$POSCAR_ELEMS" ] || die "line 6 of $POSCAR is empty; expected element symbols"
case "$POSCAR_ELEMS" in
  *[0-9]*) die "line 6 of $POSCAR looks like counts, not symbols: '$POSCAR_ELEMS'
       (VASP 4 format? the species line must be line 6)" ;;
esac

read -r -a WANT <<< "$SPECIES"
read -r -a HAVE <<< "$POSCAR_ELEMS"
[ "${#WANT[@]}" -eq "${#HAVE[@]}" ] || die \
  "species count mismatch: --species has ${#WANT[@]} (${WANT[*]}), \
$POSCAR line 6 has ${#HAVE[@]} ($POSCAR_ELEMS)"

for i in "${!WANT[@]}"; do
  base="${WANT[$i]%%_*}"                       # Ti_pv -> Ti, Nb_d_GW -> Nb
  [ "$base" = "${HAVE[$i]}" ] || die \
    "species ${i} mismatch: --species '${WANT[$i]}' has base element '$base', \
but $POSCAR position ${i} is '${HAVE[$i]}'. Order must match POSCAR exactly."
done

# ---- every file must exist BEFORE writing anything -------------------------
for sp in "${WANT[@]}"; do
  [ -f "$LIB/$sp/POTCAR" ] || die "no POTCAR for '$sp' in $LIB
       (available: $(ls -d "$LIB/${sp%%_*}"* 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' '))"
done

# ---- build -----------------------------------------------------------------
: > "$OUT"
for sp in "${WANT[@]}"; do
  cat "$LIB/$sp/POTCAR" >> "$OUT"
done

# ---- verify what was built -------------------------------------------------
n_titel=$(grep -c '^ *TITEL' "$OUT" || true)
[ "$n_titel" -eq "${#WANT[@]}" ] || die \
  "built $OUT has $n_titel TITEL entries, expected ${#WANT[@]} -- assembly is wrong"

# Record what went in, so the run directory documents its own basis.
echo "POTCAR: $LIB"
printf '%-10s %s\n' "SPECIES" "TITEL"
for sp in "${WANT[@]}"; do
  printf '%-10s %s\n' "$sp" \
    "$(grep -m1 '^ *TITEL' "$LIB/$sp/POTCAR" | sed 's/.*TITEL *= *//')"
done
echo "wrote $OUT (${#WANT[@]} species, POSCAR order verified)"
