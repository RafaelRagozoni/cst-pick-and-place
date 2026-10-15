package agent.codelets;

import agent.Config;
import agent.credit.CreditTable;
import agent.habit.HabitIdeas;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.TrackerState;
import agent.motivation.Characterization;
import agent.motivation.Drives;
import agent.sim.Observation;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.representation.idea.Idea;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * Behavior Generator (cap4 4.3.5): scores every habit in the HabitPool and decides what runs.
 *
 * <p>Score, eq. (4.1): E(h) = sum over drives of D_d * c_d(h | g, s), the credit under the current
 * goal and state, or the habit's total credit where it has no record under that pair. The plan in
 * execution is kept unless another habit now scores strictly higher; when nothing is running the best
 * habit starts. Ties are broken uniformly at random -- which is all the exploration there is at
 * first, when every credit is zero.
 *
 * <p>C6 replaces all of this with a uniform-random choice each time the plan in execution ends.
 *
 * <p>Inputs: HabitPoolMC, GoalMO, SensoryMO, DriveMO, PlanTrackerMO. Output: PlanMO.
 */
public final class BehaviorGeneratorCodelet extends AgentCodelet {

    private static final double EPS = 1e-12;

    private final Config cfg;
    private final Random rng;
    private MemoryContainer pool;
    private Memory goalMO;
    private Memory sensoryMO;
    private Memory driveMO;
    private Memory trackerMO;
    private Memory planMO;
    private long serial;

    public BehaviorGeneratorCodelet(Config cfg, long seed) {
        super("BehaviorGenerator");
        this.cfg = cfg;
        this.rng = new Random(seed);
    }

    @Override
    public void accessMemoryObjects() {
        if (pool == null) {
            pool = (MemoryContainer) in("HabitPoolMC");
            goalMO = in("GoalMO");
            sensoryMO = in("SensoryMO");
            driveMO = in("DriveMO");
            trackerMO = in("PlanTrackerMO");
            planMO = out("PlanMO");
        }
    }

    @Override
    public void proc() {
        Observation o = Observation.of(sensoryMO);
        if (o.terminal()) {
            return;
        }
        TrackerState ts = (TrackerState) trackerMO.getI();
        boolean running = ts != null && ts.running();
        Goal goal = Goal.of(goalMO);
        String context = CreditTable.context(goal.name(), Characterization.key(o));
        List<Memory> members = pool.getAllMemories();

        if (cfg.randomSelection) {
            if (!running) {
                Idea pick = (Idea) members.get(rng.nextInt(members.size())).getI();
                planMO.setI(new Plan(++serial, pick, goal.name(), goal.id(), context, 0.0));
            }
            return;
        }

        double[] levels = Drives.of(driveMO).levels();
        double best = Double.NEGATIVE_INFINITY;
        double current = Double.NEGATIVE_INFINITY;
        List<Idea> ties = new ArrayList<>();
        for (Memory m : members) {
            Idea h = (Idea) m.getI();
            double e = score(h, context, levels);
            if (running && HabitIdeas.id(h).equals(ts.habit())) {
                current = e;
            }
            if (e > best + EPS) {
                best = e;
                ties.clear();
                ties.add(h);
            } else if (Math.abs(e - best) <= EPS) {
                ties.add(h);
            }
        }
        if (running && best <= current + EPS) {
            return;                                         // keep the plan in execution
        }
        Idea pick = ties.get(rng.nextInt(ties.size()));
        planMO.setI(new Plan(++serial, pick, goal.name(), goal.id(), context, best));
    }

    double score(Idea habit, String context, double[] levels) {
        double[] c = HabitIdeas.credit(habit).value(context, cfg.creditRead);
        double e = 0.0;
        for (int d = 0; d < Drives.N; d++) {
            e += levels[d] * c[d];
        }
        return e;
    }
}
