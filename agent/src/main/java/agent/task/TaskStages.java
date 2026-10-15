package agent.task;

import agent.sim.Observation;

/**
 * The four task stages of cap4 4.5, with the precondition and termination of each (cap4 4.3.3).
 *
 * <p>The predicates are a port of {@code coppelia_environment/goals.py}, which defines success for
 * the experiment; {@code TaskStagesParityTest} checks the two agree on the recorded expert
 * trajectory. The port exists because the agent must not read the environment's task tracker: the
 * bridge returns it, but a robot outside the simulator would have no such thing.
 *
 * <p>One deliberate difference: goals.py ends {@code release} after the cube has been still for 10
 * consecutive observations. The agent's termination is a pure function of one observation (released,
 * on the pad, below the settle speed), so the PlanTracker can evaluate it without keeping a counter.
 */
public final class TaskStages {

    public static final double REACH_DIST = 0.05;
    public static final double EPS_TASK = 0.05;
    public static final double TRANSPORT_XY = 0.05;
    public static final double TRANSPORT_MIN_LIFT = 0.03;
    public static final double SETTLE_SPEED = 0.01;

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

    public static boolean succeeded(Observation o) {
        return onPad(o) && !grasped(o);
    }

    // --- stage structure ------------------------------------------------------
    public static boolean precondition(int stage, Observation o) {
        switch (stage) {
            case 0: return true;
            case 1: return reached(o);
            case 2: return grasped(o);
            case 3: return transported(o);
            default: return true;
        }
    }

    public static boolean termination(int stage, Observation o) {
        switch (stage) {
            case 0: return reached(o);
            case 1: return grasped(o);
            case 2: return transported(o);
            case 3: return succeeded(o) && cubeSpeed(o) < SETTLE_SPEED;
            default: return false;
        }
    }

    /** The stage the scene is in, read from one observation alone. The Task drive uses this. */
    public static int infer(Observation o) {
        if (grasped(o)) {
            return transported(o) ? 3 : 2;
        }
        if (succeeded(o)) {
            return DONE;
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
