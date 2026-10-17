package agent.codelets;

import agent.Checkpoint;
import agent.Config;
import agent.credit.CreditTable;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.motivation.Drives;
import agent.sim.Observation;
import br.unicamp.cst.core.entities.Memory;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayDeque;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Credit Assignment (cap4 4.3.4): relates the steps in ExecutionBuffer to the drive changes they
 * caused, and accumulates per-drive credit in CreditMO.
 *
 * <p>Every cycle it records the change in each drive, lowered = positive, as a vector that is never
 * collapsed. Two kinds of change are not the habit's doing and are zeroed: Effort restarting because
 * a new goal was set, and Task jumping because the inferred stage -- its target -- changed. A third
 * is taken out: Curiosity's yield drifting by itself (CuriosityYield) would credit every habit for
 * the time it ran, so Curiosity's change is measured at this cycle's yield -- the previous level
 * rescaled to it -- and only boredom's change counts. Task's
 * change counts only as progress beyond the lowest Task level of the last {@code progressWindow}
 * cycles of the stage: returning to where the arm had been earns nothing and moving away is not
 * charged, so going back and forth pays nothing. The levels come from DriveMO, kept here; reading
 * SensoryBuffer instead would recompute the same distance with a second copy of the formula. For each
 * newly executed step it sums those changes over the step's cycles, subtracts what a step in its
 * context changes whatever runs there (a running mean per context, {@code baselineRate}; the
 * advantage of policy-gradient methods), and distributes the rest through
 * an eligibility trace: the habit that ran gets weight 1, every habit that ran before gets
 * lambda^(cycles since it last ran), and traces under {@code traceFloor} are dropped. Each eligible
 * habit's credit goes to the (goal, state) it was selected under. No credit crosses an episode
 * boundary.
 *
 * <p>Inputs: ExecutionBuffer, DriveMO, SensoryMO (cycle and episode boundaries). SensoryBuffer is
 * an input in cap4's figure and is wired here, but nothing reads it yet: changes in perception enter
 * only through the drives. Output: CreditMO.
 */
public final class CreditAssignmentCodelet extends AgentCodelet {

    /** Cycles of per-cycle drive changes kept; a step longer than this is credited partially. */
    private static final int DELTA_WINDOW = 1024;

    private record Trace(long anchor, String context) {
    }

    private final Config cfg;
    private final CreditTable table = new CreditTable();
    private final Map<String, Trace> traces = new LinkedHashMap<>();
    private final Map<Long, double[]> deltas = new LinkedHashMap<>() {
        @Override
        protected boolean removeEldestEntry(Map.Entry<Long, double[]> eldest) {
            return size() > DELTA_WINDOW;
        }
    };
    private Memory executionMO;
    private Memory driveMO;
    private Memory sensoryMO;
    private Memory creditMO;
    /** Per context (goal, state bin): the running mean change of each drive per step, any habit. */
    private final Map<String, double[]> baselines = new HashMap<>();
    /** Task levels of the last progressWindow cycles of this stage, this episode. */
    private final ArrayDeque<Double> recentTask = new ArrayDeque<>();
    private double[] prev;
    private double prevYield;
    private int prevStage;
    private long readSeq;

    public CreditAssignmentCodelet(Config cfg) {
        super("CreditAssignment");
        this.cfg = cfg;
    }

    public CreditTable table() {
        return table;
    }

    /**
     * What outlives an episode, for a checkpoint: the table, the per-context baselines and how far
     * ExecutionBuffer was read.
     */
    public JsonObject state() {
        JsonObject b = new JsonObject();
        for (Map.Entry<String, double[]> e : baselines.entrySet()) {
            b.add(e.getKey(), Checkpoint.array(e.getValue()));
        }
        JsonObject s = new JsonObject();
        s.add("table", table.state());
        s.add("baselines", b);
        s.addProperty("readSeq", readSeq);
        return s;
    }

    public void restore(JsonObject s) {
        table.restore(s.getAsJsonObject("table"));
        baselines.clear();
        for (Map.Entry<String, JsonElement> e : s.getAsJsonObject("baselines").entrySet()) {
            baselines.put(e.getKey(), Checkpoint.doubles(e.getValue()));
        }
        readSeq = s.get("readSeq").getAsLong();
    }

    @Override
    public void accessMemoryObjects() {
        if (executionMO == null) {
            executionMO = in("ExecutionBuffer");
            driveMO = in("DriveMO");
            sensoryMO = in("SensoryMO");
            creditMO = out("CreditMO");
        }
    }

    @Override
    public void proc() {
        Observation o = Observation.of(sensoryMO);
        Drives drives = Drives.of(driveMO);
        double[] levels = drives.levels();
        if (o.episodeStart() || prev == null) {
            traces.clear();
            table.closeExecutions();
            deltas.clear();
            recentTask.clear();
        } else {
            double[] delta = new double[Drives.N];
            for (int d = 0; d < Drives.N; d++) {
                delta[d] = prev[d] - levels[d];
            }
            if (drives.effortRestarted()) {
                delta[Drives.EFFORT] = 0.0;
            }
            double y = drives.curiosityYield();
            if (y != prevYield) {
                // gain * y * (boredom before - boredom now): the yield's own drift is no habit's doing.
                delta[Drives.CURIOSITY] = prevYield > 0.0
                        ? prev[Drives.CURIOSITY] * (y / prevYield) - levels[Drives.CURIOSITY] : 0.0;
            }
            if (drives.taskStage() != prevStage) {
                delta[Drives.TASK] = 0.0;
                recentTask.clear();
            } else if (cfg.progressWindow > 0) {
                boolean retreat = levels[Drives.TASK] > prev[Drives.TASK];
                delta[Drives.TASK] = retreat && cfg.progressChargesRetreat
                        ? prev[Drives.TASK] - levels[Drives.TASK]
                        : Math.max(0.0, Collections.min(recentTask) - levels[Drives.TASK]);
            }
            deltas.put(o.cycle(), delta);
        }
        if (cfg.progressWindow > 0) {
            recentTask.addLast(levels[Drives.TASK]);
            if (recentTask.size() > cfg.progressWindow) {
                recentTask.removeFirst();
            }
        }
        prev = levels;
        prevYield = drives.curiosityYield();
        prevStage = drives.taskStage();

        ExecutionBuffer buffer = (ExecutionBuffer) executionMO.getI();
        for (ExecutionBuffer.Entry e : buffer.since(readSeq)) {
            if (e instanceof ExecutionBuffer.Step s && cfg.creditUpdates) {
                credit(s);
            }
        }
        readSeq = buffer.nextSeq();
        if (o.terminal()) {
            traces.clear();
            table.closeExecutions();
        }
        creditMO.setI(new CreditUpdate(table, table.drainDirty(), o.cycle()));
    }

    private void credit(ExecutionBuffer.Step s) {
        double[] change = new double[Drives.N];
        int cycles = 0;
        for (long c = s.startCycle() + 1; c <= s.endCycle(); c++) {
            double[] d = deltas.get(c);
            if (d != null) {
                cycles++;
                for (int i = 0; i < Drives.N; i++) {
                    change[i] += d[i];
                }
            }
        }
        if (cfg.baselineRate > 0 && cycles > 0) {
            // What a step in this context changes whatever runs, before this step joins the average.
            // Per step, not per cycle: a drive's change does not grow with the step's length.
            double[] b = baselines.computeIfAbsent(s.context(), k -> new double[Drives.N]);
            for (int i = 0; i < Drives.N; i++) {
                double x = change[i];
                change[i] = x - b[i];
                b[i] += cfg.baselineRate * (x - b[i]);
            }
        }
        traces.remove(s.habit());
        traces.put(s.habit(), new Trace(s.endCycle(), s.context()));
        Iterator<Map.Entry<String, Trace>> it = traces.entrySet().iterator();
        while (it.hasNext()) {
            Map.Entry<String, Trace> t = it.next();
            double w = Math.pow(cfg.lambda, s.endCycle() - t.getValue().anchor());
            if (w < cfg.traceFloor) {
                it.remove();
                continue;
            }
            boolean execution = t.getKey().equals(s.habit()) && s.stepIndex() == 0;
            table.add(t.getKey(), t.getValue().context(), change, w, execution);
        }
    }
}
