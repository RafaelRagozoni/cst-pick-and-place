package agent;

import agent.codelets.BehaviorGeneratorCodelet;
import agent.codelets.CreditAssignmentCodelet;
import agent.codelets.GoalGeneratorCodelet;
import agent.codelets.HabitLearnerCodelet;
import agent.codelets.PlanTrackerCodelet;
import agent.codelets.SensoryCodelet;
import agent.credit.CreditSnapshot;
import agent.credit.CreditTable;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.SensoryBuffer;
import agent.memory.TrackerState;
import agent.motivation.Characterization;
import agent.motivation.Drives;
import agent.sim.Environment;
import agent.sim.Observation;
import agent.sim.SimLink;
import agent.task.Carry;
import agent.task.TaskStages;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.core.entities.MemoryObject;
import br.unicamp.cst.core.entities.Mind;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Each codelet driven alone, through its memories, the way AgentMind drives it. */
class CodeletsTest {

    private final Mind mind = new Mind();
    private final MemoryObject sensoryMO = mind.createMemoryObject("SensoryMO");
    private final MemoryObject driveMO = mind.createMemoryObject("DriveMO");
    private final MemoryObject goalMO = mind.createMemoryObject("GoalMO");
    private final MemoryObject planMO = mind.createMemoryObject("PlanMO");
    private final MemoryObject trackerMO = mind.createMemoryObject("PlanTrackerMO");
    private final MemoryObject executionMO =
            mind.createMemoryObject("ExecutionBuffer", new ExecutionBuffer(100));
    private final MemoryObject creditMO = mind.createMemoryObject("CreditMO");
    private final MemoryObject sensoryBufferMO = mind.createMemoryObject("SensoryBuffer");

    /** Observation 0 of the expert trajectory with the arm at q, gripper at its recorded width. */
    private static Idea at(long cycle, double[] q, boolean terminal) {
        JsonObject o = Traj.copy(0);
        JsonArray joints = o.getAsJsonObject("innerSense").getAsJsonArray("joints");
        for (int j = 0; j < 6; j++) {
            joints.get(j).getAsJsonObject().addProperty("pos", q[j]);
        }
        return Observation.toIdea(o, cycle, 0, cycle == 0, terminal);
    }

    private void drives(long cycle, double c, double t, double s, double e, int stage,
                        boolean restarted) {
        double[] v = {c, t, s, e};
        driveMO.setI(Drives.toIdea(cycle, v, v, stage, restarted, 0.0));
    }

    /** Curiosity as boredom * yield (gain 1), Task as given, the rest 0. */
    private void curiosity(long cycle, double boredom, double yield, double task) {
        double[] v = {boredom * yield, task, 0, 0};
        driveMO.setI(Drives.toIdea(cycle, v, v, 0, false, 0.0, boredom, yield));
    }

    private void goal(long id, String source, String name, int stage) {
        goalMO.setI(Goal.toIdea(id, source, name, stage, 0, new double[0]));
    }

    private ExecutionBuffer buffer() {
        return (ExecutionBuffer) executionMO.getI();
    }

    private List<ExecutionBuffer.Step> steps() {
        List<ExecutionBuffer.Step> out = new ArrayList<>();
        for (ExecutionBuffer.Entry e : buffer().since(0)) {
            if (e instanceof ExecutionBuffer.Step s) {
                out.add(s);
            }
        }
        return out;
    }

    // --- PlanTracker ------------------------------------------------------------------
    private PlanTrackerCodelet tracker() {
        PlanTrackerCodelet t = new PlanTrackerCodelet(new Config());
        t.addInput(sensoryMO);
        t.addInput(goalMO);
        t.addInput(driveMO);
        t.addInput(planMO);
        t.addOutput(trackerMO);
        t.addOutput(executionMO);
        return t;
    }

    private static Idea twoStepHabit() {
        double deg = Math.toRadians(1.0);
        return HabitIdeas.create("two", HabitIdeas.MACRO, List.of(), List.of(
                new Command(Command.MOVE, 0, deg, 0.4, 20, 0),
                new Command(Command.MOVE, 1, -deg, 0.4, 20, 1)));
    }

    @Test
    void trackerRunsStepsInOrderAndRecordsThem() {
        PlanTrackerCodelet t = tracker();
        double deg = Math.toRadians(1.0);
        double[] q = Traj.obs(0).q().clone();
        goal(1, Goal.TASK, "transport", 2);           // a goal that will not be met here
        drives(0, 0, 0, 0, 0, 2, false);

        sensoryMO.setI(at(0, q, false));
        t.notifyCodelet();                             // track: nothing loaded
        assertFalse(((TrackerState) trackerMO.getI()).running());
        planMO.setI(new Plan(1, twoStepHabit(), "transport", 1, "ctx", 0.0));
        t.notifyCodelet();                             // load
        TrackerState s = (TrackerState) trackerMO.getI();
        assertTrue(s.running());
        assertEquals(0, s.stepIndex());
        assertEquals(deg, s.commands().get(0).angle(), 1e-12);

        q[0] += deg;                                   // step 0 arrives
        sensoryMO.setI(at(1, q, false));
        t.notifyCodelet();
        t.notifyCodelet();
        s = (TrackerState) trackerMO.getI();
        assertEquals(1, s.stepIndex());
        assertEquals(1, s.commands().get(0).joint());

        q[1] -= deg;                                   // step 1 arrives: the plan ends
        sensoryMO.setI(at(2, q, false));
        t.notifyCodelet();
        assertFalse(((TrackerState) trackerMO.getI()).running());

        List<ExecutionBuffer.Step> st = steps();
        assertEquals(2, st.size());
        assertEquals(0, st.get(0).stepIndex());
        assertEquals(0, st.get(0).startCycle());
        assertEquals(1, st.get(0).endCycle());
        assertEquals(1, st.get(1).startCycle());
        assertEquals(2, st.get(1).endCycle());
        assertEquals("done", st.get(1).outcome());
        assertEquals("ctx", st.get(1).context());
    }

    @Test
    void trackerRecordsAPreemptedStep() {
        PlanTrackerCodelet t = tracker();
        double[] q = Traj.obs(0).q().clone();
        goal(1, Goal.TASK, "transport", 2);
        drives(0, 0, 0, 0, 0, 2, false);
        sensoryMO.setI(at(0, q, false));
        t.notifyCodelet();
        planMO.setI(new Plan(1, twoStepHabit(), "transport", 1, "ctx", 0.0));
        t.notifyCodelet();
        q[0] += Math.toRadians(0.5);                   // halfway
        sensoryMO.setI(at(1, q, false));
        t.notifyCodelet();
        planMO.setI(new Plan(2, twoStepHabit(), "transport", 1, "ctx", 0.0));
        t.notifyCodelet();
        assertEquals(PlanTrackerCodelet.PREEMPTED, steps().get(0).outcome());
        assertEquals(2, ((TrackerState) trackerMO.getI()).planSerial());
    }

    @Test
    void trackerClosesThePlanAndMarksTheGoalWhenItIsMet() {
        PlanTrackerCodelet t = tracker();
        // Observation 400 of the expert trajectory has the cube grasped: a "grasp" goal is met.
        int i = 400;
        assertTrue(TaskStages.grasped(Traj.obs(i)));
        goal(7, Goal.TASK, "grasp", 1);
        drives(i, 0, 0, 0, 0, 2, false);
        sensoryMO.setI(Observation.toIdea(Traj.json().get(i - 1), i - 1, 0, false, false));
        t.notifyCodelet();
        planMO.setI(new Plan(1, twoStepHabit(), "grasp", 7, "ctx", 0.0));
        t.notifyCodelet();
        sensoryMO.setI(Observation.toIdea(Traj.json().get(i), i, 0, false, false));
        t.notifyCodelet();
        assertFalse(((TrackerState) trackerMO.getI()).running());
        List<ExecutionBuffer.Entry> all = buffer().since(0);
        assertEquals(PlanTrackerCodelet.CLOSED, ((ExecutionBuffer.Step) all.get(0)).outcome());
        ExecutionBuffer.GoalMark mark = (ExecutionBuffer.GoalMark) all.get(1);
        assertEquals("grasp", mark.goal());
        assertEquals(7, mark.goalId());
    }

    // --- Credit Assignment -------------------------------------------------------------
    private CreditAssignmentCodelet credit(Config cfg) {
        CreditAssignmentCodelet c = new CreditAssignmentCodelet(cfg);
        c.addInput(executionMO);
        c.addInput(sensoryBufferMO);
        c.addInput(driveMO);
        c.addInput(sensoryMO);
        c.addOutput(creditMO);
        return c;
    }

    private void creditCycle(CreditAssignmentCodelet c, long cycle, double task, double effort,
                             boolean restarted) {
        sensoryMO.setI(at(cycle, Traj.obs(0).q(), false));
        drives(cycle, 0, task, 0, effort, 0, restarted);
        c.notifyCodelet();
    }

    @Test
    void creditAssignsStepsOnTheirEndCycle() {
        Config cfg = new Config();
        cfg.lambda = 0.5;
        CreditAssignmentCodelet c = credit(cfg);
        creditCycle(c, 0, 1.0, 0.0, true);
        creditCycle(c, 1, 0.9, 0.0, false);
        buffer().addStep("A", 1, 0, 1, List.of(), 0, 2, "done", "reach", 1, "ctxA", 0);
        creditCycle(c, 2, 0.8, 0.0, false);
        creditCycle(c, 3, 0.75, 0.0, false);
        buffer().addStep("B", 2, 0, 1, List.of(), 2, 4, "done", "reach", 1, "ctxB", 0);
        creditCycle(c, 4, 0.7, 0.0, false);
        var read = agent.credit.CreditSnapshot.Read.SUM;
        double a = c.table().snapshot("A").value("ctxA", read)[Drives.TASK];
        double b = c.table().snapshot("B").value("ctxB", read)[Drives.TASK];
        assertEquals(0.1, b, 1e-9);                    // B's own change, weight 1
        assertEquals(0.2 + 0.25 * 0.1, a, 1e-9);       // A's, plus B's at lambda^2
    }

    @Test
    void oneStepCreditAndGoalSwitchesAreNotCredited() {
        Config cfg = new Config();
        cfg.lambda = 0.0;                              // C3
        CreditAssignmentCodelet c = credit(cfg);
        creditCycle(c, 0, 1.0, 0.0, true);
        creditCycle(c, 1, 0.9, 0.5, false);
        buffer().addStep("A", 1, 0, 1, List.of(), 0, 2, "done", "reach", 1, "ctxA", 0);
        creditCycle(c, 2, 0.8, 0.0, true);             // Effort restarted: not A's doing
        buffer().addStep("B", 2, 0, 1, List.of(), 2, 3, "done", "reach", 1, "ctxB", 0);
        creditCycle(c, 3, 0.7, 0.0, false);
        var read = agent.credit.CreditSnapshot.Read.SUM;
        double[] a = c.table().snapshot("A").value("ctxA", read);
        assertEquals(0.2, a[Drives.TASK], 1e-9);       // nothing from B
        assertEquals(-0.5, a[Drives.EFFORT], 1e-9);    // the rise is charged, the restart is not
    }

    /**
     * Curiosity's yield drifts down by itself (CUR-01). Differencing the level would hand that drift
     * to whatever ran, more to whatever ran longer; measured at the current yield, only boredom's
     * change is credited.
     */
    @Test
    void curiosityCreditIsBoredomsChangeNotTheYieldsDrift() {
        Config cfg = new Config();
        cfg.lambda = 0.0;
        CreditAssignmentCodelet c = credit(cfg);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        curiosity(0, 1.0, 1.0, 0.5);
        c.notifyCodelet();
        for (long t = 1; t <= 2; t++) {
            sensoryMO.setI(at(t, Traj.obs(0).q(), false));
            curiosity(t, 1.0, 1.0 - 0.1 * t, 0.5);           // bored throughout, yield 1 -> 0.8
            if (t == 2) {
                buffer().addStep("A", 1, 0, 1, List.of(), 0, 2, "done", "explore", 1, "ctx", 0);
            }
            c.notifyCodelet();
        }
        sensoryMO.setI(at(3, Traj.obs(0).q(), false));
        curiosity(3, 0.5, 0.8, 0.5);                         // novelty found, yield steady
        buffer().addStep("B", 2, 0, 1, List.of(), 2, 3, "done", "explore", 1, "ctx", 0);
        c.notifyCodelet();
        var read = CreditSnapshot.Read.SUM;
        assertEquals(0.0, c.table().snapshot("A").value("ctx", read)[Drives.CURIOSITY], 1e-12,
                "the yield fell from 1 to 0.8 by itself: not A's doing");
        assertEquals(0.8 * 0.5, c.table().snapshot("B").value("ctx", read)[Drives.CURIOSITY], 1e-12,
                "yield * the fall in boredom");
    }

    /** One habit per cycle, one-step credit; Task levels as given; each habit's Task credit. */
    private double[] taskCreditPerStep(int progressWindow, boolean chargeRetreat, double... levels) {
        executionMO.setI(new ExecutionBuffer(100));     // a test may call this twice
        Config cfg = new Config();
        cfg.lambda = 0.0;
        cfg.progressWindow = progressWindow;
        cfg.progressChargesRetreat = chargeRetreat;
        cfg.baselineRate = 0.0;
        CreditAssignmentCodelet c = credit(cfg);
        creditCycle(c, 0, levels[0], 0.0, true);
        double[] out = new double[levels.length - 1];
        for (int k = 1; k < levels.length; k++) {
            buffer().addStep("h" + k, k, 0, 1, List.of(), k - 1, k, "done", "reach", 1, "ctx", 0);
            creditCycle(c, k, levels[k], 0.0, false);
            out[k - 1] = c.table().snapshot("h" + k).value("ctx", CreditSnapshot.Read.SUM)[Drives.TASK];
        }
        return out;
    }

    /**
     * Task credit is progress beyond the closest the arm came in the last progressWindow cycles:
     * coming back to where it had been earns nothing, and moving away is not charged. Going back and
     * forth over one degree used to pay each forward move and charge each backward one.
     */
    @Test
    void taskCreditIsProgressBeyondTheRecentBest() {
        assertArrayEquals(new double[]{0.1, 0.0, 0.0, 0.1},
                taskCreditPerStep(20, false, 0.5, 0.4, 0.5, 0.4, 0.3), 1e-9);
    }

    /**
     * With the retreat charged, moving away costs what it costs under the plain change; only coming
     * back over ground already covered earns nothing. A cycle that comes back and goes beyond the
     * recent best earns the part beyond it.
     */
    @Test
    void progressWithTheRetreatCharged() {
        assertArrayEquals(new double[]{0.1, -0.1, 0.0, 0.1},
                taskCreditPerStep(20, true, 0.5, 0.4, 0.5, 0.4, 0.3), 1e-9);
        assertArrayEquals(new double[]{0.1, -0.1, 0.05},
                taskCreditPerStep(20, true, 0.5, 0.4, 0.5, 0.35), 1e-9);
    }

    @Test
    void progressWindowZeroIsThePlainChange() {
        assertArrayEquals(new double[]{0.1, -0.1, 0.1, 0.1},
                taskCreditPerStep(0, false, 0.5, 0.4, 0.5, 0.4, 0.3), 1e-9);
    }

    /**
     * One habit per cycle, one-step credit, at this stage weight; each cycle's stage and the
     * distance to its target set the Task level as the Drive Generator would. Each habit's Task credit.
     */
    private double[] taskCreditAcrossStages(double taskStageWeight, int[] stages, double[] distances) {
        executionMO.setI(new ExecutionBuffer(100));     // a fresh run: a test calls this several times
        Config cfg = new Config();
        cfg.lambda = 0.0;
        cfg.taskStageWeight = taskStageWeight;
        CreditAssignmentCodelet c = credit(cfg);
        double[] out = new double[stages.length - 1];
        for (int k = 0; k < stages.length; k++) {
            if (k > 0) {
                buffer().addStep("h" + k, k, 0, 1, List.of(), k - 1, k, "done", "transport", 1, "ctx",
                        0);
            }
            sensoryMO.setI(at(k, Traj.obs(0).q(), false));
            drives(k, 0, TaskStages.taskLevel(stages[k], distances[k], cfg.taskDistanceScale,
                    taskStageWeight), 0, 0, stages[k], k == 0);
            c.notifyCodelet();
            if (k > 0) {
                out[k - 1] = c.table().snapshot("h" + k).value("ctx", CreditSnapshot.Read.SUM)[Drives.TASK];
            }
        }
        return out;
    }

    /**
     * CRE-01. Letting the cube go mid-transport undoes a stage: above stage weight 0 the habit that
     * let go is charged the Task's rise, and grasping again is paid it back; at 0 both are zeroed
     * with the stage change, as before, and dropping the cube was free. Going in and out of reach
     * pays nothing overall at either weight: the Task is a potential, and its changes telescope.
     */
    @Test
    void aStageUndoneIsChargedAndCrossingBackAndForthPaysNothing() {
        int[] dropAndRegrasp = {2, 1, 2};                 // transport, let go at the hand, grasp again
        double[] distances = {0.2, 0.01, 0.2};
        double[] weightOne = taskCreditAcrossStages(1.0, dropAndRegrasp, distances);
        assertEquals((2 + 0.4) / 5 - (3 + 0.02) / 5, weightOne[0], 1e-12, "letting go is charged");
        assertEquals(-weightOne[0], weightOne[1], 1e-12, "grasping again is paid as much");
        assertArrayEquals(new double[]{0.0, 0.0},
                taskCreditAcrossStages(0.0, dropAndRegrasp, distances), 0.0);

        int[] inAndOutOfReach = {0, 1, 0};
        double[] acrossTheBorder = {0.051, 0.049, 0.051};
        for (double taskStageWeight : new double[]{0.0, 1.0}) {
            double[] crossing = taskCreditAcrossStages(taskStageWeight, inAndOutOfReach, acrossTheBorder);
            assertEquals(0.0, crossing[0] + crossing[1], 1e-12, "weight " + taskStageWeight);
        }
        assertTrue(taskCreditAcrossStages(1.0, inAndOutOfReach, acrossTheBorder)[0] > 0.19,
                "reaching pays a stage");
    }

    /** A new stage is a new target: the best of the last one is no reference for it. */
    @Test
    void theRecentBestRestartsWithTheStage() {
        Config cfg = new Config();
        cfg.lambda = 0.0;
        cfg.progressWindow = 20;
        cfg.baselineRate = 0.0;
        CreditAssignmentCodelet c = credit(cfg);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        drives(0, 0, 0.3, 0, 0, 0, true);
        c.notifyCodelet();
        sensoryMO.setI(at(1, Traj.obs(0).q(), false));
        drives(1, 0, 0.6, 0, 0, 1, false);              // reached: stage 1, a new target
        c.notifyCodelet();
        buffer().addStep("A", 1, 0, 1, List.of(), 1, 2, "done", "grasp", 1, "ctx", 0);
        sensoryMO.setI(at(2, Traj.obs(0).q(), false));
        drives(2, 0, 0.5, 0, 0, 1, false);
        c.notifyCodelet();
        assertEquals(0.1, c.table().snapshot("A").value("ctx", CreditSnapshot.Read.SUM)[Drives.TASK],
                1e-9, "measured against stage 1's 0.6, not stage 0's 0.3");
    }

    /**
     * A step is credited what it changed beyond what a cycle in its context usually changes: the
     * second step in context X is measured against the first, the first in Y against nothing.
     */
    @Test
    void creditIsTheChangeBeyondTheContextsBaseline() {
        Config cfg = new Config();
        cfg.lambda = 0.0;
        cfg.progressWindow = 0;
        cfg.baselineRate = 0.5;
        CreditAssignmentCodelet c = credit(cfg);
        creditCycle(c, 0, 1.0, 0.0, true);
        String[] habit = {"A", "B", "C"};
        String[] context = {"X", "X", "Y"};
        for (int k = 1; k <= 3; k++) {
            buffer().addStep(habit[k - 1], k, 0, 1, List.of(), k - 1, k, "done", "reach", 1,
                    context[k - 1], 0);
            creditCycle(c, k, 1.0 - 0.1 * k, 0.0, false);
        }
        var read = CreditSnapshot.Read.SUM;
        assertEquals(0.1, c.table().snapshot("A").value("X", read)[Drives.TASK], 1e-9);
        assertEquals(0.1 - 0.5 * 0.1, c.table().snapshot("B").value("X", read)[Drives.TASK], 1e-9);
        assertEquals(0.1, c.table().snapshot("C").value("Y", read)[Drives.TASK], 1e-9);
    }

    /**
     * The baseline is per step, not per cycle times the step's length: a drive's change does not grow
     * with time. Scaled by length, a 44-cycle grab in a bin where one-cycle moves had crossed into
     * novel bins was charged ~44 such crossings (a live -0.13 recorded as +1.97).
     */
    @Test
    void aLongStepIsMeasuredAgainstAStepNotAgainstItsCycles() {
        Config cfg = new Config();
        cfg.lambda = 0.0;
        cfg.progressWindow = 0;
        cfg.baselineRate = 0.5;
        CreditAssignmentCodelet c = credit(cfg);
        creditCycle(c, 0, 1.0, 0.0, true);
        buffer().addStep("A", 1, 0, 1, List.of(), 0, 1, "done", "reach", 1, "X", 0);
        creditCycle(c, 1, 0.9, 0.0, false);                 // one cycle, 0.1
        for (int k = 2; k <= 11; k++) {                     // ten cycles, 0.1 in all
            if (k == 11) {
                buffer().addStep("B", 2, 0, 1, List.of(), 1, 11, "done", "reach", 1, "X", 0);
            }
            creditCycle(c, k, 0.9 - 0.01 * (k - 1), 0.0, false);
        }
        assertEquals(0.1 - 0.5 * 0.1,
                c.table().snapshot("B").value("X", CreditSnapshot.Read.SUM)[Drives.TASK], 1e-9);
    }

    // --- Behavior Generator ----------------------------------------------------------------
    private BehaviorGeneratorCodelet behavior(Config cfg, MemoryContainer pool, long seed) {
        BehaviorGeneratorCodelet b = new BehaviorGeneratorCodelet(cfg, seed);
        b.addInput(pool);
        b.addInput(goalMO);
        b.addInput(sensoryMO);
        b.addInput(driveMO);
        b.addInput(trackerMO);
        b.addOutput(planMO);
        return b;
    }

    private MemoryContainer pool(String... ids) {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        for (String id : ids) {
            pool.add(mind.createMemoryObject(id, HabitIdeas.create(id, HabitIdeas.PRIMITIVE, List.of(),
                    List.of(new Command(Command.MOVE, 0, 0.01, 0.4, 20, 0)))));
        }
        return pool;
    }

    private static Idea habit(MemoryContainer pool, String id) {
        for (var m : pool.getAllMemories()) {
            Idea h = (Idea) m.getI();
            if (HabitIdeas.id(h).equals(id)) {
                return h;
            }
        }
        throw new AssertionError(id);
    }

    @Test
    void behaviorPicksTheBestAndKeepsAPlanUnlessBeaten() {
        MemoryContainer pool = pool("a", "b", "c");
        CreditTable t = new CreditTable();
        t.add("b", "x", new double[]{0, 1.0, 0, 0}, 1.0, true);     // b lowers Task
        t.add("c", "x", new double[]{2.0, 0, 0, 0}, 1.0, true);     // c lowers Curiosity
        HabitIdeas.setCredit(habit(pool, "b"), t.snapshot("b"));
        HabitIdeas.setCredit(habit(pool, "c"), t.snapshot("c"));
        BehaviorGeneratorCodelet b = behavior(new Config(), pool, 1);
        goal(1, Goal.TASK, "reach", 0);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));

        drives(0, 0.1, 0.9, 0, 0, 0, false);           // Task pressing: b (0.9) beats c (0.2)
        trackerMO.setI(TrackerState.idle(0));
        b.notifyCodelet();
        Plan p = (Plan) planMO.getI();
        assertEquals("b", HabitIdeas.id(p.habit()));

        drives(1, 0.4, 0.8, 0, 0, 0, false);           // c (0.8) only ties b (0.8): b is kept
        trackerMO.setI(new TrackerState(true, "b", p.serial(), 0, 1, List.of(), 1));
        b.notifyCodelet();
        assertEquals(p.serial(), ((Plan) planMO.getI()).serial());

        drives(2, 0.9, 0.1, 0, 0, 0, false);           // Curiosity pressing: c (1.8) takes over
        b.notifyCodelet();
        Plan q = (Plan) planMO.getI();
        assertEquals("c", HabitIdeas.id(q.habit()));
        assertNotEquals(p.serial(), q.serial());
    }

    @Test
    void zeroCreditTiesAreRandomButSeeded() {
        List<String> first = new ArrayList<>();
        List<String> second = new ArrayList<>();
        for (List<String> out : List.of(first, second)) {
            MemoryContainer pool = pool("a", "b", "c", "d", "e");
            BehaviorGeneratorCodelet b = behavior(new Config(), pool, 42);
            goal(1, Goal.TASK, "reach", 0);
            drives(0, 0.5, 0.5, 0, 0, 0, false);
            sensoryMO.setI(at(0, Traj.obs(0).q(), false));
            trackerMO.setI(TrackerState.idle(0));
            for (int k = 0; k < 20; k++) {
                b.notifyCodelet();
                out.add(HabitIdeas.id(((Plan) planMO.getI()).habit()));
            }
        }
        assertEquals(first, second);
        assertTrue(first.stream().distinct().count() > 1, "ties spread over the pool");
    }

    /**
     * UCB weighs what is known about a habit in THIS context. A habit that ran 50 times elsewhere and
     * never here is untried here and goes first. Counting its 50 instead left it a near-zero bonus
     * and gave the habit tried here once the largest: the 2026-10-15 baseline repeated a habit that
     * had already run in the bin in 99% of its choices. The hand is empty, so this holds with
     * borrowing on (CRE-01 borrows only with the cube in the hand: borrowing here too ended these
     * draws, and with them the agent's exploration). With the cube, a habit that ran elsewhere is no
     * longer untried, on purpose (borrowingRanksHabitsNewToAContextByTheirRecordElsewhere).
     */
    @Test
    void ucbTriesAHabitNeverRunHereBeforeRepeatingOneThatRan() {
        MemoryContainer pool = pool("here", "elsewhere");
        goal(1, Goal.TASK, "reach", 0);
        drives(0, 0.5, 0.5, 0, 0, 0, false);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        trackerMO.setI(TrackerState.idle(0));
        String here = CreditTable.context("reach", Characterization.key(Observation.of(sensoryMO)));
        CreditTable t = new CreditTable();
        t.add("here", here, new double[]{0.1, 0, 0, 0}, 1.0, true);
        for (int i = 0; i < 50; i++) {                  // results that vary: a spread to weigh
            t.add("elsewhere", "reach|far", new double[]{i % 2 == 0 ? 0.1 : -0.1, 0, 0, 0}, 1.0,
                    true);
        }
        t.closeExecutions();
        HabitIdeas.setCredit(habit(pool, "here"), t.snapshot("here"));
        HabitIdeas.setCredit(habit(pool, "elsewhere"), t.snapshot("elsewhere"));

        assertTrue(new Config().contextPriorWeight > 0, "borrowing on, as it runs");
        behavior(new Config(), pool, 1).notifyCodelet();
        assertEquals("here", HabitIdeas.id(((Plan) planMO.getI()).habit()), "greedy: the best score");
        behavior(new Config().withSelection("ucb"), pool, 1).notifyCodelet();
        assertEquals("elsewhere", HabitIdeas.id(((Plan) planMO.getI()).habit()),
                "ucb: never run here, so tried here first");
    }

    /**
     * A habit whose results never vary cannot set the spread for the rest. Live (seed 3, 2026-10-16):
     * every habit tried once, then a no-op repeated 4978 times; the pooled spread came from the
     * no-op alone, ~0, and UCB never retried the others. Each habit now carries its own spread, the
     * repertoire's reference until its own executions pull it away. The hand is empty, so borrowing
     * leaves this alone. With the cube in the hand it would not: the move's single execution would
     * count as 1 + n0, its bonus sqrt(3) smaller, and at 51 visits it would not yet be retried.
     */
    @Test
    void aRepeatedNoOpDoesNotSilenceTheBonusOfHabitsTriedOnce() {
        MemoryContainer pool = pool("noop", "move");
        goal(1, Goal.TASK, "reach", 0);
        drives(0, 0.5, 0.5, 0, 0, 0, false);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        trackerMO.setI(TrackerState.idle(0));
        String here = CreditTable.context("reach", Characterization.key(Observation.of(sensoryMO)));
        CreditTable t = new CreditTable();
        for (int i = 0; i < 50; i++) {
            t.add("noop", here, new double[]{0, 0, 0, 0}, 1.0, true);
        }
        t.add("move", here, new double[]{-0.001, 0, 0, 0}, 1.0, true);
        t.closeExecutions();
        HabitIdeas.setCredit(habit(pool, "noop"), t.snapshot("noop"));
        HabitIdeas.setCredit(habit(pool, "move"), t.snapshot("move"));

        behavior(new Config(), pool, 1).notifyCodelet();
        assertEquals("noop", HabitIdeas.id(((Plan) planMO.getI()).habit()), "greedy: the best score");
        behavior(new Config().withSelection("ucb"), pool, 1).notifyCodelet();
        assertEquals("move", HabitIdeas.id(((Plan) planMO.getI()).habit()),
                "ucb: one execution is not enough to give up on a habit");
    }

    /**
     * The habits UCB (c = 1) starts here in 20 decisions, nothing running, with borrowing at n0. One
     * generator for all 20: the first nextInt(2) of new Random(1), new Random(2), ... is nearly
     * always the same, a known weakness of its generator with small seeds.
     */
    private java.util.Set<String> ucbChoices(MemoryContainer pool, double contextPriorWeight) {
        Config config = new Config().withSelection("ucb");
        config.contextPriorWeight = contextPriorWeight;
        BehaviorGeneratorCodelet b = behavior(config, pool, 1);
        java.util.Set<String> chosen = new java.util.HashSet<>();
        for (int i = 0; i < 20; i++) {
            b.notifyCodelet();
            chosen.add(HabitIdeas.id(((Plan) planMO.getI()).habit()));
        }
        return chosen;
    }

    /**
     * CRE-01, the forced draw: carrying the cube into a bin where none of the habits has run yet.
     * Before, every habit was untried there and the start was a uniform draw, letting go of the cube
     * included (P1: ~77% of grab_open picks while holding were such draws). Borrowing, each habit
     * enters with its mean under "transport, holding" elsewhere and, the bin unvisited, no bonus: the
     * best record starts. A habit never run anywhere is still tried before any other.
     */
    @Test
    void borrowingRanksHabitsNewToAContextByTheirRecordElsewhere() {
        MemoryContainer pool = pool("letGo", "carryOn");
        goal(1, Goal.TASK, "transport", 2);
        drives(0, 0.2, 0.5, 0, 0, 2, false);
        sensoryMO.setI(Traj.obs(400).idea());
        assertTrue(Observation.of(sensoryMO).holding(), "observation 400 carries the cube");
        trackerMO.setI(TrackerState.idle(0));
        String carryingElsewhere = "transport|e0,0,0c0,0,0h1k1d0";
        CreditTable t = new CreditTable();
        for (int i = 0; i < 4; i++) {
            t.add("letGo", carryingElsewhere, new double[]{0, -0.2, 0, 0}, 1.0, true);
            t.add("carryOn", carryingElsewhere, new double[]{0, 0.01 * (i % 2), 0, 0}, 1.0, true);
        }
        t.add("letGo", "reach|e0,0,0c0,0,0h0k0d0", new double[]{0, 0.3, 0, 0}, 1.0, true);
        t.closeExecutions();
        HabitIdeas.setCredit(habit(pool, "letGo"), t.snapshot("letGo"));
        HabitIdeas.setCredit(habit(pool, "carryOn"), t.snapshot("carryOn"));

        assertEquals(java.util.Set.of("letGo", "carryOn"), ucbChoices(pool, 0.0), "before: a draw");
        assertEquals(java.util.Set.of("carryOn"), ucbChoices(pool, 2.0), "borrowing: the best record");

        MemoryContainer withANewHabit = pool("letGo", "carryOn", "neverRun");
        HabitIdeas.setCredit(habit(withANewHabit, "letGo"), t.snapshot("letGo"));
        HabitIdeas.setCredit(habit(withANewHabit, "carryOn"), t.snapshot("carryOn"));
        assertEquals(java.util.Set.of("neverRun"), ucbChoices(withANewHabit, 2.0),
                "never run anywhere: first");
    }

    // --- Sensory -------------------------------------------------------------------------------
    /** The bridge replaying the expert trajectory, one recorded observation per step. */
    private static final class Replay implements Environment {
        private int step;

        @Override
        public JsonObject info() {
            return new JsonObject();
        }

        @Override
        public JsonObject reset(int seed, int episode) {
            step = 0;
            return reply();
        }

        @Override
        public JsonObject step(JsonArray records, JsonObject annotate) {
            step++;
            return reply();
        }

        private JsonObject reply() {
            JsonObject r = new JsonObject();
            r.add("obs", Traj.json().get(step));
            r.addProperty("step", step);
            r.addProperty("done", false);
            r.addProperty("success", false);
            return r;
        }
    }

    @Test
    void sensoryRemembersTheCarryAndForgetsItWhenAnEpisodeStarts() {
        SimLink link = new SimLink(new Replay());
        SensoryCodelet s = new SensoryCodelet(link);
        s.addOutput(sensoryMO);
        s.addOutput(sensoryBufferMO);
        sensoryBufferMO.setI(new SensoryBuffer(5));
        link.reset(1, 0);
        s.notifyCodelet();
        for (int i = 1; i < Traj.json().size(); i++) {
            link.step(new JsonArray(), null);
            s.notifyCodelet();
        }
        assertTrue(TaskStages.settled(Observation.of(sensoryMO)), "the expert's carry ends in success");
        link.reset(1, 1);
        s.notifyCodelet();
        Observation o = Observation.of(sensoryMO);
        assertFalse(o.carried() || o.placing() || o.still() > 0, "a new episode starts with no carry");
    }

    /** The expert's cube, resting on the pad, but perceived with no carry before it: pushed in. */
    @Test
    void aCubePushedOntoThePadIsNotTheTaskDone() {
        Idea idea = Observation.toIdea(Traj.copy(Traj.json().size() - 1), 0, 0, true, false);
        new Carry().observe(idea);
        Observation o = new Observation(idea);
        assertTrue(TaskStages.placed(o));
        assertFalse(TaskStages.settled(o));
        int stage = TaskStages.infer(o);
        assertNotEquals(TaskStages.DONE, stage);
        assertTrue(TaskStages.targetDistance(stage, o) > 0.0, "the Task keeps its need");
        assertTrue(TaskStages.settled(Traj.obs(Traj.json().size() - 1)), "carried there, it is");
    }

    // --- Goal Generator ------------------------------------------------------------------------
    @Test
    void goalGeneratorWalksTheTaskStagesOnTheExpertTrajectory() {
        GoalGeneratorCodelet g = new GoalGeneratorCodelet(new Config());
        g.addInput(sensoryMO);
        g.addInput(driveMO);
        g.addOutput(goalMO);
        List<String> seen = new ArrayList<>();
        long lastId = -1;
        for (int i = 0; i < Traj.json().size(); i++) {
            sensoryMO.setI(Traj.obs(i).idea());
            drives(i, 0.0, 0.9, 0.0, 0.0, 0, false);   // Task the only pressing drive
            g.notifyCodelet();
            Goal goal = Goal.of(goalMO);
            assertEquals(Goal.TASK, goal.source());
            if (goal.id() != lastId) {
                seen.add(goal.name());
                lastId = goal.id();
            }
        }
        assertEquals(List.of("reach", "grasp", "transport", "release", "done"), seen);
    }

    @Test
    void safetyOverridesAndBoredomExplores() {
        GoalGeneratorCodelet g = new GoalGeneratorCodelet(new Config());
        g.addInput(sensoryMO);
        g.addInput(driveMO);
        g.addOutput(goalMO);
        sensoryMO.setI(Traj.obs(0).idea());
        drives(0, 0.2, 0.6, 0.0, 0, 0, false);
        g.notifyCodelet();
        assertEquals("reach", Goal.of(goalMO).name());
        sensoryMO.setI(Traj.obs(1).idea());
        drives(1, 0.65, 0.6, 0.0, 0, 0, false);        // within hysteresis: stays on the task
        g.notifyCodelet();
        assertEquals("reach", Goal.of(goalMO).name());
        drives(1, 0.8, 0.6, 0.0, 0, 0, false);         // clearly more pressing
        g.notifyCodelet();
        assertEquals(Goal.EXPLORE, Goal.of(goalMO).name());
        drives(1, 0.8, 0.6, 0.6, 0, 0, false);         // a joint near its limit
        g.notifyCodelet();
        assertEquals(Goal.RECOVER, Goal.of(goalMO).name());
    }

    /**
     * The hand-over CUR-01 is for. With yield 1, a bored Curiosity (~0.99) keeps the goal: Task,
     * capped at 1, can never beat it by the hysteresis. Once exploring stops paying, Task takes it --
     * and Curiosity's goal is not thereby "met": met is novelty found (boredom low), not a low yield,
     * or ExecutionBuffer would collect goal completions nothing achieved.
     */
    @Test
    void aLowYieldHandsTheGoalToTaskWithoutMeetingCuriositysGoal() {
        GoalGeneratorCodelet g = new GoalGeneratorCodelet(new Config());
        g.addInput(sensoryMO);
        g.addInput(driveMO);
        g.addOutput(goalMO);
        sensoryMO.setI(Traj.obs(0).idea());
        curiosity(0, 0.99, 1.0, 0.6);
        g.notifyCodelet();
        assertEquals(Goal.EXPLORE, Goal.of(goalMO).name());
        sensoryMO.setI(Traj.obs(1).idea());              // past the episode's start, which resets it
        curiosity(1, 0.99, 1.0, 1.0);
        g.notifyCodelet();
        assertEquals(Goal.EXPLORE, Goal.of(goalMO).name(), "Task at its cap still cannot take it");
        curiosity(2, 0.99, 0.2, 0.6);
        g.notifyCodelet();
        assertEquals("reach", Goal.of(goalMO).name());

        Config cfg = new Config();
        goal(9, Goal.CURIOSITY, Goal.EXPLORE, 0);
        Observation o = Traj.obs(0);
        curiosity(3, 0.99, 0.2, 0.6);                    // level 0.198, under curiosityGoalMet
        assertFalse(Goal.of(goalMO).met(o, Drives.of(driveMO), cfg.curiosityGoalMet, cfg.safetyGoalMet));
        curiosity(4, 0.2, 1.0, 0.6);                     // novelty found
        assertTrue(Goal.of(goalMO).met(o, Drives.of(driveMO), cfg.curiosityGoalMet, cfg.safetyGoalMet));
    }

    // --- HabitLearner: macros (vault spec MAC-01) ---------------------------------------------
    private static final double DEGREE = Math.toRadians(1.0);

    private static Command turn(int joint, double degrees) {
        return new Command(Command.MOVE, joint, degrees * DEGREE, 0.4, 20.0, 0);
    }

    /** A learner with three one-degree primitives, building macros by {@code rule}. */
    private HabitLearnerCodelet learner(String rule, MemoryContainer pool) {
        Config config = new Config().withMacroRule(rule);
        HabitLearnerCodelet learner = new HabitLearnerCodelet(config, mind);
        learner.addInput(creditMO);
        learner.addInput(executionMO);
        learner.addOutput(pool);
        learner.seed(List.of(
                HabitIdeas.create("move_j0_pos", HabitIdeas.PRIMITIVE, List.of(), List.of(turn(0, 1))),
                HabitIdeas.create("move_j1_pos", HabitIdeas.PRIMITIVE, List.of(), List.of(turn(1, 1))),
                HabitIdeas.create("move_j0_neg", HabitIdeas.PRIMITIVE, List.of(), List.of(turn(0, -1)))));
        return learner;
    }

    private long cycle;

    /** One executed primitive step, under the goal and state bin given, in {@code episode}. */
    private void ran(String habit, Command command, String context, int episode) {
        buffer().addStep(habit, cycle, 0, 1, List.of(command), cycle, cycle + 1, "done",
                context.substring(0, context.indexOf('|')), 1, context, episode);
        cycle++;
    }

    private static List<HabitLearnerCodelet.MacroEvent> after(HabitLearnerCodelet learner) {
        learner.notifyCodelet();
        return learner.macroEvents();
    }

    @Test
    void aTaskGoalMetBuildsAMacroForTheContextItsStretchStartedIn() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("sum", pool);
        ran("move_j0_pos", turn(0, 1), "explore|binA", 0);          // Curiosity's detour stays in
        buffer().addGoalMark(Goal.EXPLORE, 1, Goal.CURIOSITY, cycle, 0);
        ran("move_j1_pos", turn(1, 1), "reach|binB", 0);
        ran("move_j0_pos", turn(0, 1), "reach|binC", 0);
        buffer().addGoalMark("reach", 2, Goal.TASK, cycle, 0);
        List<HabitLearnerCodelet.MacroEvent> events = after(learner);

        assertEquals(1, events.size(), events.toString());
        HabitLearnerCodelet.MacroEvent created = events.get(0);
        assertEquals(HabitLearnerCodelet.CREATED, created.kind());
        assertEquals("reach|binA", created.initiation(), "the goal met, the first step's bin");
        assertEquals(3, created.stretchSteps());
        Idea macro = learner.habits().get(created.macro());
        assertEquals("macro_reach_1", HabitIdeas.id(macro));
        assertEquals(HabitIdeas.MACRO, HabitIdeas.origin(macro));
        assertEquals(List.of("move_j0_pos", "move_j1_pos"), HabitIdeas.parents(macro));
        assertEquals(List.of(turn(0, 2), turn(1, 1).withSpeed(0.2)), HabitIdeas.commands(macro),
                "one parallel step, joint 1 at half speed to end with joint 0");
        assertEquals(CreditSnapshot.EMPTY, HabitIdeas.credit(macro), "empty credit (D5)");
        assertEquals(4, pool.getAllMemories().size());
        assertTrue(after(learner).isEmpty(), "each entry is read once");
    }

    @Test
    void curiositysAndSafetysGoalsBuildNothingAndAStretchEndsWithItsEpisode() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("copy", pool);
        ran("move_j0_pos", turn(0, 1), "explore|binA", 0);
        ran("move_j1_pos", turn(1, 1), "explore|binA", 0);
        buffer().addGoalMark(Goal.EXPLORE, 1, Goal.CURIOSITY, cycle, 0);
        buffer().addGoalMark(Goal.RECOVER, 2, Goal.SAFETY, cycle, 0);
        assertTrue(after(learner).isEmpty());
        ran("move_j1_pos", turn(1, 1), "reach|binZ", 1);           // a new episode starts over
        buffer().addGoalMark("reach", 3, Goal.TASK, cycle, 1);
        List<HabitLearnerCodelet.MacroEvent> events = after(learner);
        assertEquals(HabitLearnerCodelet.EXISTS, events.get(0).kind(),
                "one step, the primitive itself: nothing new");
        assertEquals("move_j1_pos", events.get(0).macro());
        assertEquals("reach|binZ", events.get(0).initiation());
    }

    @Test
    void aShorterStretchFromTheSameContextRetiresTheMacroAndALongerOneIsARepetition() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("copy", pool);
        for (int i = 0; i < 3; i++) {
            ran("move_j0_pos", turn(0, 1), "reach|home", 0);
        }
        buffer().addGoalMark("reach", 1, Goal.TASK, cycle, 0);
        assertEquals(HabitLearnerCodelet.CREATED, after(learner).get(0).kind());

        for (int i = 0; i < 3; i++) {                               // as long: a repetition
            ran("move_j1_pos", turn(1, 1), "reach|home", 1);
        }
        buffer().addGoalMark("reach", 2, Goal.TASK, cycle, 1);
        HabitLearnerCodelet.MacroEvent repeated = after(learner).get(0);
        assertEquals(HabitLearnerCodelet.REPEATED, repeated.kind());
        assertEquals("macro_reach_1", repeated.macro());

        ran("move_j1_pos", turn(1, 1), "reach|home", 2);           // shorter: replaces it
        ran("move_j1_pos", turn(1, 1), "reach|home", 2);
        buffer().addGoalMark("reach", 3, Goal.TASK, cycle, 2);
        HabitLearnerCodelet.MacroEvent replaced = after(learner).get(0);
        assertEquals(HabitLearnerCodelet.REPLACED, replaced.kind());
        assertEquals("macro_reach_2", replaced.macro());
        assertEquals("macro_reach_1", replaced.retired());
        assertTrue(HabitIdeas.isRetired(learner.habits().get("macro_reach_1")));
        assertFalse(HabitIdeas.isRetired(learner.habits().get("macro_reach_2")));
        assertEquals(2, HabitIdeas.stretchSteps(learner.habits().get("macro_reach_2")));
        assertEquals(5, pool.getAllMemories().size(), "the retired one stays in the pool");
    }

    @Test
    void aMacroThatRanAloneAndMetItsGoalDoesNotRetireItself() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("sum", pool);
        ran("move_j0_pos", turn(0, 1), "reach|home", 0);
        ran("move_j1_pos", turn(1, 1), "reach|home", 0);
        buffer().addGoalMark("reach", 1, Goal.TASK, cycle, 0);
        Idea macro = learner.habits().get(after(learner).get(0).macro());

        buffer().addStep(HabitIdeas.id(macro), cycle, 0, 1, HabitIdeas.commands(macro), cycle,
                cycle + 20, "done", "reach", 2, "reach|home", 1);
        cycle += 20;
        buffer().addGoalMark("reach", 2, Goal.TASK, cycle, 1);
        HabitLearnerCodelet.MacroEvent event = after(learner).get(0);
        assertEquals(HabitLearnerCodelet.EXISTS, event.kind(), "one step is shorter, but the same");
        assertFalse(HabitIdeas.isRetired(macro));
    }

    @Test
    void aStepCutShortEntersAsFarAsItRan() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("sum", pool);
        buffer().addStep("some_macro", cycle, 0, 1, List.of(turn(2, 30)), List.of(turn(2, 12)),
                cycle, cycle + 10, PlanTrackerCodelet.PREEMPTED, "reach", 1, "reach|home", 0);
        cycle += 10;
        ran("move_j1_pos", turn(1, 1), "reach|x", 0);
        buffer().addGoalMark("reach", 1, Goal.TASK, cycle, 0);
        Idea macro = learner.habits().get(after(learner).get(0).macro());
        assertEquals(12 * DEGREE, HabitIdeas.commands(macro).get(1).angle(), 1e-12,
                "joint 2: the 12 degrees it turned, not the 30 commanded");
    }

    @Test
    void aFullPoolRefusesANewContextButStillReplaces() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        Config config = new Config().withMacroRule("copy");
        config.maxActiveMacros = 1;
        HabitLearnerCodelet learner = new HabitLearnerCodelet(config, mind);
        learner.addInput(creditMO);
        learner.addInput(executionMO);
        learner.addOutput(pool);
        learner.seed(List.of(HabitIdeas.create("move_j0_pos", HabitIdeas.PRIMITIVE, List.of(),
                List.of(turn(0, 1)))));
        ran("move_j0_pos", turn(0, 1), "reach|a", 0);
        ran("move_j0_pos", turn(0, 1), "reach|a", 0);
        ran("move_j0_pos", turn(0, 1), "reach|a", 0);
        buffer().addGoalMark("reach", 1, Goal.TASK, cycle, 0);
        assertEquals(HabitLearnerCodelet.CREATED, after(learner).get(0).kind());
        ran("move_j0_pos", turn(0, 1), "grasp|b", 0);
        ran("move_j0_pos", turn(0, 1), "grasp|b", 0);
        buffer().addGoalMark("grasp", 2, Goal.TASK, cycle, 0);
        assertEquals(HabitLearnerCodelet.REFUSED, after(learner).get(0).kind());
        ran("move_j0_pos", turn(0, 1), "reach|a", 1);
        ran("move_j0_pos", turn(0, 1), "reach|a", 1);
        buffer().addGoalMark("reach", 3, Goal.TASK, cycle, 1);
        assertEquals(HabitLearnerCodelet.REPLACED, after(learner).get(0).kind());
    }

    @Test
    void withoutAMacroRuleTheLearnerBuildsNothing() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("none", pool);
        ran("move_j0_pos", turn(0, 1), "reach|a", 0);
        ran("move_j1_pos", turn(1, 1), "reach|a", 0);
        buffer().addGoalMark("reach", 1, Goal.TASK, cycle, 0);
        assertTrue(after(learner).isEmpty());
        assertEquals(3, pool.getAllMemories().size());
    }

    @Test
    void aLearnerRestoredFromItsStateHasItsMacrosAndGoesOnNumbering() {
        MemoryContainer pool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet learner = learner("copy", pool);
        for (int episode = 0; episode < 2; episode++) {
            for (int i = 0; i < 3 - episode; i++) {
                ran("move_j0_pos", turn(0, 1), "reach|home", episode);
            }
            buffer().addGoalMark("reach", episode + 1, Goal.TASK, cycle, episode);
            learner.notifyCodelet();
        }
        com.google.gson.JsonObject state = learner.state();

        MemoryContainer otherPool = mind.createMemoryContainer("HabitPoolMC");
        HabitLearnerCodelet restored = learner("copy", otherPool);
        restored.restore(state);
        assertEquals(new ArrayList<>(learner.habits().keySet()), new ArrayList<>(restored.habits().keySet()));
        assertTrue(HabitIdeas.isRetired(restored.habits().get("macro_reach_1")));
        assertEquals(state, restored.state());
        ran("move_j0_pos", turn(0, 1), "reach|elsewhere", 2);
        ran("move_j1_pos", turn(1, 1), "reach|elsewhere", 2);
        buffer().addGoalMark("reach", 3, Goal.TASK, cycle, 2);
        HabitLearnerCodelet.MacroEvent event = after(restored).get(0);
        assertEquals(HabitLearnerCodelet.CREATED, event.kind());
        assertEquals("macro_reach_3", event.macro(), "the numbering goes on");
    }

    // --- Behavior Generator and macros (MAC-01 D1, D4, D14) ---------------------------------------
    private Idea macroIn(MemoryContainer pool, String id, String initiation) {
        Idea macro = HabitIdeas.createMacro(id, List.of(), List.of(turn(0, 5)), initiation, 10);
        pool.add(mind.createMemoryObject(id, macro));
        return macro;
    }

    @Test
    void aMacroIsChosenOnlyInItsContextAndNeverOnceRetired() {
        MemoryContainer pool = pool("p");
        goal(1, Goal.TASK, "reach", 0);
        drives(0, 0.5, 0.5, 0, 0, 0, false);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        trackerMO.setI(TrackerState.idle(0));
        String here = CreditTable.context("reach", Characterization.key(Observation.of(sensoryMO)));
        Idea macroHere = macroIn(pool, "m_here", here);
        Idea macroElsewhere = macroIn(pool, "m_elsewhere", "reach|far");
        CreditTable t = new CreditTable();
        t.add("m_here", here, new double[]{0, 1.0, 0, 0}, 1.0, true);
        t.add("m_elsewhere", here, new double[]{0, 5.0, 0, 0}, 1.0, true);   // would win here
        t.closeExecutions();
        HabitIdeas.setCredit(macroHere, t.snapshot("m_here"));
        HabitIdeas.setCredit(macroElsewhere, t.snapshot("m_elsewhere"));

        behavior(new Config(), pool, 1).notifyCodelet();
        assertEquals("m_here", HabitIdeas.id(((Plan) planMO.getI()).habit()));
        HabitIdeas.retire(macroHere);
        behavior(new Config(), pool, 1).notifyCodelet();
        assertEquals("p", HabitIdeas.id(((Plan) planMO.getI()).habit()), "retired: never again");
    }

    @Test
    void aMacroInExecutionRunsOnUntilTheGoalChanges() {
        MemoryContainer pool = pool("p");
        goal(1, Goal.TASK, "reach", 0);
        drives(0, 0.5, 0.5, 0, 0, 0, false);
        sensoryMO.setI(at(0, Traj.obs(0).q(), false));
        trackerMO.setI(TrackerState.idle(0));
        String here = CreditTable.context("reach", Characterization.key(Observation.of(sensoryMO)));
        Idea macro = macroIn(pool, "m", here);
        BehaviorGeneratorCodelet b = behavior(new Config().withSelection("ucb"), pool, 1);
        CreditTable t = new CreditTable();
        t.add("p", here, new double[]{0, 0.1, 0, 0}, 1.0, true);
        t.closeExecutions();
        HabitIdeas.setCredit(habit(pool, "p"), t.snapshot("p"));
        b.notifyCodelet();
        Plan chosen = (Plan) planMO.getI();
        assertEquals("m", HabitIdeas.id(chosen.habit()), "never run here: UCB tries it");

        int later = 1;                                              // the expert arm, in another bin
        while (Characterization.key(Traj.obs(later)).equals(Characterization.key(Traj.obs(0)))) {
            later++;
        }
        sensoryMO.setI(Traj.obs(later).idea());
        trackerMO.setI(new TrackerState(true, "m", chosen.serial(), 0, 1, List.of(), 1));
        String there = CreditTable.context("reach", Characterization.key(Observation.of(sensoryMO)));
        assertNotEquals(here, there, "the arm moved to another bin");
        b.notifyCodelet();
        assertEquals(chosen.serial(), ((Plan) planMO.getI()).serial(),
                "outside its context, beside an untried habit, the macro runs on");

        goal(2, Goal.CURIOSITY, Goal.EXPLORE, 0);                 // another drive takes the goal
        b.notifyCodelet();
        Plan next = (Plan) planMO.getI();
        assertNotEquals(chosen.serial(), next.serial());
        assertEquals("p", HabitIdeas.id(next.habit()));
        assertFalse(HabitIdeas.isRetired(macro));
    }
}
