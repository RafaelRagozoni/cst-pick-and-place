package agent.codelets;

import agent.Config;
import agent.credit.CreditTable;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.motivation.Drives;
import agent.sim.Observation;
import br.unicamp.cst.core.entities.Memory;

import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Credit Assignment (cap4 4.3.4): relates the steps in ExecutionBuffer to the drive changes they
 * caused, and accumulates per-drive credit in CreditMO.
 *
 * <p>Every cycle it records the change in each drive, lowered = positive, as a vector that is never
 * collapsed. Two kinds of change are not the habit's doing and are zeroed: Effort restarting because
 * a new goal was set, and Task jumping because the inferred stage -- its target -- changed. For each
 * newly executed step it sums those changes over the step's cycles and distributes the sum through
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
    private double[] prev;
    private int prevStage;
    private long readSeq;

    public CreditAssignmentCodelet(Config cfg) {
        super("CreditAssignment");
        this.cfg = cfg;
    }

    public CreditTable table() {
        return table;
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
            deltas.clear();
        } else {
            double[] delta = new double[Drives.N];
            for (int d = 0; d < Drives.N; d++) {
                delta[d] = prev[d] - levels[d];
            }
            if (drives.effortRestarted()) {
                delta[Drives.EFFORT] = 0.0;
            }
            if (drives.taskStage() != prevStage) {
                delta[Drives.TASK] = 0.0;
            }
            deltas.put(o.cycle(), delta);
        }
        prev = levels;
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
        }
        creditMO.setI(new CreditUpdate(table, table.drainDirty(), o.cycle()));
    }

    private void credit(ExecutionBuffer.Step s) {
        double[] change = new double[Drives.N];
        for (long c = s.startCycle() + 1; c <= s.endCycle(); c++) {
            double[] d = deltas.get(c);
            if (d != null) {
                for (int i = 0; i < Drives.N; i++) {
                    change[i] += d[i];
                }
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
