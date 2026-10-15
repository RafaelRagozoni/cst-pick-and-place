# tools — run, summarize, watch

```
python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000
python3 tools/summarize_run.py runs/<batch>                 # also mid-run
python3 tools/replay.py runs/<batch>/s1 --every 100 --speed 4
```

| script | does |
|---|---|
| `run_live.py` | One independent run per seed, in parallel, headless: each seed its own CoppeliaSim (`bridge.py --launch`), bridge and agent. The agent runs from a compiled snapshot in the batch folder, so code edits mid-run cannot leak in. Ctrl-C or `kill` stops everything, simulators included. |
| `summarize_run.py` | A Markdown summary of fixed size (≤ 20 rows, ~1–2 k tokens) whatever the run length: per block of episodes, success, task stages reached, closest approach, new coverage bins, which drive set the goal, most chosen habits, σ; then the key moments (first time each stage fired, distance records, first success). Reads a run still going, up to its last finished episode. |
| `replay.py` | Shows chosen episodes (`--ep 5`, `--ep 100-119`, `--every 1000`) in the CoppeliaSim window at 1× = real time or faster, with a panel: episode, step, habit, goal, drives. Kinematic: it puts things where the log says, so it shows what happened even though Bullet would not repeat it. |
| `runlog.py` | Shared log reading (tolerates an unfinished log). |

Batches go to `runs/` (git-ignored): `runs/<date>_<cond>_<sel>[_tag]/{agent/, s<seed>/{log.jsonl.gz, agent.out, bridge.out, run.json, summary.md}}`.

## Cost (measured 2026-10-15)

| | per step | 1000 episodes × 500 steps |
|---|---|---|
| headless (what `run_live.py` uses) | ~17–19 ms | ~2.5 h per seed; seeds in parallel cost no extra wall time |
| physics alone (`sim.step`) | 8.8 ms | the floor: batching the bridge's 41 remote calls per step into one could reach ~2× |
| GUI, every step drawn | ~140 ms | ~20 h — why watching is a replay, not a live view |

Log: ~0.2 MB per 500-step episode (gzip), so ~200 MB per 1000 episodes. `summarize_run.py` reads ~1000 episodes in well under a minute.

## Prior art / alternatives considered

| alternative | why not |
|---|---|
| TensorBoard / Weights & Biases / MLflow for the learning curves | Good dashboards, but binary event files or a service; the goal here is a summary short enough for Claude to read in plain text, from the log that already exists. Adding a TensorBoard writer later is cheap if curves need a UI. |
| GNU parallel / Ray / Hydra multirun for the seeds | Each run already needs its own simulator, bridge and agent wired by ports; a ~150-line launcher does that plus cleanup. Ray or SLURM become worth it on a cluster. |
| Live GUI every N episodes | Slows the whole run (~7 steps/s drawn) and needs you watching at that moment. |
| Re-running an episode's actions in the simulator | Bullet does not repeat contacts across processes: the re-run would drift from what happened. |
| CoppeliaSim's video recorder | Needs the GUI during the run (same cost as a live view). |

What the own scripts lose against the strongest alternative (a TensorBoard dashboard): no interactive plots. What they gain: nothing new to run or install, and a summary Claude can read cheaply.

## Approximations and risks

- **Replay, cosmetic only:** the log keeps the cube's position but not its rotation (it keeps its starting yaw), and the gripper's opening but not its finger joints (fingers are posed from a table the replay measures at start-up).
- **First GUI launch** shows CoppeliaSim's "Welcome / choose Lua or Python" dialog until a choice is made once.
- Parallel seeds: each takes ~1.5 cores; with 20 cores, more than ~10 at once will slow every run.
