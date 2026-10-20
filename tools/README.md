# tools — run, summarize, watch

```
python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000
python3 tools/summarize_run.py runs/<batch>                 # also mid-run
python3 tools/replay.py runs/<batch>/s1 --every 100 --speed 4
python3 tools/run_live.py --resume runs/<batch> --emax 2000 # 1000 more, from the checkpoints
python3 tools/run_live.py --protocol bench/P1.json --condition C4   # a baseline batch (BAS-01)
python3 tools/bench.py score runs/<batch>                   # its scorecard; also mid-run
python3 tools/bench.py compare runs/<A> runs/<B>            # C0 against C4, or the track
```

| script | does |
|---|---|
| `run_live.py` | One independent run per seed, in parallel, headless: each seed its own CoppeliaSim (`bridge.py --launch`), bridge and agent. The agent runs from a compiled snapshot in the batch folder, so code edits mid-run cannot leak in. Ctrl-C or `kill` stops everything, simulators included. The agent checkpoints after every episode; `--resume` continues a stopped or finished batch (below). |
| `summarize_run.py` | A Markdown summary of fixed size (≤ 20 rows, ~1–2 k tokens) whatever the run length: per block of episodes, success, task stages reached, closest approach, new coverage bins, which drive set the goal, most chosen habits, σ; then the key moments (first time each stage fired, distance records, first success). Reads a run still going, up to its last finished episode. |
| `replay.py` | Shows chosen episodes (`--ep 5`, `--ep 100-119`, `--every 1000`) in the CoppeliaSim window at 1× = real time or faster, with a panel: episode, step, habit, goal, drives. Kinematic: it puts things where the log says, so it shows what happened even though Bullet would not repeat it. |
| `runlog.py` | Shared log reading (tolerates an unfinished log); cuts a log back to a checkpoint. `test_runlog.py` checks both, offline. |
| `bench.py` | The scorecard of a batch (BAS-01's M1–M5 and its sanity checks) as `scorecard.md` and `.json` in the batch; `table` prints the track, `bench/ledger.csv`, one line per finished protocol batch; `compare` tests two batches and refuses what BAS-01's rules 5 and 6 refuse. Needs SciPy (`requirements-tools.txt`). `test_bench.py` checks it offline on fake batches. |
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

## Scorecard and track (`bench.py`, since 2026-10-20)

`score` reads every seed's log in parallel (~7 s for 6 × 170 episodes) and writes the scorecard. M1
is episodes to the first success, Kaplan–Meier, a seed without one censored at E_max — or, while it
runs, at the episodes it has run, so a scorecard mid-run says "in progress", not "invalid". M1b is
the same per task stage, M2 Phase 2's jumpstart, time to θ and final rate, M2b whether the last 100
still differ from the 100 before, M3 steps and energy per Phase 2 success, M4 coverage bins, M5 the
repertoire. A batch with a failing sanity check is invalid: a seed that did not end where the
protocol ends it, Effort not 0 in Phase 1 or 0 in Phase 2, C4 or C6 off the 14 primitives, two
fingerprints in one batch, a success without the four stages in order. A finished protocol batch
writes its line into `bench/ledger.csv`, replacing an older one of the same batch.

`compare A B` tests M1 (censored seeds tied at E_max, with log-rank beside it as the check), M2's
final rate, M3's steps and M4's bins by Mann–Whitney, with rank-biserial and Holm. It refuses two
protocol versions, C0 against C4 on different fingerprints, and batches without a protocol unless
`--exploratory`, which says so at the top and the bottom.

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
| `lifelines` for Kaplan–Meier; `statsmodels` for Holm | SciPy alone gives Kaplan–Meier with its band, log-rank, Mann–Whitney and the bootstrap; lifelines would be a second dependency for one of those, and Holm is six lines against statsmodels' size. What it loses: lifelines' median CI is built in; here it is read off SciPy's log-log band, tested on a case worked by hand. |
| Resume as a new batch (a second log beside the first) | No log rewrite on resume, ever. But `metrics.py`, `summarize_run.py` and `replay.py` would each have to learn to stitch segments; one file keeps every reader as it is, and the rewrite only happens after a stop mid-episode. |

What the own scripts lose against the strongest alternative (a TensorBoard dashboard): no interactive plots. What they gain: nothing new to run or install, and a summary Claude can read cheaply.

## Approximations and risks

- **Replay, cosmetic only:** the log keeps the cube's position but not its rotation (it keeps its starting yaw), and the gripper's opening but not its finger joints (fingers are posed from a table the replay measures at start-up).
- **First GUI launch** shows CoppeliaSim's "Welcome / choose Lua or Python" dialog until a choice is made once.
- Parallel seeds: each takes ~1.5 cores; with 20 cores, more than ~10 at once will slow every run.
