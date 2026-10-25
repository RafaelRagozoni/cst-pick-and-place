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
import agent.selection.Selectors;
import agent.sim.Observation;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.ObjectInputFilter;
import java.io.ObjectInputStream;
import java.io.ObjectOutputStream;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Random;

/**
 * Behavior Generator (cap4 4.3.5): scores every habit in the HabitPool and decides what runs.
 *
 * <p>Score, eq. (4.1): E(h) = sum over drives of D_d * c_d(h | g, s), the credit under the current
 * goal and state, or the habit's total credit where it has no record under that pair. Which habit
 * the scores lead to is the {@link Selector} named by {@code Config.selection}: greedy as cap4 writes it,
 * uniform random in C6, or UCB or Thompson sampling. Each candidate also carries how many executions
 * its score rests on here and the spread of one of its executions' score, which those two need: the
 * repertoire's reference spread, shrunk toward the habit's own as its executions accumulate.
 *
 * <p>Inputs: HabitPoolMC, GoalMO, SensoryMO, DriveMO, PlanTrackerMO. Output: PlanMO.
 */
public final class BehaviorGeneratorCodelet extends AgentCodelet {

    private final Config cfg;
    private Random rng;
    private final Selector selector;
    private double referenceSpread;
    private MemoryContainer habitPool;
    private Memory goalMO;
    private Memory sensoryMO;
    private Memory driveMO;
    private Memory trackerMO;
    private Memory planMO;
    private long planSerial;

    public BehaviorGeneratorCodelet(Config cfg, long seed) {
        super("BehaviorGenerator");
        this.cfg = cfg;
        this.rng = new Random(seed);
        this.selector = Selectors.byName(cfg.selection);
    }

    @Override
    public void accessMemoryObjects() {
        if (habitPool == null) {
            habitPool = (MemoryContainer) in("HabitPoolMC");
            goalMO = in("GoalMO");
            sensoryMO = in("SensoryMO");
            driveMO = in("DriveMO");
            trackerMO = in("PlanTrackerMO");
            planMO = out("PlanMO");
        }
    }

    @Override
    public void proc() {
        Observation observation = Observation.of(sensoryMO);
        if (observation.terminal()) {
            return;
        }
        TrackerState trackerState = (TrackerState) trackerMO.getI();
        boolean planRunning = trackerState != null && trackerState.running();
        Goal goal = Goal.of(goalMO);
        String creditContext = CreditTable.context(goal.name(), Characterization.key(observation));
        double[] driveLevels = Drives.of(driveMO).levels();
        List<Idea> habits = new ArrayList<>();
        List<CreditSnapshot> habitCredits = new ArrayList<>();
        for (Memory poolMember : habitPool.getAllMemories()) {
            Idea habit = (Idea) poolMember.getI();
            habits.add(habit);
            habitCredits.add(HabitIdeas.credit(habit));
        }
        referenceSpread = CreditSnapshot.reference(habitCredits, driveLevels);
        List<Candidate> candidates = new ArrayList<>();
        Candidate runningCandidate = null;
        for (int i = 0; i < habits.size(); i++) {
            Idea habit = habits.get(i);
            CreditSnapshot habitCredit = habitCredits.get(i);
            Candidate candidate = new Candidate(habit, score(habitCredit, creditContext, driveLevels),
                    habitCredit.count(creditContext),
                    habitCredit.spread(referenceSpread, driveLevels, cfg.spreadPriorWeight));
            if (planRunning && HabitIdeas.id(habit).equals(trackerState.habit())) {
                runningCandidate = candidate;
            }
            candidates.add(candidate);
        }
        Candidate chosen = selector.select(candidates, runningCandidate, rng);
        if (chosen != null) {
            planMO.setI(new Plan(++planSerial, chosen.habit(), goal.name(), goal.id(), creditContext,
                    chosen.score()));
        }
    }

    /**
     * What outlives an episode, for a checkpoint: the plan numbering and the random generator
     * mid-sequence (Java serialization is the only public way to its state). Selectors keep no state
     * across episodes: Thompson's draws restart with each decision taken while nothing runs.
     */
    public JsonObject state() {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ObjectOutputStream out = new ObjectOutputStream(bytes)) {
            out.writeObject(rng);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        JsonObject stateJson = new JsonObject();
        stateJson.addProperty("serial", planSerial);
        stateJson.addProperty("rng", Base64.getEncoder().encodeToString(bytes.toByteArray()));
        return stateJson;
    }

    public void restore(JsonObject stateJson) {
        planSerial = stateJson.get("serial").getAsLong();
        byte[] bytes = Base64.getDecoder().decode(stateJson.get("rng").getAsString());
        try (ObjectInputStream in = new ObjectInputStream(new ByteArrayInputStream(bytes))) {
            in.setObjectInputFilter(ObjectInputFilter.Config.createFilter("java.util.Random;!*"));
            rng = (Random) in.readObject();
        } catch (IOException | ClassNotFoundException e) {
            throw new IllegalArgumentException("unreadable random generator state in checkpoint", e);
        }
    }

    /**
     * The reference spread the last selection used (CreditSnapshot#reference), what the run log
     * records: 0 means no habit has a finished execution, or every habit's results are the same.
     */
    public double spread() {
        return referenceSpread;
    }

    /** E(h), eq. (4.1): each drive's level times the habit's credit for that drive, summed. */
    double score(CreditSnapshot habitCredit, String creditContext, double[] driveLevels) {
        double[] creditByDrive = habitCredit.value(creditContext, cfg.creditRead);
        double score = 0.0;
        for (int drive = 0; drive < Drives.N; drive++) {
            score += driveLevels[drive] * creditByDrive[drive];
        }
        return score;
    }
}
