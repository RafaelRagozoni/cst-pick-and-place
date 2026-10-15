package agent;

import agent.codelets.BehaviorGeneratorCodelet;
import agent.codelets.CreditAssignmentCodelet;
import agent.codelets.GoalGeneratorCodelet;
import agent.codelets.PlanTrackerCodelet;
import agent.credit.CreditTable;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.TrackerState;
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
