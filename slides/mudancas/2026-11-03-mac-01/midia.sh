#!/usr/bin/env bash
# Media of the MAC-01 slides (vault spec APR-01): replayed from the exploratory runs' logs, the
# episode chosen by a named rule that goes into the caption.
#   bash slides/mudancas/2026-11-03-mac-01/midia.sh        (SIM_RUNS: where the runs are)
# Then fatos.py, which reads the episode and steps back from the .json sidecar.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../../../tools"
RUNS="${SIM_RUNS:-$HOME/Mestrado/Simulation/runs}"
SUM="$RUNS/2026-11-03_1242_C0_ucb-0.1_lp_macro-sum"
mkdir -p "$HERE/media"

# O caso da seed 1: o 1º sucesso da soma, quatro macros em cadeia
python3 "$TOOLS/video.py" episode "$SUM/s1" --rule first-success --stride 2 \
    --title "MAC-01 soma · seed 1" --out "$HERE/media/soma_s1.mp4" \
    --stills reach,grasp,transport,last --stills-prefix "$HERE/media/soma"
