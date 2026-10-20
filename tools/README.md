# tools — run, summarize, watch

```
python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000
python3 tools/summarize_run.py runs/<batch>                 # also mid-run
python3 tools/replay.py runs/<batch>/s1 --every 100 --speed 4
python3 tools/run_live.py --resume runs/<batch> --emax 2000 # 1000 more, from the checkpoints
python3 tools/run_live.py --protocol bench/P1.json --condition C4   # a baseline batch (BAS-01)
```

| script | does |
|---|---|
| `run_live.py` | One independent run per seed, in parallel, headless: each seed its own CoppeliaSim (`bridge.py --launch`), bridge and agent. The agent runs from a compiled snapshot in the batch folder, so code edits mid-run cannot leak in. Ctrl-C or `kill` stops everything, simulators included. The agent checkpoints after every episode; `--resume` continues a stopped or finished batch (below). |
| `summarize_run.py` | A Markdown summary of fixed size (≤ 20 rows, ~1–2 k tokens) whatever the run length: per block of episodes, success, task stages reached, closest approach, new coverage bins, which drive set the goal, most chosen habits, σ; then the key moments (first time each stage fired, distance records, first success). Reads a run still going, up to its last finished episode. |
| `replay.py` | Shows chosen episodes (`--ep 5`, `--ep 100-119`, `--every 1000`) in the CoppeliaSim window at 1× = real time or faster, with a panel: episode, step, habit, goal, drives. Kinematic: it puts things where the log says, so it shows what happened even though Bullet would not repeat it. |
| `runlog.py` | Shared log reading (tolerates an unfinished log); cuts a log back to a checkpoint. `test_runlog.py` checks both, offline. |
| `protocol.py` | Protocol batches (vault spec BAS-01): the fingerprint every `run.json` records, the protocol file, and the refusals (below). `test_protocol.py` checks the refusals offline, on throwaway repositories. |

Batches go to `runs/` (git-ignored): `runs/<date>_<cond>_<sel>[_tag]/{agent/, [protocol.json], s<seed>/{log.jsonl.gz, checkpoint.json.gz, checkpoints/, agent.out, bridge.out, run.json, agent.json, summary.md}}`.

## Protocol batches and the fingerprint (since 2026-10-20)

Every `run.json` has a `fingerprint`: the repository's full commit and every uncommitted path (the
scene and `cst` included; the `-dirty` suffix used to look only at `agent/` and
`coppelia_environment/*.py`), the `cst` commit, a hash of the scene, the success test
(`goals.SUCCESS_TEST`), the protocol file's name and hash, the CoppeliaSim install and a hash of its
libraries, and the Java and Python versions. `agent.json`, written by the agent before its first
episode, adds the effective Config, every field, and the bridge's handshake.

`--protocol FILE` makes a batch the baseline track can use. The file (`bench/P0.json` is the pilot's)
fixes selection, Curiosity, seeds, E_max, E_ref and step limit, and lists the conditions it allows,
and the success test it was written for. Refused, each with what to change:
- any of `--selection --curiosity --seeds --emax --eref --step-limit` on the command line;
- a `--condition` the file does not list, or none;
- a tree whose success test is not the file's;
- a tree with anything uncommitted, the scene and `cst` included;
- resuming with `--emax` or `--eref`, from a dirty tree, or with any fingerprint field changed —
  which also keeps a resume from running a newer bridge, since the bridge is not snapshotted.

Without `--protocol`, nothing is refused and the fingerprint is recorded all the same.

## Resume

`--resume runs/<batch>` continues every seed (or `--seeds`) from its `checkpoint.json.gz`, the agent
after its last finished episode (`agent/README.md`, Checkpoints). `--emax` and `--eref` are totals:
`--emax 2000` after a 1000-episode run adds 1000; left out, each keeps the seed's own. (Until
2026-10-20 they fell back to 1000 and 0, so resuming a batch with Phase 2 without `--eref` silently
ended it at the first success.) The batch's own agent snapshot and settings are
used; its condition, selection and step limit cannot be changed. The log continues in the same file
(a second gzip member); if the run was stopped mid-episode, or the bridge logged an episode the
agent had not checkpointed yet, the log is first cut back to the checkpoint (`run.json` → `resumes`
says what went). A seed still running is refused. `checkpoints/after-ep000099.json.gz` and so on,
every `--keep-every` (100) episodes, are kept for later use; nothing reads them yet.

## Cost (measured 2026-10-15)

| | per step | 1000 episodes × 500 steps |
|---|---|---|
| headless (what `run_live.py` uses) | ~17–19 ms | ~2.5 h per seed; seeds in parallel cost no extra wall time |
| physics alone (`sim.step`) | 8.8 ms | the floor: batching the bridge's 41 remote calls per step into one could reach ~2× |
| GUI, every step drawn | ~140 ms | ~20 h — why watching is a replay, not a live view |
| checkpoint, every episode | ≤ 0.23 s per episode, at a pessimistic state size | ≤ 2.5 % |

Log: ~0.2 MB per 500-step episode (gzip), so ~200 MB per 1000 episodes. `summarize_run.py` reads ~1000 episodes in well under a minute.

## Prior art / alternatives considered

| alternative | why not |
|---|---|
| TensorBoard / Weights & Biases / MLflow for the learning curves | Good dashboards, but binary event files or a service; the goal here is a summary short enough for Claude to read in plain text, from the log that already exists. Adding a TensorBoard writer later is cheap if curves need a UI. |
| GNU parallel / Ray / Hydra multirun for the seeds | Each run already needs its own simulator, bridge and agent wired by ports; a ~150-line launcher does that plus cleanup. Ray or SLURM become worth it on a cluster. |
| Live GUI every N episodes | Slows the whole run (~7 steps/s drawn) and needs you watching at that moment. |
| Re-running an episode's actions in the simulator | Bullet does not repeat contacts across processes: the re-run would drift from what happened. |
| CoppeliaSim's video recorder | Needs the GUI during the run (same cost as a live view). |
| Sacred (`--enforce_clean`), MLflow, W&B for the fingerprint and refusals | They record a run's commit, and Sacred refuses a dirty tree; none knows the `cst` submodule, the scene or the CoppeliaSim install, and none refuses a resume on other code or a budget that differs from a protocol file. ~150 lines here; vault spec BAS-01 weighs them. |
| Resume as a new batch (a second log beside the first) | No log rewrite on resume, ever. But `metrics.py`, `summarize_run.py` and `replay.py` would each have to learn to stitch segments; one file keeps every reader as it is, and the rewrite only happens after a stop mid-episode. |

What the own scripts lose against the strongest alternative (a TensorBoard dashboard): no interactive plots. What they gain: nothing new to run or install, and a summary Claude can read cheaply.

## Approximations and risks

- **Replay, cosmetic only:** the log keeps the cube's position but not its rotation (it keeps its starting yaw), and the gripper's opening but not its finger joints (fingers are posed from a table the replay measures at start-up).
- **First GUI launch** shows CoppeliaSim's "Welcome / choose Lua or Python" dialog until a choice is made once.
- Parallel seeds: each takes ~1.5 cores; with 20 cores, more than ~10 at once will slow every run.
