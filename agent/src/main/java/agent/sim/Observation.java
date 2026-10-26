package agent.sim;

import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/**
 * The SensoryMO Idea, and a typed view over it.
 *
 * <p>cap4 4.2: the Sensory codelet "writes one Idea to SensoryMO, holding the external state (object
 * and target poses) and the inner state (joint positions, velocities, and torques, end-effector pose,
 * gripper state, contact flags)". {@link #toIdea} builds that Idea from the bridge's observation dict
 * (coppelia_environment/observations.py, which owns the field meanings); every other codelet reads it
 * through this view instead of walking Idea paths by hand.
 *
 * <pre>
 *   Idea SensoryMO
 *     cycle, episode, episodeStart, terminal, t
 *     inner     q, qd, tau, eefPos, eefQuat, gripperWidth, gripperOpen, holding, contact,
 *               jointLimitMargin, selfCollision, envCollision, manipulability
 *     external  cubePos, cubeVel, padPos
 *     derived   eefToCube, cubeToPadXY, cubeHeight, cubeDisplacement
 *     carry     carried, placing, still
 * </pre>
 *
 * Vectors are stored as {@code double[]} Idea values. {@code cycle} counts control cycles over the
 * whole run, across episodes; {@code terminal} marks the observation an episode ended on, which the
 * agent perceives and learns from but no longer acts on.
 *
 * <p>{@code carry} is the one group the bridge does not send: what the agent remembers of the carry
 * ({@link agent.task.Carry}), written by the Sensory codelet. {@link #toIdea} alone has no history to
 * remember, so it writes no carry.
 */
public final class Observation {

    private final Idea idea;

    public Observation(Idea idea) {
        this.idea = idea;
    }

    public static Observation of(Memory sensoryMO) {
        return new Observation((Idea) sensoryMO.getI());
    }

    public Idea idea() {
        return idea;
    }

    // --- construction ------------------------------------------------------
    public static Idea toIdea(JsonObject obs, long cycle, int episode, boolean episodeStart,
                              boolean terminal) {
        JsonObject inner = obs.getAsJsonObject("innerSense");
        JsonObject grip = inner.getAsJsonObject("gripper");
        JsonObject vision = obs.getAsJsonObject("vision");
        JsonObject derived = obs.getAsJsonObject("derived");
        JsonArray joints = inner.getAsJsonArray("joints");
        double[] q = new double[joints.size()];
        double[] qd = new double[joints.size()];
        double[] tau = new double[joints.size()];
        for (int i = 0; i < joints.size(); i++) {
            JsonObject j = joints.get(i).getAsJsonObject();
            q[i] = j.get("pos").getAsDouble();
            qd[i] = j.get("vel").getAsDouble();
            tau[i] = j.get("torque").getAsDouble();
        }

        Idea root = new Idea("SensoryMO", null, 0);
        root.add(prop("cycle", cycle));
        root.add(prop("episode", episode));
        root.add(prop("episodeStart", episodeStart));
        root.add(prop("terminal", terminal));
        root.add(prop("t", obs.get("t").getAsDouble()));

        Idea in = new Idea("inner", null, 0);
        in.add(prop("q", q));
        in.add(prop("qd", qd));
        in.add(prop("tau", tau));
        in.add(prop("eefPos", vec(inner.getAsJsonObject("eef").getAsJsonArray("pos"))));
        in.add(prop("eefQuat", vec(inner.getAsJsonObject("eef").getAsJsonArray("quat"))));
        in.add(prop("gripperWidth", grip.get("width").getAsDouble()));
        in.add(prop("gripperOpen", grip.get("commanded_open").getAsBoolean()));
        in.add(prop("holding", grip.get("isHolding").getAsBoolean()));
        in.add(prop("contact", grip.get("inContact").getAsBoolean()));
        in.add(prop("jointLimitMargin", vec(inner.getAsJsonArray("jointLimitMargin"))));
        in.add(prop("selfCollision", inner.get("selfCollision").getAsBoolean()));
        in.add(prop("envCollision", inner.get("envCollision").getAsBoolean()));
        in.add(prop("manipulability", num(inner.get("manipulability"))));
        root.add(in);

        Idea ext = new Idea("external", null, 0);
        ext.add(prop("cubePos", vec(vision.getAsJsonObject("cube").getAsJsonArray("pos"))));
        ext.add(prop("cubeVel", vec(vision.getAsJsonObject("cube").getAsJsonArray("vel"))));
        ext.add(prop("padPos", vec(vision.getAsJsonObject("pad").getAsJsonArray("pos"))));
        root.add(ext);

        Idea der = new Idea("derived", null, 0);
        der.add(prop("eefToCube", derived.get("eefToCube").getAsDouble()));
        der.add(prop("cubeToPadXY", derived.get("cubeToPadXY").getAsDouble()));
        der.add(prop("cubeHeight", derived.get("cubeHeightAboveTable").getAsDouble()));
        der.add(prop("cubeDisplacement", derived.get("cubeDisplacement").getAsDouble()));
        root.add(der);

        Idea carry = new Idea("carry", null, 0);
        carry.add(prop("carried", false));
        carry.add(prop("placing", false));
        carry.add(prop("still", 0));
        root.add(carry);
        return root;
    }

    /** Write the carry into an observation built by {@link #toIdea}. */
    public static void setCarry(Idea observation, boolean carried, boolean placing, int still) {
        observation.get("carry.carried").setValue(carried);
        observation.get("carry.placing").setValue(placing);
        observation.get("carry.still").setValue(still);
    }

    private static Idea prop(String name, Object value) {
        return new Idea(name, value, 1);
    }

    private static double[] vec(JsonArray a) {
        double[] v = new double[a.size()];
        for (int i = 0; i < v.length; i++) {
            v[i] = a.get(i).getAsDouble();
        }
        return v;
    }

    private static double num(JsonElement e) {
        return e == null || e.isJsonNull() ? Double.NaN : e.getAsDouble();
    }

    // --- view ----------------------------------------------------------------
    private Object v(String path) {
        Idea i = idea.get(path);
        if (i == null) {
            throw new IllegalStateException("SensoryMO has no " + path);
        }
        return i.getValue();
    }

    private double d(String path) {
        return ((Number) v(path)).doubleValue();
    }

    private boolean b(String path) {
        return (Boolean) v(path);
    }

    private double[] a(String path) {
        return (double[]) v(path);
    }

    public long cycle() {
        return ((Number) v("cycle")).longValue();
    }

    public int episode() {
        return ((Number) v("episode")).intValue();
    }

    public boolean episodeStart() {
        return b("episodeStart");
    }

    public boolean terminal() {
        return b("terminal");
    }

    public double t() {
        return d("t");
    }

    public double[] q() {
        return a("inner.q");
    }

    public double[] qd() {
        return a("inner.qd");
    }

    public double[] eefPos() {
        return a("inner.eefPos");
    }

    public double gripperWidth() {
        return d("inner.gripperWidth");
    }

    public boolean gripperOpen() {
        return b("inner.gripperOpen");
    }

    public boolean holding() {
        return b("inner.holding");
    }

    public boolean contact() {
        return b("inner.contact");
    }

    public double[] jointLimitMargin() {
        return a("inner.jointLimitMargin");
    }

    public boolean selfCollision() {
        return b("inner.selfCollision");
    }

    public boolean envCollision() {
        return b("inner.envCollision");
    }

    public double[] cubePos() {
        return a("external.cubePos");
    }

    public double[] cubeVel() {
        return a("external.cubeVel");
    }

    public double[] padPos() {
        return a("external.padPos");
    }

    public double eefToCube() {
        return d("derived.eefToCube");
    }

    public double cubeToPadXY() {
        return d("derived.cubeToPadXY");
    }

    public double cubeHeight() {
        return d("derived.cubeHeight");
    }

    public double cubeDisplacement() {
        return d("derived.cubeDisplacement");
    }

    public boolean carried() {
        return b("carry.carried");
    }

    public boolean placing() {
        return b("carry.placing");
    }

    public int still() {
        return ((Number) v("carry.still")).intValue();
    }
}
