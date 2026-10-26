package agent.bench;

import agent.sim.BridgeClient;
import br.unicamp.cst.core.entities.Codelet;
import br.unicamp.cst.core.entities.MemoryObject;
import br.unicamp.cst.core.entities.Mind;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.Random;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * BRG-03: measure the control loop with a real CST mind in it, not just a Java client.
 *
 * <p>Two codelets in <b>publish-subscribe mode</b>, which is what makes an asynchronous codelet
 * architecture produce a synchronous cycle:
 *
 * <pre>
 *   PolicyCodelet  observes OBSERVATION -&gt; writes ACTION
 *   SimCodelet     observes ACTION      -&gt; steps the simulator once, writes OBSERVATION
 * </pre>
 *
 * Each observation causes exactly one action, which causes exactly one simulation step. If the
 * codelets ran on their default timers instead, the sim would step without a fresh action, or an
 * action would be overwritten before it was applied -- and the (s, a, s') transitions the credit
 * assignment depends on would be silently wrong. That is the finding this benchmark exists to make
 * concrete, as much as the timing number.
 *
 * <p>The bridge socket is owned by exactly one codelet on purpose: a ZeroMQ REQ socket is strictly
 * request-reply and is not safe to share across threads.
 *
 * <pre>
 *   ./gradlew liveRun -Pmain=agent.bench.CstMindBench -PagentArgs="5555 400 [timer]"
 * </pre>
 */
public class CstMindBench {

    static final AtomicInteger steps = new AtomicInteger();
    static final AtomicLong nanosInBridge = new AtomicLong();
    static final AtomicInteger staleActions = new AtomicInteger();
    /** Actions the policy issued that the simulator never applied -- the real timer-mode failure. */
    static final AtomicInteger droppedActions = new AtomicInteger();
    static final AtomicInteger issued = new AtomicInteger();

    /** Owns the bridge. Observes ACTION, applies it, advances the simulator exactly once. */
    static class SimCodelet extends Codelet {
        private final BridgeClient bridge;
        private MemoryObject actionMO;
        private MemoryObject obsMO;
        private long lastActionSerial = -1;

        SimCodelet(BridgeClient bridge) {
            this.bridge = bridge;
        }

        @Override
        public void accessMemoryObjects() {
            actionMO = (MemoryObject) getInput("ACTION");
            obsMO = (MemoryObject) getOutput("OBSERVATION");
        }

        @Override
        public void calculateActivation() {
        }

        @Override
        public void proc() {
            Object info = actionMO.getI();
            if (!(info instanceof Action)) {
                return;
            }
            Action a = (Action) info;
            if (a.serial == lastActionSerial) {
                staleActions.incrementAndGet();      // same action applied twice
            } else if (lastActionSerial >= 0 && a.serial > lastActionSerial + 1) {
                // The policy issued actions the simulator never saw. This is the failure mode that
                // free-running timers actually produce, and it silently corrupts (s, a, s').
                droppedActions.addAndGet((int) (a.serial - lastActionSerial - 1));
            }
            lastActionSerial = a.serial;

            long t = System.nanoTime();
            JsonObject reply = bridge.step(a.records);
            nanosInBridge.addAndGet(System.nanoTime() - t);
            steps.incrementAndGet();
            obsMO.setI(reply);
        }
    }

    /** Observes OBSERVATION, picks a primitive, writes ACTION. Stands in for the habit machinery. */
    static class PolicyCodelet extends Codelet {
        private final Random rng = new Random(7);
        private final int maxSteps;
        private MemoryObject obsMO;
        private MemoryObject actionMO;
        private long serial = 0;

        PolicyCodelet(int maxSteps) {
            this.maxSteps = maxSteps;
        }

        @Override
        public void accessMemoryObjects() {
            obsMO = (MemoryObject) getInput("OBSERVATION");
            actionMO = (MemoryObject) getOutput("ACTION");
        }

        @Override
        public void calculateActivation() {
        }

        @Override
        public void proc() {
            if (steps.get() >= maxSteps) {
                return;
            }
            JsonArray recs = new JsonArray();
            int k = rng.nextInt(14);
            if (k < 12) {
                recs.add(BridgeClient.move(k / 2, (k % 2 == 0 ? 1 : -1) * Math.toRadians(1.0), 0.4));
            } else {
                recs.add(BridgeClient.grab(k == 12));
            }
            issued.incrementAndGet();
            actionMO.setI(new Action(serial++, recs));
        }
    }

    static class Action {
        final long serial;
        final JsonArray records;

        Action(long serial, JsonArray records) {
            this.serial = serial;
            this.records = records;
        }
    }

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 5555;
        int maxSteps = args.length > 1 ? Integer.parseInt(args[1]) : 400;
        // "timer" runs the codelets on their own timers instead of publish-subscribe -- the
        // negative control that shows why the synchronous wiring is not optional.
        boolean timerMode = args.length > 2 && args[2].equals("timer");

        BridgeClient bridge = new BridgeClient("127.0.0.1", port, 30000);
        JsonObject reset = bridge.reset(1, 0);
        System.out.println("  reset ok, driving " + maxSteps + " cycles through a CST mind");

        Mind mind = new Mind();
        MemoryObject obsMO = mind.createMemoryObject("OBSERVATION");
        MemoryObject actionMO = mind.createMemoryObject("ACTION");

        SimCodelet sim = new SimCodelet(bridge);
        sim.addInput(actionMO);
        sim.addOutput(obsMO);
        PolicyCodelet pol = new PolicyCodelet(maxSteps);
        pol.addInput(obsMO);
        pol.addOutput(actionMO);

        mind.insertCodelet(sim);
        mind.insertCodelet(pol);
        if (timerMode) {
            System.out.println("  MODE: free-running timers (negative control)");
            sim.setTimeStep(5);
            pol.setTimeStep(5);
        } else {
            System.out.println("  MODE: publish-subscribe (one observation -> one action -> one step)");
            sim.setIsMemoryObserver(true);
            actionMO.addMemoryObserver(sim);
            pol.setIsMemoryObserver(true);
            obsMO.addMemoryObserver(pol);
        }

        mind.start();
        long t0 = System.nanoTime();
        obsMO.setI(reset);                     // kick the loop off

        while (steps.get() < maxSteps && (System.nanoTime() - t0) < 120e9) {
            Thread.sleep(20);
        }
        double wall = (System.nanoTime() - t0) / 1e9;
        int n = steps.get();
        mind.shutDown();
        // Let any codelet call already on the wire finish before main touches the socket. Without
        // this, main and a codelet thread can both be inside the REQ socket and jeromq throws.
        Thread.sleep(500);

        double perCycle = wall / n * 1000.0;
        double bridgeMs = nanosInBridge.get() / 1e6 / n;
        System.out.printf("  %d cycles in %.2f s -> %.1f cycles/s (%.2f ms/cycle)%n",
                n, wall, n / wall, perCycle);
        System.out.printf("  of which bridge round trip: %.2f ms; CST overhead: %.2f ms/cycle%n",
                bridgeMs, perCycle - bridgeMs);
        System.out.printf("  actions issued %d, applied %d, dropped %d, re-applied %d%n",
                issued.get(), n, droppedActions.get(), staleActions.get());

        boolean ok = timerMode || (n >= maxSteps && staleActions.get() == 0
                && droppedActions.get() == 0);
        System.out.println();
        if (timerMode) {
            System.out.printf("  CONTROL: %d actions never reached the simulator, %d applied twice%n",
                    droppedActions.get(), staleActions.get());
        } else {
            System.out.println("BRG-03 CST-IN-THE-LOOP: " + (ok ? "PASS" : "FAIL"));
        }
        bridge.shutdown();
        bridge.close();
        System.exit(ok ? 0 : 1);
    }
}
