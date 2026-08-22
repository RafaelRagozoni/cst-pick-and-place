# Java side of the simulation bridge (BRG-02 / BRG-03)

`BridgeClient.java` is the class the CST application will use. The other two are tests.

| File | What it is |
|---|---|
| `BridgeClient.java` | The client. One request per control cycle: command records in, one simulation step, full observation back |
| `BridgeSmokeTest.java` | BRG-02 acceptance — drives the arm and gripper over the wire, no task logic |
| `CstMindBench.java` | BRG-03 — a minimal **CST mind** (two codelets) driving the simulator, and the timing |

## Build and run

The jars in `lib/` are fetched, not checked in (see the repo `.gitignore`):

```bash
mkdir -p lib && cd lib
curl -LO https://repo1.maven.org/maven2/org/zeromq/jeromq/0.5.4/jeromq-0.5.4.jar
curl -LO https://repo1.maven.org/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar
cp ~/Mestrado/Projetos/cst/build/libs/cst-1.6.1-full.jar .        # only for CstMindBench
cd ..

javac -cp "lib/*" -d out *.java

# with CoppeliaSim running and `python3 ../bridge.py --port 5555` up:
java -cp "lib/*:out" BridgeSmokeTest 5555
java -cp "lib/*:out" CstMindBench   5555 400          # publish-subscribe
java -cp "lib/*:out" CstMindBench   5555 400 timer    # negative control
```

In a real Gradle build these are two ordinary dependencies — jeromq is pure Java, so there is no
native library and no code generation:

```groovy
implementation 'org.zeromq:jeromq:0.5.4'
implementation 'com.google.code.gson:gson:2.11.0'
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
