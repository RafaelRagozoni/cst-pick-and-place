#!/usr/bin/env bash
# Media of the 2026-11-11 meeting (vault spec APR-01): the starting point, replayed from the base's
# log. Every and stride were chosen with `video.py learning ... --estimate` to give 30–45 s for the
# main deck; the 2-minute version goes to the appendix.
#   bash slides/reunioes/2026-11-11/midia.sh        (SIM_RUNS: where the runs are)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../../../tools"
RUNS="${SIM_RUNS:-$HOME/Mestrado/Simulation/runs}"
BASE="$RUNS/2026-10-21_0842_C4_ucb-0.1_lp_P1"
mkdir -p "$HERE/media"

python3 "$TOOLS/video.py" learning "$BASE/s1" --every 300 --stride 8 --epilogue first-success \
    --title "Como a base do WP2 aprende" --out "$HERE/media/aprendizado_curto.mp4"
python3 "$TOOLS/video.py" learning "$BASE/s1" --every 100 --stride 4 --epilogue first-success \
    --epilogue-stride 2 --title "Como a base do WP2 aprende" --out "$HERE/media/aprendizado_longo.mp4"
