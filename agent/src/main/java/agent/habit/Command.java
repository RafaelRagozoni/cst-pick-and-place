package agent.habit;

import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;

/**
 * One command record of cap4 4.4.1: {@code {action, joint, angle, speed, force, step}}.
 *
 * <p>The same schema is the motor command, the HabitPool member's content, and the ExecutionBuffer
 * record. It mirrors {@code coppelia_environment/actions.py}, which owns the wire contract: a MOVE
 * means "rotate {@code joint} by {@code angle} radians at {@code speed} rad/s", the angle relative to
 * where the joint was when the step started; a GRAB with negative force opens the gripper. Records
 * sharing a {@code step} run in parallel, increasing steps run in sequence.
 */
public record Command(String action, int joint, double angle, double speed, double force, int step) {

    public static final String MOVE = "MOVE";
    public static final String GRAB = "GRAB";
    public static final String HOLD = "HOLD";

    public boolean isMove() {
        return MOVE.equals(action);
    }

    public boolean isGrab() {
        return GRAB.equals(action);
    }

    public Command withAngle(double a) {
        return new Command(action, joint, a, speed, force, step);
    }

    public Command withStep(int s) {
        return new Command(action, joint, angle, speed, force, s);
    }

    /** The name actions.record_id gives this record; for a single-record habit, its id. */
    public String recordId() {
        if (isGrab()) {
            return force < 0 ? "grab_open" : "grab_close";
        }
        if (isMove()) {
            return "move_j" + joint + (angle > 0 ? "_pos" : "_neg");
        }
        return "hold";
    }

    public JsonObject toJson() {
        JsonObject o = new JsonObject();
        o.addProperty("action", action);
        o.addProperty("joint", joint);
        o.addProperty("angle", angle);
        o.addProperty("speed", speed);
        o.addProperty("force", force);
        o.addProperty("step", step);
        return o;
    }

    public static Command fromJson(JsonObject o) {
        return new Command(o.get("action").getAsString(), o.get("joint").getAsInt(),
                o.get("angle").getAsDouble(), o.get("speed").getAsDouble(),
                o.get("force").getAsDouble(), o.has("step") ? o.get("step").getAsInt() : 0);
    }

    /** This record as an Idea, one child per field. */
    public Idea toIdea(String name) {
        Idea r = new Idea(name, null, 1);
        r.add(new Idea("action", action, 1));
        r.add(new Idea("joint", joint, 1));
        r.add(new Idea("angle", angle, 1));
        r.add(new Idea("speed", speed, 1));
        r.add(new Idea("force", force, 1));
        r.add(new Idea("step", step, 1));
        return r;
    }

    public static Command fromIdea(Idea r) {
        return new Command((String) r.get("action").getValue(),
                ((Number) r.get("joint").getValue()).intValue(),
                ((Number) r.get("angle").getValue()).doubleValue(),
                ((Number) r.get("speed").getValue()).doubleValue(),
                ((Number) r.get("force").getValue()).doubleValue(),
                ((Number) r.get("step").getValue()).intValue());
    }
}
