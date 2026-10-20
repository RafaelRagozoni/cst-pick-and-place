package agent.task;

import agent.sim.Observation;

/**
 * The four task stages of cap4 4.5, with the precondition and termination of each (cap4 4.3.3).
 *
 * <p>The predicates are a port of {@code coppelia_environment/goals.py}, which defines success for
 * the experiment; {@code ParityTest} checks the two agree on the recorded expert trajectory. The
 * port exists because the agent must not read the environment's task tracker: the bridge returns
 * it, but a robot outside the simulator would have no such thing.
 *
 * <p>{@code release} ends on the strict success test (BAS-01; goals.py's {@code SUCCESS_TEST} names
 * its version), which needs the carry's history: was the cube let go over the pad after a
 * transport, and has it been still since? The Sensory codelet keeps that history ({@link Carry}) and
 * writes it into each observation, so every predicate here is still a function of one observation,
 * and {@link #settled} is that test. {@link #placed} -- on the pad and not held, however it got
 * there -- is goals.py's one-observation predicate, kept for the parity test: a cube pushed onto the
 * pad is placed, and the task is not done.
 */
public final class TaskStages {

    public static final double REACH_DIST = 0.05;
    public static final double EPS_TASK = 0.05;
    public static final double TRANSPORT_XY = 0.05;
    public static final double TRANSPORT_MIN_LIFT = 0.05;    // goals.py says why, with the heights
    public static final double SETTLE_SPEED = 0.01;
    public static final int SETTLE_STEPS = 10;

    public static final String[] STAGES = {"reach", "grasp", "transport", "release"};
    public static final int DONE = STAGES.length;

    private TaskStages() {
    }

    public static String name(int stage) {
        return stage >= DONE ? "done" : STAGES[stage];
    }

    public static int index(String name) {
        for (int i = 0; i < STAGES.length; i++) {
            if (STAGES[i].equals(name)) {
                return i;
            }
        }
        return DONE;
    }

    // --- goals.py predicates -------------------------------------------------
    public static boolean reached(Observation o) {
        return o.eefToCube() <= REACH_DIST;
    }

    public static boolean grasped(Observation o) {
        return o.holding();
    }

    public static boolean transported(Observation o) {
        return grasped(o) && o.cubeToPadXY() <= TRANSPORT_XY && o.cubeHeight() >= TRANSPORT_MIN_LIFT;
    }

    public static double cubeSpeed(Observation o) {
        double[] v = o.cubeVel();
        return Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    }

    public static boolean onPad(Observation o) {
        return o.cubeToPadXY() <= EPS_TASK && o.cubeHeight() > 0.0;
    }

    /** goals.py's {@code placed}: on the pad and not held, in one observation. */
    public static boolean placed(Observation o) {
        return onPad(o) && !grasped(o);
    }

    /** The bridge's episode success: let go over the pad after a transport, then still. */
    public static boolean settled(Observation o) {
        return o.placing() && o.still() >= SETTLE_STEPS;
    }

    // --- stage structure ------------------------------------------------------
    public static boolean precondition(int stage, Observation o) {
        switch (stage) {
            case 0: return true;
            case 1: return reached(o);
            case 2: return grasped(o);
            case 3: return transported(o) || o.placing();
            default: return true;
        }
    }

    public static boolean termination(int stage, Observation o) {
        switch (stage) {
            case 0: return reached(o);
            case 1: return grasped(o);
            case 2: return transported(o);
            case 3: return settled(o);
            default: return false;
        }
    }

    /**
     * The stage the scene is in, read from one observation and the carry it remembers. The Task drive
     * uses this. A cube that reached the pad any other way than let go there after a carry is still
     * to be reached, so the Task keeps its need.
     */
    public static int infer(Observation o) {
        if (grasped(o)) {
            return transported(o) ? 3 : 2;
        }
        if (settled(o)) {
            return DONE;
        }
        if (o.placing()) {
            return 3;
        }
        return reached(o) ? 1 : 0;
    }

    /**
     * Distance from what the stage moves -- the end-effector, or the grasped cube -- to the stage's
     * target. cap4 4.3.2: the Task drive "rises with the Euclidean distance between the end-effector,
     * or the grasped cube, and that stage's target".
     */
    public static double targetDistance(int stage, Observation o) {
        switch (stage) {
            case 0:
            case 1:
                return o.eefToCube();
            case 2: {
                double lift = Math.max(0.0, TRANSPORT_MIN_LIFT - o.cubeHeight());
                return Math.hypot(o.cubeToPadXY(), lift);
            }
            case 3:
                return o.cubeToPadXY();
            default:
                return 0.0;
        }
    }

    /** Where the stage's target is, for GoalMO. */
    public static double[] target(int stage, Observation o) {
        if (stage <= 1) {
            return o.cubePos().clone();
        }
        double[] pad = o.padPos().clone();
        if (stage == 2) {
            pad[2] += TRANSPORT_MIN_LIFT;
        }
        return stage < DONE ? pad : new double[0];
    }
}
