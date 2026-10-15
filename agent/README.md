# agent — the CST mind of cap4 (WP2)

The eight codelets of cap4 §4.2 in CST, driving the CoppeliaSim scene through the simulation
bridge. Replaces `coppelia_environment/java/`: `BridgeClient`, `BridgeSmokeTest` and `CstMindBench`
moved here (`agent.sim`, `agent.bench`). CST comes from the `../cst` submodule, never a copied jar.

## Run

```
./gradlew test                       # 39 tests, offline; ParityTest runs python3
# live: CoppeliaSim open (or headless: `sleep infinity | ./coppeliaSim.sh -h`), then
mkdir -p runs && python3 ../coppelia_environment/bridge.py --log runs/C0_s1.jsonl.gz --condition C0
./gradlew liveRun -PagentArgs="--condition C0 --seed 1 --emax 50 --eref 20"
python3 ../coppelia_environment/metrics.py runs/C0_s1.jsonl.gz
```

The agent shuts the bridge down at the end (`--shutdown false` to keep it): the bridge closes the
gzip log only on shutdown, and an unclosed one cannot be read. It refuses to run if the bridge logs a
different condition label than the one it runs.

## Goal

WP2 of cap5: every component of cap4 §4.2–4.3 implemented, unit-tested, and running closed-loop on
the real scene. The HabitLearner's generative half (mutation, fusion, macros, culling) is WP3 and
is not here yet.

## Architecture

| cap4 | class | reads | writes |
|---|---|---|---|
| Sensory | `SensoryCodelet` | the bridge (`SimLink`) | SensoryMO (Idea), SensoryBuffer |
| Drive Generator | `DriveGeneratorCodelet` | SensoryMO, GoalMO | DriveMO (Idea) |
| Goal Generator | `GoalGeneratorCodelet` | SensoryMO, DriveMO | GoalMO (Idea) |
| PlanTracker | `PlanTrackerCodelet` | SensoryMO, GoalMO, DriveMO, PlanMO | PlanTrackerMO, ExecutionBuffer |
| Credit Assignment | `CreditAssignmentCodelet` | ExecutionBuffer, DriveMO, SensoryMO | CreditMO |
| HabitLearner | `HabitLearnerCodelet` | CreditMO | HabitPoolMC |
| Behavior Generator | `BehaviorGeneratorCodelet` | HabitPoolMC, GoalMO, SensoryMO, DriveMO, PlanTrackerMO | PlanMO |
| Motor | `MotorCodelet` | PlanTrackerMO | the bridge |

Lines the cap4 figure may not have yet: **Drive ← GoalMO** (Effort restarts on a new goal),
**PlanTracker ← DriveMO** (the Curiosity and Safety goals are met by a drive level), **Credit ←
SensoryMO** (cycle and episode boundaries). SensoryBuffer is wired into Credit Assignment as in the
figure, but nothing reads it yet.

The Behavior Generator scores; a `Selector` decides. Selection is one function,
`(candidates, running, rng) -> habit to start, or null to keep the running plan`, and the mechanism
in use is one line of `Config`:

| `selector =` | ranks by | |
|---|---|---|
| `Selectors.GREEDY` | E(h) | cap4 as written; the default |
| `Selectors.ucb(1.0)` | E(h) + c·σ·√(2 ln N / n) | UCB1: a habit tried less than the rest gets a bonus, so an unlucky first result is retried |
| `Selectors.thompson()` | a draw from N(E(h), σ²/(n+1)) | Gaussian Thompson sampling: chosen with the probability it is the best; no parameter |
| `Selectors.RANDOM` | — | C6 |

All but RANDOM keep the running plan unless beaten. n is the executions behind the score (the
context's, or the total's where the context has none — the same cell the score reads). σ is the
spread of one execution's score: `CreditTable` keeps each finished execution's credit as a sample
(an execution is finished when the habit runs again or the episode ends — its trace stops
collecting), and σ pools the within-habit covariance over the pool, read through the drive levels.
Because σ is in the units of the scores, UCB's c = 1 needs no calibration to the drives. A new
mechanism is one more entry in `Selectors`; it must draw only from the `rng` it is given, or a seed
stops reproducing a run.

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
- **Release termination** is single-observation (released, on the pad, below settle speed); goals.py
  waits 10 observations. The episode ends on the environment's success anyway.
- **Goal choice**: Safety ≥ 0.5 takes over; otherwise a drive must beat the goal's drive by 0.1; a
  drive whose goal is already met is not a candidate.
- **σ is pooled over the pool**, not per habit: early on most habits have one or two samples, and a
  per-habit variance from two samples is noise. A quiet habit is treated as noisier than it is,
  which only means more exploration.
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

## Testing

`./gradlew test`: 39 tests, ~1 s, no simulator.

- `ParityTest` — the Java ports agree with the Python they port, on the recorded expert trajectory:
  task predicates (goals.py), characterization bins (metrics.characterise), step completion
  (actions.StepCompletion, 15 scenarios: arrive, stall, parallel, gripper, hold). It runs
  `tools/parity_dump.py` fresh. Mutation-checked: changing `REACH_DIST` or `GRIP_MIN_TICKS` fails it.
- `CodeletsTest` — each codelet alone through its memories: step order and records, preemption, goal
  completion closing a plan, eligibility-trace arithmetic, λ = 0, the Effort restart not credited,
  keep-unless-beaten, seeded ties, the Goal Generator walking reach → grasp → transport → release →
  done on the expert trajectory, Safety override, hysteresis.
- `UnitsTest` also pins the selectors: an execution becomes one credit sample only when its credit
  stops arriving, σ from hand-computed samples, UCB retrying a habit with one bad result that GREEDY
  abandons, Thompson holding its draws (no preemption on noise) and reproducing per seed.
- `AgentMindTest` — the whole mind against `FakeEnvironment` (a kinematic stand-in): one sim step per
  cycle and none on the terminal observation, exact reproduction per seed, credit reaching the pool,
  steps never overlapping, no idle cycles, C6 learning nothing, all seven conditions running, the
  refinement phase raising Effort; UCB and Thompson closed-loop trying all 14 habits, reproducing per
  seed, and with σ > 0 — at σ = 0 both silently rank by score alone, like GREEDY. Mutation-checked:
  dropping the sample recording fails three tests.

Nothing checks the agent *learns the task*: that is WP3's gate, judged on live runs.

## Deferred

- **HabitLearner generation (WP3)**: mutation, parallel fusion, macros at goal completion, culling,
  pool cap. `Config.generation`/`fusion` are wired to conditions but unread. Culling needs a
  member-removal operation in CST's `MemoryContainer` (cap4 §4.4.3), which the fork does not have.
- The macro selection rule (open in cap4 §4.4.2).
- Which selector: UCB and Thompson are implemented, not yet run live. On the fake environment
  (C0, 3 seeds, 6 × 300 steps) the two most-chosen habits take 57–76 % of choices under GREEDY and
  20–24 % under either — plumbing evidence, not physics.
- A credit baseline (advantage), part of rethinking credit.
- Choosing the selector on the command line (`--selection ucb`) instead of in `Config`, and logging
  its name and σ in the run, before comparing them live.
- Per-habit variance (UCB-V, UCB1-Tuned) once habits have enough samples; a discounted or
  sliding-window UCB if non-stationarity (below) shows up.

## Risks

- **The silent failure**: credit that looks healthy but is mostly passive boredom drift. Every habit
  gets *some* credit every run, so nothing errors; only per-habit drive-change statistics (as in
  the live-run analysis above) show whether credit tracks what the habit did.
- **Credit is not stationary**, and UCB and Thompson assume it is. Curiosity habituates, so a
  habit's early credit is not what it would earn now; n only grows, so the bonus never comes back
  for a habit whose old credit is stale. Discounted UCB (Garivier and Moulines 2011) is the
  standard fix.
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
| Bandit libraries: MABWiser (Python), Vowpal Wabbit's contextual-bandit exploration (C++, JNI binding) | Tested rules: UCB1, Thompson, softmax, ε-greedy, LinUCB (MABWiser); ε-greedy, softmax, bagging, cover (VW) | Each learns its own reward estimate; here the estimate is the credit table (per-drive late fusion, eligibility traces), and only the ~20-line ranking rule would be reused. Python or native code inside a CST codelet for that is the worse trade |

What building our own gains: the habit is a CST Idea end to end, every cap4 component is a codelet
you can point at, and the conditions are clean switches. What it loses against the strongest
alternative (an SB3 learner): a learner that is known to work on this kind of scene. Nothing here
has yet shown it learns the task.
