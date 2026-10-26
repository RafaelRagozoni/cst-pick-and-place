# agent — the CST mind of cap4 (WP2)

The eight codelets of cap4 §4.2 in CST, driving the CoppeliaSim scene through the simulation
bridge. Replaces `coppelia_environment/java/`: `BridgeClient`, `BridgeSmokeTest` and `CstMindBench`
moved here (`agent.sim`, `agent.bench`). CST comes from the `../cst` submodule, never a copied jar.

## Run

```
./gradlew test                       # 67 tests, offline; ParityTest runs python3
# live: CoppeliaSim open (or headless: `sleep infinity | ./coppeliaSim.sh -h`), then
mkdir -p runs && python3 ../coppelia_environment/bridge.py --log runs/C0_ucb_s1.jsonl.gz --condition C0
./gradlew liveRun -PagentArgs="--condition C0 --seed 1 --emax 50 --eref 20 --selection ucb"
python3 ../coppelia_environment/metrics.py runs/C0_ucb_s1.jsonl.gz
```

The agent shuts the bridge down at the end (`--shutdown false` to keep it): the bridge closes the
gzip log only on shutdown, and an unclosed one cannot be read. It refuses to run if the bridge logs a
different condition label than the one it runs. `--selection` (greedy, ucb, ucb:<c>, thompson;
default greedy) is the selection mechanism. Every logged step records `selection` and the `spread`
it used, and `metrics.py` reports the selection (two names means two runs went into one log).
`--curiosity` (none, count, count:<W>, lp, lp:<W>; default none) is the Curiosity yield ("Curiosity
that runs out"); every logged step records `curiosity` and the `yield`.

Long runs go through `../tools/run_live.py`, which also checkpoints and resumes them (below).

## Checkpoints

`--checkpoint FILE` saves the agent after every episode (`Checkpoint.java`); `--keep-every N` also
keeps a copy every N episodes in `checkpoints/after-epNNNNNN.json.gz`; `--resume FILE` continues
from one: same condition, selection and seed, next episode, same phase. It is the training
checkpoint of ML (YOLO's `last.pt`, PyTorch's model + optimizer + epoch), but with no weights: what
carries over is the credit table, the novelty archive and visit counts, the random generator
mid-sequence, the counters that number cycles, goals, plans and ExecutionBuffer entries, and where
the run stands. Everything else restarts each episode, so a checkpoint is only taken between them.

It refuses a checkpoint saved under another `Config` or with another pool, rather than resume a
different run. Cost, measured at a pessimistic size (archive full at 5000 points, 50 k visited bins,
14 × 5000 credit cells): 4.0 MB, ~0.23 s per save (~2.5 %) against ~9 s per 500-step episode; on the first
live episodes, 1–18 ms. Under Bullet a resumed run is not the run that would have gone on (its
physics varies per process, see Risks), but it is the same agent, so the same experiment.

## Goal

WP2 of cap5: every component of cap4 §4.2–4.3 implemented, unit-tested, and running closed-loop on
the real scene. The HabitLearner's generative half (mutation, fusion, macros, culling) is WP3 and
is not here yet.

## Architecture

| cap4 | class | reads | writes |
|---|---|---|---|
| Sensory | `SensoryCodelet` | the bridge (`SimLink`) | SensoryMO (Idea), SensoryBuffer |
| Drive Generator | `DriveGeneratorCodelet` | SensoryMO, GoalMO, PlanTrackerMO | DriveMO (Idea) |
| Goal Generator | `GoalGeneratorCodelet` | SensoryMO, DriveMO | GoalMO (Idea) |
| PlanTracker | `PlanTrackerCodelet` | SensoryMO, GoalMO, DriveMO, PlanMO | PlanTrackerMO, ExecutionBuffer |
| Credit Assignment | `CreditAssignmentCodelet` | ExecutionBuffer, DriveMO, SensoryMO | CreditMO |
| HabitLearner | `HabitLearnerCodelet` | CreditMO | HabitPoolMC |
| Behavior Generator | `BehaviorGeneratorCodelet` | HabitPoolMC, GoalMO, SensoryMO, DriveMO, PlanTrackerMO | PlanMO |
| Motor | `MotorCodelet` | PlanTrackerMO | the bridge |

Lines the cap4 figure may not have yet: **Drive ← GoalMO** (Effort restarts on a new goal),
**Drive ← PlanTrackerMO** (the habit whose commands produced this observation; only the `lp`
Curiosity yield reads it), **PlanTracker ← DriveMO** (the Curiosity and Safety goals are met by a
drive level), **Credit ← SensoryMO** (cycle and episode boundaries). SensoryBuffer is wired into Credit Assignment as in the
figure, but nothing reads it yet.

The Behavior Generator scores; a `Selector` decides. Selection is one function,
`(candidates, running, rng) -> habit to start, or null to keep the running plan`, and the mechanism
in use is one line of `Config` (`selection = "greedy"`) or `--selection` on the command line:

| name | ranks by | |
|---|---|---|
| `greedy` | E(h) | cap4 as written; the default |
| `ucb`, `ucb:<c>` | E(h) + c·σ·√(2 ln N / n) | UCB1 (c = 1 by default): a habit tried less than the rest gets a bonus, so an unlucky first result is retried; `ucb:0` is greedy |
| `thompson` | a draw from N(E(h), σ²/(n+1)) | Gaussian Thompson sampling: chosen with the probability it is the best; no parameter |
| `random` | — | C6, which refuses any other |

All but RANDOM keep the running plan unless beaten. n is the executions behind the score (the
context's, or the total's where the context has none — the same cell the score reads). σ is the
spread of one execution's score: `CreditTable` keeps each finished execution's credit as a sample
(an execution is finished when the habit runs again or the episode ends — its trace stops
collecting), and σ pools the within-habit covariance over the pool, read through the drive levels.
Because σ is in the units of the scores, UCB's c = 1 needs no calibration to the drives. A new
mechanism is one more entry in `Selectors` and its name in `Selectors.byName`; it must draw only from
the `rng` it is given, or a seed stops reproducing a run. The Behavior Generator makes its selector
from the name, so a stateful one (thompson) is never shared between minds.

A habit is an Idea (`HabitIdeas`): `origin`, `parents`, `commands` (one Idea per record of the
`actions.py` schema), and `credit`, a frozen `CreditSnapshot` the HabitLearner copies in.

### Why a fixed schedule

One cycle = one observation in, one simulation step out. `AgentMind.cycle()` runs the codelets in a
fixed order through CST's own `notifyCodelet`:

```
Sensory → Drive → Goal → PlanTracker(track) → Credit → HabitLearner → Behavior → PlanTracker(load) → Motor
```

The BRG-03 benchmark (moved here as `agent.bench.CstMindBench`) measured, over 400 cycles:

| Wiring | cycles/s | actions issued | applied | dropped |
|---|---|---|---|---|
| publish-subscribe | 58.4 | 400 | 400 | 0 |
| free-running timers | 39.8 | 1964 | 400 | 1563 |

Publish-subscribe in this CST is synchronous (`setI` runs the observer's `proc()` inline), so the
schedule is the same mechanism with the order made explicit. An observer chain would not do here:
Motor → Sensory closes a loop that nests one stack frame deeper per step; the PlanTracker has to run
on both sides of the Behavior Generator (else every habit change costs an idle cycle — a third to a
half of all cycles with 1° primitives); and observer order is registration order, which a
reproducible-per-seed run should not depend on. `AgentMindTest` checks a seed reproduces a run
exactly.

## Choices the text leaves open, as implemented

- **Credit is read per execution** (`Config.creditRead = MEAN`). cap4 says credit "accumulates";
  read as a sum, a habit's score grows with how often it ran, and a context's sum and the total it
  falls back to are on different scales. Both sums and counts are stored; `SUM` is one setting away.
- **Novelty is per cycle**, not per completed habit as §4.3.1 says: the archive and the bin counts
  update every cycle, and the displacement dimension is the per-tick cube displacement — the same
  bins `metrics.characterise` uses for metric 5, which `ParityTest` holds together.
- **Task stage regression**: if the current stage's precondition stops holding (cube dropped), the
  Goal Generator falls back to the stage perception shows. TROCA only advances.
- **Release ends on the agent's own strict success test** (since 2026-10-20, vault spec BAS-01): the
  cube let go over the pad after a transport, then still for 10 observations, as goals.py's success
  test (version `SUCCESS_TEST`, S3 since the transport lift went from 0.03 to 0.05). That needs
  the carry's history, which the Sensory codelet keeps (`task.Carry`) and writes into SensoryMO's
  `carry` group, so `TaskStages` stays a function of one observation. A cube that reached the pad any
  other way is placed but not done: the Task keeps its need and points back at the cube. Before, any
  placed cube was `done`, and a push-in left the Task at 0 for the rest of the episode. `ParityTest`
  holds `Carry` to goals.GoalTracker on the expert trajectory and on test_success.py's cases.
- **Goal choice**: Safety ≥ 0.5 takes over; otherwise a drive must beat the goal's drive by 0.1; a
  drive whose goal is already met is not a candidate. Curiosity's goal is met by its boredom, not
  its level (since 2026-10-17): a low yield is exploring having stopped paying, not novelty found.
- **UCB and Thompson count executions per context** (goal, state bin): a habit with no record there
  has n = 0, even though its score then falls back to its total credit. The score may borrow what
  the habit did elsewhere; how much is known about it *here* may not (see "The bin-count bug").
- **σ is per habit, shrunk toward a reference** (since 2026-10-16; `CreditSnapshot.spread`,
  `Config.spreadPriorWeight` = 2): σ_h² = (2 σ₀² + the habit's own scatter) / (2 + n_h − 1). The
  reference σ₀ is how much one execution's score varies across the repertoire, every habit
  weighted once (`CreditSnapshot.reference`). A habit run once has σ₀; a habit whose results never
  vary falls toward 0 as its own executions accumulate, and only its own. Until then one σ was
  pooled over every execution, so the habit run most set it for all (Risks, "σ from one habit").
  The prior is the usual normal-inverse-gamma one with pseudo-observations; per-arm variance is
  what UCB-V and UCB1-Tuned use, with a prior here because most habits have few executions.
- **Thompson draws once per decision**: z is drawn when nothing is running and held while the plan
  runs. Drawn every cycle, some habit's lucky draw would preempt the running plan nearly every cycle.
- **Gains enter twice**: DriveMO holds gained levels, Credit differences them and Behavior weights
  by them, so E(h) scales with gain². Zeroing a gain still removes the drive cleanly.

## First live runs (2026-10-14, C0, seed 1, 500-step episodes)

| run | change | habits used | goal held by Curiosity | min eef→cube |
|---|---|---|---|---|
| 1 (3 ep) | — | 14, but 2 dominate | 56% | 0.28 m |
| 2 (6 ep) | empty archive no longer "maximally novel" | 14 | 97% | 0.14 m |
| 3 (6 ep) | `noveltyScale` 1.0 → 0.01 | **2** | 100% | 0.35 m (never moved) |

What they show:

1. **Greedy selection locks in.** cap4 says exploration needs no separate mechanism: untried habits
   score 0 and ties are random. Live, Curiosity creeps up every cycle in a familiar bin, so almost
   every execution is charged a little, and rare bin crossings pay a lot. Selection takes the best
   sample mean; a habit with one unlucky early sample is never retried, a lucky one is repeated.
   Run 3 locked into `grab_open` + `move_j5_neg` and never left the home bin. **This needs a
   decision**: options in Prior art below.
2. **Curiosity is uncalibrated.** At the default scale it sits at ~0.97 and holds the goal nearly
   always, starving Task; a calibrated scale makes credit swings larger and lock-in faster. Fix 1
   before tuning this.
3. Run 1 found a bug, fixed: an empty archive reported a large sparseness, so the first habit of a
   run was charged a Curiosity jump it did not cause and was never chosen again — it happened to be
   the one that pulls joint 5 off its limit.

Safety works: after the fix, recovering from a joint limit kept every joint ≥ 7° from it.

### Selectors live (2026-10-15, C0, seed 1, 6 × 500 steps, one run each)

These ran with the bin-count bug below, which inverts UCB's bonus inside a bin: the UCB and
Thompson rows are not the rules as designed.

| selection | two most-chosen habits | coverage bins | min eef→cube | goal held by Curiosity |
|---|---|---|---|---|
| greedy | 58 % (`grab_open` alone 35 %) | 22 | 0.22 m | 97 % |
| ucb | 22 % | **37** | **0.12 m** | 96 % |
| thompson | 22 % | 24 | 0.17 m | 100 % |

Both bandit rules end the lock-in: choices spread over all 14 habits. UCB also explored more of the
state space (+68 % bins) and came closest to the cube of any run so far. No run reached it
(5 cm) or succeeded. One seed each: the UCB–Thompson gap may be chance. Curiosity still holds the
goal nearly always, so Task never drives selection — calibrating Curiosity is now the next lever.

### The bin-count bug (found and fixed 2026-10-16)

`CreditSnapshot.count(context)` returned the habit's *total* executions where it had no record
under the current (goal, bin). UCB read that as "well known", so a habit never run in the bin got
a bonus of ~0.002 and the one habit run there once got ~0.25: inside a bin, UCB repeated what it
had already done. Rebuilt from the 2026-10-15 baseline logs (3 × 1000 episodes), the chosen habit
had already run in its context in **99 %** of choices, while only ~20 % of the habits had. That is
the opposite-pair back-and-forth in that batch, and a bonus that large drowned any credit (~0.001).
Now a habit with no record in the context has n = 0 there and is tried first
(`ucbTriesAHabitNeverRunHereBeforeRepeatingOneThatRan` fails on the old code).

Live after the fix (C0, UCB, seeds 1–3, the first 30 episodes against the baseline's):

| seed | bins visited, before → after | closest to the cube, before → after |
|---|---|---|
| 1 | 122 → 24 | 0.19 → 0.16 m |
| 2 | 93 → 26 | 0.13 → 0.15 m |
| 3 | 114 → 26 | 0.12 → 0.21 m |

Coverage fell 4–5×. Trying all 14 one-degree primitives in each bin, one move undoes another, and
the arm dithers in place; the bug's repetition was what carried it across bins. The bonus
(σ ≈ 0.045) still outweighs typical credit, so uncertainty, not credit, picks. Repeating an action
is the known remedy for dithering with small actions (temporally extended exploration: action
repeat, options, ε-z-greedy, Dabney et al. 2021); here that is a credit large enough to follow,
a smaller c, or WP3's macros. Open decision.

A 10× smaller bonus (`--selection ucb:0.1`), same seeds and episodes: 52 / 55 / 75 bins (against
24 / 26 / 26 at c = 1), closest 0.13 / 0.17 / 0.09 m, median distance per 10-episode block
0.16–0.19 m against 0.20–0.29 m; choices still spread (two most-chosen habits ~22 %). With doubt
weighing less, credit steers the arm to 2–3× more places: it carries some signal, but not enough to
match the bug's accidental persistence, and no run reached the cube.

### Credit, round 1 (2026-10-16): shorter trace, progress, baseline

What the credit recorded, rebuilt from the `ucb:0.1` logs: a habit's *own* effect on Task, repeated
in the same bin, kept its sign 81–89 % of the time (chance is 50 %), but the recorded credit only
67–73 %. Primitives last one cycle and the trace (λ = 0.9 per cycle) shared each execution's credit
with the ~30 after it: ~60 % of a habit's recorded credit was what the habits after it did. One
execution moves the hand ~0.2 cm (Task ~0.005). Curiosity rose in ~63 % of cycles whatever ran.

Three changes, applied in turn, each run as C0, `ucb:0.1`, seeds 1–3, 30 episodes:

| run | bins (s1/s2/s3) | closest (m) | median distance, ep. 20–29 (m) | episodes with a reach |
|---|---|---|---|---|
| before (λ 0.9) | 52 / 55 / 75 | 0.13 / 0.17 / 0.09 | 0.20 / 0.23 / 0.21 | 0 |
| **A** λ 0.5 | **116 / 114 / 108** | **0.08 / 0.07 / 0.04** | 0.18 / 0.17 / 0.20 | **1** |
| A + B progress (window 20) | 82 / 102 / 96 | 0.13 / 0.13 / 0.13 | 0.23 / 0.27 / 0.24 | 0 |
| A + B + C baseline (0.1) | 102 / 87 / 47 | 0.13 / 0.17 / 0.15 | 0.30 / 0.25 / 0.33 | 0 |
| A + C | 80 / 99 / 73 | 0.10 / 0.08 / 0.11 | 0.18 / 0.15 / 0.16 | 0 |

- **A (`lambda` 0.9 → 0.5)** doubled coverage and came closest in every seed; the recorded Task
  credit now keeps its sign in 86–87 % of repeats. The one clear gain.
- **B (`progressWindow`: credit only progress beyond the recent best)** was worse in every seed. Its
  cost is the one it was chosen with: moving away earns 0 instead of a charge, and coming back to a
  point already reached earns 0, so 70 % of executions earn exactly 0 and the gap between the best
  and the worst habit in a bin falls 4–5× (0.015 → 0.0035). The plain change already nets a
  back-and-forth to zero across the pair while telling each move apart.
- **C (`baselineRate`: minus the context's running mean per step)** shows no clear gain. A baseline
  shared by every habit in a context barely changes their ranking, and UCB ranks within a context;
  only the order in which habits were first tried, and the spread, can move. Its first version
  subtracted a per-cycle mean times the step's length and charged 44-cycle grabs for dozens of bin
  crossings (σ tripled, coverage 23 / 21 / 27): fixed, with a test.

Thirty episodes and three seeds: A's effect is large and the same in every seed; B's harm is
consistent and explained; C is within the noise.

**B with the retreat charged** (`progressChargesRetreat`: moving away costs its plain change; only
coming back over ground covered in the window earns 0), same protocol: seeds 1–2 like A (107 / 109
bins, closest 0.10 / 0.06 m); seed 3 never left the home bin in 30 episodes (1 bin, `grab_open`
chosen 99–100 %). Two causes, read from its checkpoint:

1. *The rule makes moving cost on average.* A retreat is charged, the approach that undoes it earns
   0, so a move's expected Task credit is negative and doing nothing is the best score. In seed 3
   eleven of the thirteen habits tried once came out negative on Task; `grab_open` with the gripper
   already open sat at ~0. The plain change is symmetric and has no such pull.
2. *UCB's σ collapsed to zero* — a selector bug that A can hit too: see Risks, "σ from one habit".


## Curiosity that runs out (2026-10-17, vault spec CUR-01)

The long batch `runs/2026-10-16_1750_C0_ucb-0.1` (6 seeds × ~660 episodes, commit d8125ec) reached
the cube in 351 episodes and grasped it in 61 (the baseline batch: 6 and 0), but never transported
it, and got worse after episode ~200 (median closest 0.08–0.14 → 0.16–0.25 m). Task set the goal in
~0 % of steps. Not a calibration problem — it cannot, by construction:

- Task = distance / 0.5, capped at **1**; a drive must beat the goal's drive by **0.1**
  (`goalHysteresis`); Curiosity = 1 / (1 + novelty) sits at **~0.995** (novelty median ~0.006). Task
  would need > 1.095. Its ~0–1 % came only from moments Curiosity's goal was met.
- And Curiosity *rises* as the agent explores: the fuller the archive, the lower the novelty. It
  measures "bored here", never "nothing left to explore".

The fix keeps the boredom and multiplies it by a **yield** y ∈ [0, 1], "is exploring still paying"
(`CuriosityYield`; `Config.curiosityYield`, `--curiosity`):

| name | x per cycle (y = running mean of x over W cycles, y₀ = 1, W = 2500 by default) | after |
|---|---|---|
| `none` | — (y = 1) | cap4 as written; **Task stays blocked**. The default only so old batches compare |
| `count`, `count:<W>` | 1 / √(times the bin was *entered*, ever) | MBIE-EB, #Exploration |
| `lp`, `lp:<W>` | the bin's learning progress: how fast the error of predicting a habit's effect (mean Δb per bin and habit) falls, relative, over the last 2 × 10 errors; 1 for a bin with fewer | IAC (Oudeyer et al. 2007) with fixed regions |

Entries, not cycles: crossing a 5 cm bin takes ~25 one-degree executions, so counting cycles would
make a new bin look familiar on its first crossing. lp's error has a floor (`Yields.LP_FLOOR`,
0.001 bin): without it a learned effect's errors are rounding noise and their relative fall is
anywhere in [0, 1]. A learned effect and pure noise both leave lp at ~0, so the "noisy TV" that
prediction-error curiosity (ICM) gets stuck on — and Bullet's contacts vary per process — is no trap.

Two things y must not do, both tested:
1. **Earn credit by drifting.** y falls by itself; differenced as a level, that fall would be
   Curiosity credit for whatever ran, more for whatever ran longer (WP3's macros). Credit measures
   Curiosity's change at this cycle's yield (the previous level rescaled to it): only boredom's.
2. **Meet Curiosity's goal.** Met is boredom < `curiosityGoalMet` (novelty found), not the level, or a
   low yield would fill ExecutionBuffer with goal completions nothing achieved.

With `none` every command and logged decision is the code before this change, bit for bit: checked
once on the fake environment (C0 ucb:0.1, C0 greedy, C3 thompson, C1 ucb; 8 × 150 steps each) by
diffing the logs, and held since by every older test passing unchanged. **Not run live yet.**

## Testing

`./gradlew test`: 67 tests, ~1 s, no simulator.

- `ParityTest` — the Java ports agree with the Python they port, on the recorded expert trajectory:
  task predicates (goals.py), characterization bins (metrics.characterise), step completion
  (actions.StepCompletion, 15 scenarios: arrive, stall, parallel, gripper, hold). It runs
  `tools/parity_dump.py` fresh. Mutation-checked: changing `REACH_DIST` or `GRIP_MIN_TICKS` fails it.
- `CodeletsTest` — each codelet alone through its memories: step order and records, preemption, goal
  completion closing a plan, eligibility-trace arithmetic, λ = 0, the Effort restart not credited,
  keep-unless-beaten, seeded ties, the Goal Generator walking reach → grasp → transport → release →
  done on the expert trajectory, Safety override, hysteresis.
- `UnitsTest` pins the Curiosity yields: names refused, `none` = 1; `count` counts entries, not
  cycles in a bin, never forgets, and averages over W; `lp` is 1 until a bin has 2K errors, falls to
  0 when the effect is learned, stays < 0.1 on pure noise, rises again when the effect changes, and
  ignores resets and idle cycles. `CodeletsTest` holds the two safeguards: a yield drifting from 1 to
  0.8 credits nothing, boredom's fall is credited at the current yield; a bored Curiosity keeps the
  goal from a Task at its cap, a low yield hands it over, and that does not meet Curiosity's goal.
- `UnitsTest` also pins the selectors: an execution becomes one credit sample only when its credit
  stops arriving, σ from hand-computed samples, UCB retrying a habit with one bad result that GREEDY
  abandons, Thompson holding its draws (no preemption on noise) and reproducing per seed.
- `AgentMindTest` — the whole mind against `FakeEnvironment` (a kinematic stand-in): one sim step per
  cycle and none on the terminal observation, exact reproduction per seed, credit reaching the pool,
  steps never overlapping, no idle cycles, C6 learning nothing, all seven conditions running, the
  refinement phase raising Effort; each Curiosity yield closed-loop, logged, in [0, 1], with
  `count:200` and `lp:200` falling under 0.9 in the small fake world; UCB and Thompson closed-loop trying all 14 habits, reproducing per
  seed, logging their name and σ, and with σ > 0 — at σ = 0 both silently rank by score alone, like GREEDY. Mutation-checked:
  dropping the sample recording fails three tests.

- `CheckpointTest` — a run paused after episode 3, saved to a file and resumed in a new mind is the
  run that never stopped: every command and every logged decision (habit, goal, drive levels,
  novelty, σ, yield) of episodes 3–5 equal, and the same state at the end; for GREEDY, UCB,
  Thompson, C3, C6, across the refinement switch, and with the `count` and `lp` yields. A wrong Config, a used mind and a mid-episode save are
  refused. Mutation-checked: leaving out any one restored piece (archive, generator, credit, the
  credit copied to the pool, cycle, goal or ExecutionBuffer numbering) fails it. The PlanTracker's
  last plan and goal numbers were left out because doing so failed nothing: they only compare
  against numberings that continue.

Nothing checks the agent *learns the task*: that is WP3's gate, judged on live runs.

## Deferred

- **HabitLearner generation (WP3)**: mutation, parallel fusion, macros at goal completion, culling,
  pool cap. `Config.generation`/`fusion` are wired to conditions but unread. Culling needs a
  member-removal operation in CST's `MemoryContainer` (cap4 §4.4.3), which the fork does not have.
- The macro selection rule (open in cap4 §4.4.2).
- Which selector: UCB and Thompson ran live once each (above), both with the bin-count bug; rerun
  them before choosing. On the fake environment (C0, 3 seeds, 6 × 300 steps) the two most-chosen
  habits take 57–76 % of choices under GREEDY and 20–24 % under either — plumbing evidence, not
  physics.
- A credit baseline (advantage): tried (`baselineRate`, "Credit, round 1"), no clear gain over 30
  episodes; a longer run would tell.
- A discounted or sliding-window UCB if non-stationarity (below) shows up. (Per-habit variance:
  done, with a prior.)
- Checkpoints of generated habits (WP3): the pool is checked, not saved, so a resume refuses a pool
  that is not the primary repertoire. ExecutionBuffer entries are not saved either (only their
  numbering); if WP3's macros read across an episode end, they must be.
- **Curiosity yields not built** (CUR-01): RND / ICM (counts are exact over the bins, and no ML
  library here); learning progress as competence on Curiosity's own goals (SAGG-RIAC; those goals
  are probably almost never met — boredom < 0.3 needs novelty ~35× its 90th percentile — not
  measured); adaptive regions (R-IAC) instead of fixed bins; lp's effect model for WP3's macros.
- **Curiosity coming back when Task is stuck** (grasped, never transported): no yield does that; it
  would be a mechanism of its own (Task's progress, or Effort).
- Using the kept checkpoints: evaluating a frozen agent (no credit updates) at episode 100, 500,
  1000; starting a new batch from one, e.g. another selector from the same learned state.

## Risks

- **σ from one habit** (found and fixed 2026-10-16): the pooled spread counted only habits with
  two or more finished executions. When one habit was the only such habit and its results never
  varied, σ was ~0, UCB's bonus vanished and selection was greedy for the rest of the run, with
  nothing erroring. Live (B with the retreat charged, seed 3): every habit tried once in episode
  0, `grab_open` — a no-op with the gripper already open — then repeated 4978 times with variance
  ~5e-11; the other thirteen were never retried in 30 episodes. Each habit now has its own σ
  shrunk toward a repertoire-wide reference ("Choices"); `aRepeatedNoOpDoesNotSilenceTheBonus...`
  fails on the pooled version. What is left: σ₀ is 0 while every habit's results are identical,
  which the log's `spread` column shows.
- **The silent failure**: credit that looks healthy but is mostly passive boredom drift. Every habit
  gets *some* credit every run, so nothing errors; only per-habit drive-change statistics (as in
  the live-run analysis above) show whether credit tracks what the habit did.
- **Per-context exploration preempts plans and grows with the pool.** Under UCB a habit never run
  in the current bin goes before any other, so a running plan is replaced whenever, in the bin it
  is passing through, it has run before and some other habit has not. Primitives last a cycle or
  two and barely notice; WP3's macros would be cut short. And every new context costs one try per
  habit: 14 now, more as the HabitLearner adds habits.
- **Credit is not stationary**, and UCB and Thompson assume it is. Curiosity habituates, so a
  habit's early credit is not what it would earn now; n only grows, so the bonus never comes back
  for a habit whose old credit is stale. Discounted UCB (Garivier and Moulines 2011) is the
  standard fix.
- **Live runs do not reproduce per seed** (found 2026-10-15). Same-seed agent runs issue identical
  actions, yet the physics parts at the first contact (the gripper closing on nothing, fingers
  touching), by ~1e-8 rad; the agent amplifies it and the habit choices part ways within ~1
  episode. A minimal test without the agent (idle / move the base / close the gripper, 3 runs per
  bridge session) narrowed it to two causes, neither of them the GUI:
  1. *Bullet's contacts are not deterministic across processes.* At first it looked like a scene
     reloaded in a long-lived process (a first load matched across processes once). It is not:
     six fresh processes closing the gripper on nothing gave three different physics, parting at
     the finger contact by ~3e-5 — with address randomization off and Python's hash seed fixed
     alike. Within one process repeated runs are identical. Under **MuJoCo, ODE and Newton** all
     six were identical, the fingers closing in each. `test_fresh_process.py` (SIM-09, five fresh
     processes) fails under Bullet. Switching engine is open: grasping, contacts, joint limits and
     the expert trajectory were all measured under Bullet. A trial of the whole simulation suite
     under MuJoCo (scene and `pin_physics` switched in a copy, 2026-10-15): SIM-09 passes; reset,
     determinism, bridge, observations, actions, goals and runner pass; the pilot still solves the
     task, but in **520 steps against 248** (primitives take ~2× the ticks: the timing constants in
     `actions.py` were measured under Bullet) — over the 500-step episode limit; the joint-limit
     guard overshoots by 0.18°; `test_grasp_rule.py` fails (the fingers close through a cube the test
     teleports mid-simulation — MuJoCo may need `resetDynamicObject` there; the pilot's grasp works).
  2. *Reset did not reset the gripper's motor* — **fixed**: the finger motor's target velocity
     survived the stop, so an episode after one that closed the gripper started 4.6 mm more closed,
     and every episode began with the fingers still opening. `EpisodeReset` now zeroes it and waits
     for the fingers to stop (reset 0.34 → 0.46 s); `test_episode_reset.py` checks both.
  What 1 costs: not the paired statistics — conditions are paired on the cube placements, a pure
  function of (seed, episode), which `pilot.py` already argued and which still holds — but exact
  replay: a run cannot be re-run to debug it, and a C0–Cx difference in one pair mixes the
  component's effect with physics noise, so it needs more seeds to show.
- **A checkpoint is tied to the code that wrote it.** `FORMAT`, the Config check and the pool
  check refuse the mismatches they can see; a change in what a component means (a field reread
  differently) they cannot. `run_live.py --resume` therefore runs the batch's own agent snapshot.
- **Task's contexts are empty** when the yield first hands it the goal: Task held the goal ~0 % of
  every run so far, so credit under (Task stage, bin) has almost no records, and UCB starts from
  scratch there. "Task took over and things got worse" can be that, not the yield.
- **The yield that never falls** (the silent failure of CUR-01): if the bins keep multiplying (a
  pushed cube makes every cube × hand bin new), coverage grows and everything looks healthy while
  Task stays blocked. The summary's `y` column is there to show it; the yields' W, lp's K and floor
  are uncalibrated.
- **Curiosity taking the goal back mid-transport**: carrying the cube makes new bins (count) and new
  effects (lp), so y rises just when Task makes progress. The hysteresis damps it; the goal column
  shows it.
- Novelty search is O(archive) per cycle; capped at 5000 points.
- The Fake environment tests the plumbing, not the physics; the live scene is the only physics check.

## Prior art / alternatives considered

| Alternative | What it would give | Why not (for now) |
|---|---|---|
| Python agent on the bridge (Gymnasium-style loop, `runner.py` already has one) | 2–5× less code, same language as the environment, numpy | cap4 implements the system *inside CST*; that is the thesis's claim. The cost is the three Java ports, which `ParityTest` guards |
| Stable-Baselines3 PPO/SAC + an intrinsic reward (RND, ICM) | A tested learner for the same scene | Learns one policy network, not a repertoire of habits: metric 4 and the HabitLearner have nothing to act on. Still the strongest *external* baseline if a reviewer asks "why not RL?" — not in the C0–C6 grid |
| CST's motivational subsystem (`MotivationalCodelet`, `Drive`, `GoalCodelet`) | Drives and goals already in CST | One codelet per drive (the professor merged them into one Drive Generator); activation is remapped through an urgency threshold (`0.5 + priority` vs `level/2`), which would make "credit = how much the level fell" nonlinear; `GoalCodelet` reads one "hypothetical situation" and skips its first cycle |
| CST `HabitExecutionerCodelet` / `GroupHabitExecutionerCodelet` | Habit execution in CST | Executes code via `Habit.exec`; cap4's habits are data run step by step by PlanTracker + Motor |
| Behavior-tree library (e.g. gdx-ai) for the PlanTracker | Sequence/parallel nodes with success conditions | A habit's normal form is a flat list of parallel steps; translating Ideas into BT nodes costs more than the ~200-line tracker, and the learner mutates the Ideas |
| Quality-diversity libraries (pyribs, QDax, Sferes2) for the archive | Tested novelty/MAP-Elites archives | Python/C++; here the archive is ~100 lines inside a codelet, tested in `UnitsTest` |
| **Homeostatic RL** (Keramati & Gutkin 2014) | Reward = drive reduction | Adopted as the idea behind credit; no library involved |
| **Q-decomposition / Hybrid Reward Architecture** (Russell & Zimdars 2003; van Seijen et al. 2017) | Per-component values combined only at action selection | This *is* late fusion. Their values bootstrap (TD); this credit is a non-bootstrapped trace-weighted mean — the ladder's next rung |
| CST's `MemoryContainer` policies (`MAX`, `RANDOM_FLAT`, `RANDOM_PROPORTIONAL`, `*_STABLE`) as the selector | Selection native to CST: set each habit's evaluation, read the container | Its `Random` is unseeded, so a run would not reproduce per seed; `RANDOM_PROPORTIONAL` is a roulette that assumes evaluations ≥ 0, and E(h) is mostly negative; an evaluation lives on the habit's memory while E(h) depends on goal and state, so every evaluation would be rewritten each cycle; no UCB, softmax temperature or ε |
| Selection as its own codelet (swap by rewiring) | The most CST-shaped plug | A ninth codelet and a new box in the cap4 figure for what one function does |
| **Exploration for lock-in** (multi-armed / contextual bandits): ε-greedy, softmax over E(h), UCB, Thompson sampling, optimistic initial credit, a per-state baseline subtracted from ΔD (advantage) | Standard fixes for greedy selection on noisy estimates | UCB and Thompson implemented as selectors, the choice pending live runs. ε-greedy explores blindly; softmax needs a temperature in the units of E(h), which move with the drive levels and gains; optimistic credit helps only habits never run, while the failure is a habit run once. The baseline is a credit change, not a selector. cap4's claim that exploration needs no separate mechanism changes either way |
| Checkpoint: Java serialization of the whole `AgentMind` | One call, nothing to list by hand | CST's `Mind`, codelets and their `Timer` threads are not serializable; a binary blob breaks on any class change and cannot be read with `zcat \| jq`. Kept for one field: `java.util.Random` has no other public way to its state |
| Checkpoint: a process snapshot (CRIU) of agent, bridge and CoppeliaSim | Resume anything, mid-episode | Three processes, ZeroMQ sockets and a simulator's GPU/GL state; Linux-only and fragile; and the gain (resume mid-episode) is worth one episode at most |
| Checkpoint: Gson reflection on the components | No hand-written state()/restore() | Restoring a renamed field leaves its default, silently; the explicit reads fail loudly on a missing key |
| **The agent knowing it succeeded** (2026-10-20, BAS-01): read the environment's success, as RL benchmarks do (Gymnasium's `info["is_success"]`, the bridge's `success`) | Zero code, and never disagrees with the experiment | A robot outside the simulator has no such signal, and cap4 has the agent perceive its task (`TaskStages`). Ours, `task.Carry`, ports goals.py's carry instead. What it loses: two copies of one rule, kept equal only by `ParityTest`; and the bridge also needs its four steps fired in order, which `Carry` does not track (they part only on a carry transported in its first two held observations alone) |
| **Credit that tells habits apart** (2026-10-16): a shorter eligibility trace (TD(λ)'s λ); credit as progress beyond the recent best, close to the competence progress of SAGG-RIAC (Baranes and Oudeyer 2013); an advantage baseline (REINFORCE with baseline, Sutton and Barto §13.4); larger steps or action repeat (frame skip in Atari agents) | Each is a standard answer to one measured flaw: credit diluted by later habits, back-and-forth, drift every habit is charged, effects too small to see | All three credit changes implemented as `Config` settings and run live ("Credit, round 1"): λ 0.5 kept; progress lost the sign of moving away and was worse; the baseline is near ranking-neutral under per-context UCB. Action repeat changes the primitives, not credit — WP3's mutation of a habit's angle is where it would come from |
| **Curiosity that runs out** (2026-10-17, vault spec CUR-01): count-based bonuses (MBIE-EB, Strehl and Littman 2008; pseudo-counts, Bellemare et al. 2016; #Exploration, Tang et al. 2017); learning progress (IAC, Oudeyer, Kaplan and Hafner 2007; R-IAC, Baranes and Oudeyer 2009); RND (Burda et al. 2018), ICM (Pathak et al. 2017); an annealed intrinsic weight, or Agent57's bandit over it (Badia et al. 2020); RLeXplore (rllte, 2024), a library of eight intrinsic rewards | Ways for exploration to stop paying once the world is known | Count and learning progress built, as `count` and `lp` yields. RND/ICM exist for spaces that cannot be counted, and these bins can; ICM also chases noise, and Bullet's contacts are noise. Annealing hands over by the clock, not by exploration; Agent57 needs task return to tune it, and there are no successes. RLeXplore is Python/PyTorch, per-step rewards for an RL learner, no learning progress. What ours loses against the strongest (a count bonus added to the reward, as published): the evidence is for that form; a running mean used as a drive's urgency is our adaptation, untested, with one more parameter (W) |
| Bandit libraries: MABWiser (Python), Vowpal Wabbit's contextual-bandit exploration (C++, JNI binding) | Tested rules: UCB1, Thompson, softmax, ε-greedy, LinUCB (MABWiser); ε-greedy, softmax, bagging, cover (VW) | Each learns its own reward estimate; here the estimate is the credit table (per-drive late fusion, eligibility traces), and only the ~20-line ranking rule would be reused. Python or native code inside a CST codelet for that is the worse trade |

What building our own gains: the habit is a CST Idea end to end, every cap4 component is a codelet
you can point at, and the conditions are clean switches. What it loses against the strongest
alternative (an SB3 learner): a learner that is known to work on this kind of scene. Nothing here
has yet shown it learns the task.
