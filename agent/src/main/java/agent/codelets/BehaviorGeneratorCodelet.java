package agent.codelets;

import agent.Config;
import agent.credit.CreditSnapshot;
import agent.credit.CreditTable;
import agent.habit.HabitIdeas;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.TrackerState;
import agent.motivation.Characterization;
import agent.motivation.Drives;
import agent.selection.Selector;
import agent.selection.Selector.Candidate;
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
 * goal and state, or the habit's total credit where it has no record under that pair. Which habit
 * the scores lead to is the {@link Selector} in {@code Config.selector}: greedy as cap4 writes it,
 * uniform random in C6, or UCB or Thompson sampling. Each candidate also carries how many executions
 * its score rests on and the pooled spread of one execution's score, which those two need.
 *
 * <p>Inputs: HabitPoolMC, GoalMO, SensoryMO, DriveMO, PlanTrackerMO. Output: PlanMO.
 */
public final class BehaviorGeneratorCodelet extends AgentCodelet {

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
        double[] levels = Drives.of(driveMO).levels();
        List<Idea> habits = new ArrayList<>();
        List<CreditSnapshot> credit = new ArrayList<>();
        for (Memory m : pool.getAllMemories()) {
            Idea h = (Idea) m.getI();
            habits.add(h);
            credit.add(HabitIdeas.credit(h));
        }
        double spread = CreditSnapshot.spread(credit, levels);
        List<Candidate> candidates = new ArrayList<>();
        Candidate current = null;
        for (int i = 0; i < habits.size(); i++) {
            Idea h = habits.get(i);
            Candidate c = new Candidate(h, score(credit.get(i), context, levels),
                    credit.get(i).count(context), spread);
            if (running && HabitIdeas.id(h).equals(ts.habit())) {
                current = c;
            }
            candidates.add(c);
        }
        Candidate pick = cfg.selector.select(candidates, current, rng);
        if (pick != null) {
            planMO.setI(new Plan(++serial, pick.habit(), goal.name(), goal.id(), context,
                    pick.score()));
        }
    }

    double score(CreditSnapshot credit, String context, double[] levels) {
        double[] c = credit.value(context, cfg.creditRead);
        double e = 0.0;
        for (int d = 0; d < Drives.N; d++) {
            e += levels[d] * c[d];
        }
        return e;
    }
}
