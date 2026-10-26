package agent.sim;

import agent.habit.Command;

import java.util.ArrayList;
import java.util.List;

/**
 * Follows one habit step -- the records sharing a step index -- until it is over.
 *
 * <p>A line-for-line port of {@code actions.StepCompletion}, so the PlanTracker ends a step exactly
 * the way the Python random baseline (C6) does: a MOVE is finished when its joint has turned through
 * {@code angle} or has stopped turning; a GRAB when the fingers stop moving; the step when every
 * record is. {@code StepCompletionParityTest} runs both on the same recorded observations and fails
 * if they disagree, so a change on one side cannot drift silently.
 */
public final class StepCompletion {

    public static final double ANGLE_TOL = Math.toRadians(0.1);
    public static final double STALL_ANGLE = Math.toRadians(0.01);
    public static final double GRIP_SETTLED = 0.0005;
    public static final int GRIP_MIN_TICKS = 3;
    public static final int STEP_TICK_CAP = 400;

    public static final String DONE = "done";
    public static final String STALLED = "stalled";
    public static final String TIMEOUT = "timeout";

    private final List<Command> records;
    private final double[] q0;
    private double[] qPrev;
    private double wPrev;
    private int ticks;
    private final boolean[] finished;
    private final boolean[] stalled;

    public StepCompletion(List<Command> records, Observation obs) {
        this.records = List.copyOf(records);
        this.q0 = obs.q().clone();
        this.qPrev = q0;
        this.wPrev = obs.gripperWidth();
        this.finished = new boolean[records.size()];
        this.stalled = new boolean[records.size()];
    }

    public List<Command> records() {
        return records;
    }

    /** Signed angle the record's joint still has to turn. */
    public double remaining(Command rec, Observation obs) {
        double turned = obs.q()[rec.joint()] - q0[rec.joint()];
        return rec.angle() - turned;
    }

    /** The records to send this tick: unfinished ones, MOVE angles replaced by what is left. */
    public List<Command> commands(Observation obs) {
        List<Command> out = new ArrayList<>();
        for (int i = 0; i < records.size(); i++) {
            if (finished[i]) {
                continue;
            }
            Command rec = records.get(i);
            out.add(rec.isMove() ? rec.withAngle(remaining(rec, obs)) : rec);
        }
        return out;
    }

    /** Account for one more tick: null while running, else DONE, STALLED or TIMEOUT. */
    public String update(Observation obs) {
        ticks++;
        double[] q = obs.q();
        double w = obs.gripperWidth();
        for (int i = 0; i < records.size(); i++) {
            if (finished[i]) {
                continue;
            }
            Command rec = records.get(i);
            if (rec.isMove()) {
                int j = rec.joint();
                if (Math.abs(remaining(rec, obs)) <= ANGLE_TOL) {
                    finished[i] = true;
                } else if (ticks >= 2 && Math.abs(q[j] - qPrev[j]) < STALL_ANGLE) {
                    finished[i] = true;
                    stalled[i] = true;
                }
            } else if (rec.isGrab()) {
                if (ticks >= GRIP_MIN_TICKS && Math.abs(w - wPrev) < GRIP_SETTLED) {
                    finished[i] = true;
                }
            } else {                                    // HOLD: one tick
                finished[i] = true;
            }
        }
        qPrev = q.clone();
        wPrev = w;
        boolean all = true;
        boolean anyStalled = false;
        for (int i = 0; i < records.size(); i++) {
            all &= finished[i];
            anyStalled |= stalled[i];
        }
        if (all) {
            return anyStalled ? STALLED : DONE;
        }
        if (ticks >= STEP_TICK_CAP) {
            return TIMEOUT;
        }
        return null;
    }
}
