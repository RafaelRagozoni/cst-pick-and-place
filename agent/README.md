# agent — the CST mind of cap4 (WP2)

The eight codelets of cap4 §4.2 in CST, driving the CoppeliaSim scene through the simulation
bridge. Replaces `coppelia_environment/java/`: `BridgeClient`, `BridgeSmokeTest` and `CstMindBench`
moved here (`agent.sim`, `agent.bench`). CST comes from the `../cst` submodule, never a copied jar.

## Run

```
./gradlew test                       # 33 tests, offline; ParityTest runs python3
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

`./gradlew test`: 33 tests, ~1 s, no simulator.

- `ParityTest` — the Java ports agree with the Python they port, on the recorded expert trajectory:
  task predicates (goals.py), characterization bins (metrics.characterise), step completion
  (actions.StepCompletion, 15 scenarios: arrive, stall, parallel, gripper, hold). It runs
  `tools/parity_dump.py` fresh. Mutation-checked: changing `REACH_DIST` or `GRIP_MIN_TICKS` fails it.
- `CodeletsTest` — each codelet alone through its memories: step order and records, preemption, goal
  completion closing a plan, eligibility-trace arithmetic, λ = 0, the Effort restart not credited,
  keep-unless-beaten, seeded ties, the Goal Generator walking reach → grasp → transport → release →
  done on the expert trajectory, Safety override, hysteresis.
- `AgentMindTest` — the whole mind against `FakeEnvironment` (a kinematic stand-in): one sim step per
  cycle and none on the terminal observation, exact reproduction per seed, credit reaching the pool,
  steps never overlapping, no idle cycles, C6 learning nothing, all seven conditions running, the
  refinement phase raising Effort.

Nothing checks the agent *learns the task*: that is WP3's gate, judged on live runs.

## Deferred

- **HabitLearner generation (WP3)**: mutation, parallel fusion, macros at goal completion, culling,
  pool cap. `Config.generation`/`fusion` are wired to conditions but unread. Culling needs a
  member-removal operation in CST's `MemoryContainer` (cap4 §4.4.3), which the fork does not have.
- The macro selection rule (open in cap4 §4.4.2).
- An exploration mechanism or a credit baseline, if chosen (see First live runs, 1).

## Risks

- **The silent failure**: credit that looks healthy but is mostly passive boredom drift. Every habit
  gets *some* credit every run, so nothing errors; only per-habit drive-change statistics (as in
  the live-run analysis above) show whether credit tracks what the habit did.
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
| **Exploration for lock-in**: ε-greedy, softmax over E(h), UCB bonus, optimistic initial credit, a per-state baseline subtracted from ΔD (advantage) | Standard fixes for greedy selection on noisy estimates | Not adopted: cap4 claims exploration needs no separate mechanism, and choosing one changes the thesis. The live runs say it is needed; the decision is the author's |

What building our own gains: the habit is a CST Idea end to end, every cap4 component is a codelet
you can point at, and the conditions are clean switches. What it loses against the strongest
alternative (an SB3 learner): a learner that is known to work on this kind of scene. Nothing here
has yet shown it learns the task.
