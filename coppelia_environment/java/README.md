# Java side of the simulation bridge (BRG-02 / BRG-03)

`BridgeClient.java` is the class the CST application will use. The other two are tests.

| File | What it is |
|---|---|
| `BridgeClient.java` | The client. One request per control cycle: command records in, one simulation step, full observation back |
| `BridgeSmokeTest.java` | BRG-02 acceptance — drives the arm and gripper over the wire, no task logic |
| `CstMindBench.java` | BRG-03 — a minimal **CST mind** (two codelets) driving the simulator, and the timing |

## Build and run — currently unbuildable, on purpose

`lib/` and `out/` were **deleted** on 2026-08-22. They are not coming back in this form.

`lib/` held `cst-1.6.1-full.jar` built on **May 4**, while the CST source had moved on to
**Jun 2** (`3ae65c8`). The May jar contains `HabitExecutionerCodelet` and nothing else — no
`GroupHabitExecutionerCodelet`, the class WP2's habit fusion is built on. BRG-02 and BRG-03 both
passed against it because a two-codelet mind never touches habit execution. The old recipe here
told you to `cp` that jar, so following this file reproduced the bug.

CST now comes from the **`cst/` submodule at the repo root**, pinned at `3ae65c8`
(`RafaelRagozoni/cst` @ `feat/parallel_Habit_Executioner`) and built from source. Verified
2026-08-22: `./gradlew jar` produces `GroupHabitExecutionerCodelet.class`, with no trace of the
older `ParallelHabitExecutionerCodelet` name.

These three files move into the `agent/` Gradle module, where jeromq and gson are two ordinary
declared dependencies (jeromq is pure Java — no native library, no code generation):

```groovy
implementation 'org.zeromq:jeromq:0.5.4'
implementation 'com.google.code.gson:gson:2.11.0'
// CST from the submodule, not a copied jar
```

The move is deliberately **not done yet** — the agent architecture is still being designed, and
where `BridgeClient` lives depends on it. Until then these do not compile, which is the honest
state. What they do, once the module exists, with CoppeliaSim running and
`python3 ../bridge.py --port 5555 --no-log` up (or `--log run.jsonl.gz --condition X`):

```
BridgeSmokeTest 5555              # BRG-02 acceptance
CstMindBench    5555 400          # BRG-03, publish-subscribe
CstMindBench    5555 400 timer    # BRG-03, negative control
```

## The one thing to carry into WP2

Wire the codelets in **publish-subscribe** mode (`setIsMemoryObserver(true)` plus
`memory.addMemoryObserver(codelet)`), not on their default timers. Measured over 400 cycles:

| Wiring | cycles/s | CST overhead | actions issued | applied | **dropped** |
|---|---|---|---|---|---|
| publish-subscribe | 58.4 | 0.04 ms | 400 | 400 | **0** |
| free-running timers | 39.8 | 5.07 ms | 1964 | 400 | **1563** |

On timers the policy codelet decides at its own rate regardless of the simulator, so **four out of
five decisions never reach the environment** — and nothing errors. The `(s, a, s')` transitions the
credit assignment depends on would be quietly wrong. Publish-subscribe makes one observation cause
exactly one action and exactly one simulation step.

Related: `BridgeClient.call` is `synchronized`. A ZeroMQ REQ socket is strictly one-request-one-reply
and throws if two threads are inside it — which happens easily when codelets run on separate threads.
