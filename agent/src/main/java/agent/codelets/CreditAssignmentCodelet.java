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
    private static final int DRIVE_CHANGE_WINDOW = 1024;

    private record Trace(long lastEndCycle, String context) {
    }

    private final Config cfg;
    private final CreditTable creditTable = new CreditTable();
    private final Map<String, Trace> eligibilityTraces = new LinkedHashMap<>();
    private final Map<Long, double[]> driveChangeByCycle = new LinkedHashMap<>() {
        @Override
        protected boolean removeEldestEntry(Map.Entry<Long, double[]> eldest) {
            return size() > DRIVE_CHANGE_WINDOW;
        }
    };
    private Memory executionMO;
    private Memory driveMO;
    private Memory sensoryMO;
    private Memory creditMO;
    /** Per context (goal, state bin): the running mean change of each drive per step, any habit. */
    private final Map<String, double[]> contextBaselines = new HashMap<>();
    /** Task levels of the last progressWindow cycles of this stage, this episode. */
    private final ArrayDeque<Double> recentTaskLevels = new ArrayDeque<>();
    private double[] previousDriveLevels;
    private double previousYieldFactor;
    private int previousTaskStage;
    private long nextUnreadSeq;

    public CreditAssignmentCodelet(Config cfg) {
        super("CreditAssignment");
        this.cfg = cfg;
    }

    public CreditTable table() {
        return creditTable;
    }

    /**
     * What outlives an episode, for a checkpoint: the table, the per-context baselines and how far
     * ExecutionBuffer was read.
     */
    public JsonObject state() {
        JsonObject baselinesJson = new JsonObject();
        for (Map.Entry<String, double[]> entry : contextBaselines.entrySet()) {
            baselinesJson.add(entry.getKey(), Checkpoint.array(entry.getValue()));
        }
        JsonObject stateJson = new JsonObject();
        stateJson.add("table", creditTable.state());
        stateJson.add("baselines", baselinesJson);
        stateJson.addProperty("readSeq", nextUnreadSeq);
        return stateJson;
    }

    public void restore(JsonObject stateJson) {
        creditTable.restore(stateJson.getAsJsonObject("table"));
        contextBaselines.clear();
        for (Map.Entry<String, JsonElement> entry : stateJson.getAsJsonObject("baselines").entrySet()) {
            contextBaselines.put(entry.getKey(), Checkpoint.doubles(entry.getValue()));
        }
        nextUnreadSeq = stateJson.get("readSeq").getAsLong();
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
        Observation observation = Observation.of(sensoryMO);
        Drives drives = Drives.of(driveMO);
        double[] driveLevels = drives.levels();
        if (observation.episodeStart() || previousDriveLevels == null) {
            eligibilityTraces.clear();
            creditTable.closeExecutions();
            driveChangeByCycle.clear();
            recentTaskLevels.clear();
        } else {
            double[] driveChange = new double[Drives.N];
            for (int drive = 0; drive < Drives.N; drive++) {
                driveChange[drive] = previousDriveLevels[drive] - driveLevels[drive];
            }
            if (drives.effortRestarted()) {
                driveChange[Drives.EFFORT] = 0.0;
            }
            double yieldFactor = drives.curiosityYield();
            if (yieldFactor != previousYieldFactor) {
                // gain * y * (boredom before - boredom now): the yield's own drift is no habit's doing.
                driveChange[Drives.CURIOSITY] = previousYieldFactor > 0.0
                        ? previousDriveLevels[Drives.CURIOSITY] * (yieldFactor / previousYieldFactor)
                            - driveLevels[Drives.CURIOSITY]
                        : 0.0;
            }
            if (drives.taskStage() != previousTaskStage) {
                driveChange[Drives.TASK] = 0.0;
                recentTaskLevels.clear();
            } else if (cfg.progressWindow > 0) {
                boolean taskRetreated = driveLevels[Drives.TASK] > previousDriveLevels[Drives.TASK];
                driveChange[Drives.TASK] = taskRetreated && cfg.progressChargesRetreat
                        ? previousDriveLevels[Drives.TASK] - driveLevels[Drives.TASK]
                        : Math.max(0.0, Collections.min(recentTaskLevels) - driveLevels[Drives.TASK]);
            }
            driveChangeByCycle.put(observation.cycle(), driveChange);
        }
        if (cfg.progressWindow > 0) {
            recentTaskLevels.addLast(driveLevels[Drives.TASK]);
            if (recentTaskLevels.size() > cfg.progressWindow) {
                recentTaskLevels.removeFirst();
            }
        }
        previousDriveLevels = driveLevels;
        previousYieldFactor = drives.curiosityYield();
        previousTaskStage = drives.taskStage();

        ExecutionBuffer executionBuffer = (ExecutionBuffer) executionMO.getI();
        for (ExecutionBuffer.Entry entry : executionBuffer.since(nextUnreadSeq)) {
            if (entry instanceof ExecutionBuffer.Step step && cfg.creditUpdates) {
                credit(step);
            }
        }
        nextUnreadSeq = executionBuffer.nextSeq();
        if (observation.terminal()) {
            eligibilityTraces.clear();
            creditTable.closeExecutions();
        }
        creditMO.setI(new CreditUpdate(creditTable, creditTable.drainDirty(), observation.cycle()));
    }

    private void credit(ExecutionBuffer.Step step) {
        double[] stepChange = new double[Drives.N];
        int cyclesCounted = 0;
        for (long cycle = step.startCycle() + 1; cycle <= step.endCycle(); cycle++) {
            double[] cycleChange = driveChangeByCycle.get(cycle);
            if (cycleChange != null) {
                cyclesCounted++;
                for (int drive = 0; drive < Drives.N; drive++) {
                    stepChange[drive] += cycleChange[drive];
                }
            }
        }
        if (cfg.baselineRate > 0 && cyclesCounted > 0) {
            // What a step in this context changes whatever runs, before this step joins the average.
            // Per step, not per cycle: a drive's change does not grow with the step's length.
            double[] contextBaseline = contextBaselines.computeIfAbsent(step.context(),
                    k -> new double[Drives.N]);
            for (int drive = 0; drive < Drives.N; drive++) {
                double rawChange = stepChange[drive];
                stepChange[drive] = rawChange - contextBaseline[drive];
                contextBaseline[drive] += cfg.baselineRate * (rawChange - contextBaseline[drive]);
            }
        }
        eligibilityTraces.remove(step.habit());
        eligibilityTraces.put(step.habit(), new Trace(step.endCycle(), step.context()));
        Iterator<Map.Entry<String, Trace>> traceIterator = eligibilityTraces.entrySet().iterator();
        while (traceIterator.hasNext()) {
            Map.Entry<String, Trace> traceEntry = traceIterator.next();
            String tracedHabit = traceEntry.getKey();
            Trace trace = traceEntry.getValue();
            double traceWeight = Math.pow(cfg.lambda, step.endCycle() - trace.lastEndCycle());
            if (traceWeight < cfg.traceFloor) {
                traceIterator.remove();
                continue;
            }
            boolean countsAsExecution = tracedHabit.equals(step.habit()) && step.stepIndex() == 0;
            creditTable.add(tracedHabit, trace.context(), stepChange, traceWeight, countsAsExecution);
        }
    }
}
