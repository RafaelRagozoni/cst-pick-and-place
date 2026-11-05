#!/usr/bin/env bash
# Media of the CRE-01 slides (vault spec APR-01): every image and video in media/ comes from here,
# replayed from the run logs, the episode chosen by a named rule that goes into the caption.
#   bash slides/mudancas/2026-10-27-cre-01/midia.sh        (SIM_RUNS: where the runs are)
# Then fatos.py, which reads the episodes and steps back from the media's .json sidecars.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../../../tools"
RUNS="${SIM_RUNS:-$HOME/Mestrado/Simulation/runs}"
BASE="$RUNS/2026-10-21_0842_C4_ucb-0.1_lp_P1"
AMENDED="$RUNS/2026-10-28_1803_C4_ucb-0.1_lp_P1"
mkdir -p "$HERE/media"

# Problema: a base pega o cubo e o larga no caminho (tira de 4 quadros)
python3 "$TOOLS/video.py" episode "$BASE/s1" --rule first-drop-away:400 --stride 4 \
    --title "Base do WP2 · seed 1" --out "$HERE/media/base_s1.mp4" \
    --stills grasp-40,grasp+4,drop-12,drop+40 --stills-prefix "$HERE/media/base"

# Previsto × aconteceu: o CRE-01 emendado leva o cubo ao pad e não solta
python3 "$TOOLS/video.py" episode "$AMENDED/s1" --rule last-with-stage:transport --stride 2 \
    --title "CRE-01 emendado · seed 1" --out "$HERE/media/cre01_s1.mp4" \
    --stills transport,last --stills-prefix "$HERE/media/cre"
