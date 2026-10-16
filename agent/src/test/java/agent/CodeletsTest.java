package agent;

import agent.codelets.BehaviorGeneratorCodelet;
import agent.codelets.CreditAssignmentCodelet;
import agent.codelets.GoalGeneratorCodelet;
import agent.codelets.PlanTrackerCodelet;
import agent.credit.CreditSnapshot;
import agent.credit.CreditTable;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.TrackerState;
import agent.motivation.Characterization;
import agent.motivation.Drives;
import agent.sim.Observation;
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

    /** One habit per cycle, one-step credit; Task levels as given; each habit's Task credit. */
    private double[] taskCreditPerStep(int progressWindow, boolean chargeRetreat, double... levels) {
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
     * had already run in the bin in 99% of its choices.
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
     * repertoire's reference until its own executions pull it away.
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
}
