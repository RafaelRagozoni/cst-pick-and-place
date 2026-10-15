package agent;

import agent.habit.Command;
import agent.sim.Environment;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;

/**
 * A kinematic stand-in for the bridge, so the whole mind can run in a unit test.
 *
 * <p>It speaks the bridge's protocol and produces observations with every field observations.py
 * does, from a crude model: joints track their commanded velocity exactly (actions.tick_velocity and
 * limit_velocity), the end-effector is a three-link forward kinematics of joints 0-2, the gripper
 * moves 2.5 mm per tick, and the cube attaches when the gripper closes on it. It is not a physics
 * check of anything -- only a source of plausible, deterministic observations.
 */
public final class FakeEnvironment implements Environment {

    static final double DT = 0.05;
    static final double LIMIT = Math.PI;
    static final double TABLE = 0.72;
    static final double[] HOME = {0.0, -0.3, 0.9, 0.0, 0.0, 0.0};
    static final double OPEN = 0.1054;
    static final double CLOSED = 0.0045;
    static final double ON_CUBE = 0.05;

    private final int stepLimit;
    private double[] q;
    private double[] qd = new double[6];
    private double width;
    private boolean commandedOpen;
    private boolean holding;
    private double[] cube;
    private double[] prevCube;
    private final double[] pad = {0.4, 0.4, 0.723};
    private int steps;
    private double t;
    private boolean done;

    /** Every step's records and annotation, in order, for assertions. */
    public final List<JsonArray> records = new ArrayList<>();
    public final List<JsonObject> annotations = new ArrayList<>();
    public int resets;

    public FakeEnvironment(int stepLimit) {
        this.stepLimit = stepLimit;
    }

    @Override
    public JsonObject info() {
        JsonObject info = new JsonObject();
        JsonArray prims = new JsonArray();
        List<Command> recs = new ArrayList<>();
        for (int j = 0; j < 6; j++) {
            for (int d : new int[]{1, -1}) {
                recs.add(new Command(Command.MOVE, j, d * Math.toRadians(1.0), 0.4, 20.0, 0));
            }
        }
        recs.add(new Command(Command.GRAB, -1, 0.0, 0.0, -20.0, 0));
        recs.add(new Command(Command.GRAB, -1, 0.0, 0.0, 20.0, 0));
        for (Command c : recs) {
            JsonObject p = new JsonObject();
            p.addProperty("id", c.recordId());
            JsonArray r = new JsonArray();
            r.add(c.toJson());
            p.add("records", r);
            prims.add(p);
        }
        info.add("primitives", prims);
        info.addProperty("stepLimit", stepLimit);
        info.add("log", null);
        info.add("condition", null);
        return info;
    }

    @Override
    public JsonObject reset(int seed, int episode) {
        resets++;
        q = HOME.clone();
        qd = new double[6];
        width = OPEN;
        commandedOpen = true;
        holding = false;
        // The cube's position depends on (seed, episode) only, as the bridge's placements do.
        java.util.Random r = new java.util.Random(seed * 1000003L + episode);
        cube = new double[]{0.6 + 0.05 * r.nextDouble(), 0.05 + 0.05 * r.nextDouble(), TABLE + 0.025};
        prevCube = cube.clone();
        steps = 0;
        t = 0.0;
        done = false;
        return reply(false);
    }

    @Override
    public JsonObject step(JsonArray recs, JsonObject annotate) {
        if (done) {
            throw new IllegalStateException("no episode in progress: reset first");
        }
        records.add(recs);
        annotations.add(annotate);
        double[] vel = new double[6];
        for (JsonElement e : recs) {
            Command c = Command.fromJson(e.getAsJsonObject());
            if (c.isMove()) {
                double v = Math.copySign(Math.min(Math.abs(c.speed()), Math.abs(c.angle()) / DT),
                        c.angle());
                int j = c.joint();
                if (v > 0) {
                    v = Math.max(0.0, Math.min(v, (LIMIT - q[j]) / DT));
                } else if (v < 0) {
                    v = Math.min(0.0, Math.max(v, (-LIMIT - q[j]) / DT));
                }
                vel[j] = v;
            } else if (c.isGrab()) {
                commandedOpen = c.force() < 0;
            }
        }
        for (int j = 0; j < 6; j++) {
            q[j] += vel[j] * DT;
        }
        qd = vel;
        double target = commandedOpen ? OPEN : (holding ? ON_CUBE : CLOSED);
        width += Math.max(-0.0025, Math.min(0.0025, target - width));

        double[] eef = eef();
        prevCube = cube.clone();
        if (!commandedOpen && !holding && dist(eef, cube) < 0.05 && width <= ON_CUBE + 0.005) {
            holding = true;
        }
        if (commandedOpen) {
            holding = false;
        }
        if (holding) {
            cube = eef.clone();
        } else if (cube[2] > TABLE + 0.025) {
            cube[2] = Math.max(TABLE + 0.025, cube[2] - 0.05);
        }
        steps++;
        t += DT;
        boolean success = onPad() && !holding;
        done = success || steps >= stepLimit;
        return reply(success);
    }

    private boolean onPad() {
        return Math.hypot(cube[0] - pad[0], cube[1] - pad[1]) <= 0.05 && cube[2] - TABLE > 0;
    }

    private double[] eef() {
        double l1 = 0.425, l2 = 0.39;
        double r = l1 * Math.cos(q[1]) + l2 * Math.cos(q[1] + q[2]);
        double z = 0.9 + l1 * Math.sin(q[1]) + l2 * Math.sin(q[1] + q[2]);
        return new double[]{r * Math.cos(q[0]), r * Math.sin(q[0]), z};
    }

    private static double dist(double[] a, double[] b) {
        double s = 0;
        for (int i = 0; i < 3; i++) {
            s += (a[i] - b[i]) * (a[i] - b[i]);
        }
        return Math.sqrt(s);
    }

    private static JsonArray arr(double... v) {
        JsonArray a = new JsonArray();
        for (double x : v) {
            a.add(x);
        }
        return a;
    }

    private JsonObject reply(boolean success) {
        double[] eef = eef();
        JsonObject obs = new JsonObject();
        obs.addProperty("t", t);
        JsonObject inner = new JsonObject();
        JsonArray joints = new JsonArray();
        double[] margin = new double[6];
        for (int j = 0; j < 6; j++) {
            JsonObject jo = new JsonObject();
            jo.addProperty("j", j);
            jo.addProperty("pos", q[j]);
            jo.addProperty("vel", qd[j]);
            jo.addProperty("torque", 0.0);
            joints.add(jo);
            margin[j] = LIMIT - Math.abs(q[j]);
        }
        inner.add("joints", joints);
        JsonObject e = new JsonObject();
        e.add("pos", arr(eef));
        e.add("quat", arr(0, 0, 0, 1));
        inner.add("eef", e);
        JsonObject g = new JsonObject();
        g.addProperty("width", width);
        g.addProperty("commanded_open", commandedOpen);
        g.addProperty("isHolding", holding);
        g.add("contactForce", arr(0.4, 0.4));
        g.addProperty("inContact", holding || dist(eef, cube) < 0.04);
        inner.add("gripper", g);
        inner.add("jointLimitMargin", arr(margin));
        inner.addProperty("selfCollision", false);
        inner.addProperty("envCollision", eef[2] < TABLE + 0.02);
        inner.add("manipulability", null);
        obs.add("innerSense", inner);
        JsonObject vision = new JsonObject();
        JsonObject c = new JsonObject();
        c.add("pos", arr(cube));
        c.add("vel", arr((cube[0] - prevCube[0]) / DT, (cube[1] - prevCube[1]) / DT,
                (cube[2] - prevCube[2]) / DT));
        c.addProperty("visible", true);
        vision.add("cube", c);
        JsonObject p = new JsonObject();
        p.add("pos", arr(pad));
        p.addProperty("visible", true);
        vision.add("pad", p);
        obs.add("vision", vision);
        JsonObject d = new JsonObject();
        d.addProperty("eefToCube", dist(eef, cube));
        d.addProperty("cubeToPadXY", Math.hypot(cube[0] - pad[0], cube[1] - pad[1]));
        d.addProperty("cubeHeightAboveTable", cube[2] - TABLE);
        d.addProperty("cubeDisplacement", dist(cube, prevCube));
        obs.add("derived", d);

        JsonObject rep = new JsonObject();
        rep.addProperty("ok", true);
        rep.add("obs", obs);
        rep.addProperty("success", success);
        rep.addProperty("done", done);
        rep.addProperty("step", steps);
        return rep;
    }
}
