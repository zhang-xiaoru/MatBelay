#!/bin/bash
#
# query_enmax.sh — read ENMAX for a species list straight from the
#                  pseudopotential library, and report the resulting ENCUT.
#
# Run this on the cluster at PREPARE time, before the INCAR is written.
# ENCUT is derived from the POTCARs, but the POTCAR itself is only assembled at
# run time -- and for a node whose structure comes from its parent there is no
# POSCAR yet either. So this queries the library directly: library + species
# list is all it needs, no structure and no assembled POTCAR.
#
# Usage:
#   ./query_enmax.sh --library /path/to/potpaw_LDA.52 --species "Ti_pv Nb_pv O"
#   ./query_enmax.sh --library potpaw_PBE.64 --species "Si C" --factor 1.3   # with $VASP_POT_ROOT set
#
# Options:
#   --library NAME|PATH   library directory; a bare name resolves under --pot-root
#   --species "A B C"     species, with variants (order is irrelevant here)
#   --factor F            ENCUT multiplier                     (default 1.25)
#   --pot-root DIR        root for resolving a bare --library name; defaults to
#                         $VASP_POT_ROOT. Unset by design -- library paths are a
#                         site fact and live in the VASP tool reference, not here.
#
set -euo pipefail

# No default: a pseudopotential library path is a site fact, and this script
# is meant to be shareable. Pass an absolute --library, or set a root.
POT_ROOT="${VASP_POT_ROOT:-}"
LIBRARY=""; SPECIES=""; FACTOR="1.25"

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --library)  LIBRARY="${2:-}"; shift 2 ;;
    --species)  SPECIES="${2:-}"; shift 2 ;;
    --factor)   FACTOR="${2:-}";  shift 2 ;;
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

read -r -a WANT <<< "$SPECIES"

# Fail before printing anything, so a typo'd variant cannot yield a plausible
# but wrong maximum.
for sp in "${WANT[@]}"; do
  [ -f "$LIB/$sp/POTCAR" ] || die "no POTCAR for '$sp' in $LIB
       (available: $(ls -d "$LIB/${sp%%_*}"* 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' '))"
done

echo "library: $LIB"
printf '%-10s %-28s %s\n' "SPECIES" "TITEL" "ENMAX"
max=0
for sp in "${WANT[@]}"; do
  t=$(grep -m1 '^ *TITEL' "$LIB/$sp/POTCAR" | sed 's/.*TITEL *= *//')
  e=$(grep -m1 '^ *ENMAX' "$LIB/$sp/POTCAR" | sed 's/.*ENMAX *= *//; s/;.*//' | tr -d ' ')
  printf '%-10s %-28s %s\n' "$sp" "$t" "$e"
  awk -v a="$e" -v b="$max" 'BEGIN{exit !(a>b)}' && max="$e"
done
echo
printf 'max ENMAX = %s eV  ->  ENCUT at %sx = %s eV\n' \
  "$max" "$FACTOR" "$(awk -v m="$max" -v f="$FACTOR" 'BEGIN{printf "%.0f", m*f}')"
