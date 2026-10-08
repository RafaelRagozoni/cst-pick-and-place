import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

/**
 * Java client for the CoppeliaSim simulation bridge (BRG-02).
 *
 * <p>This is the class the CST side uses. The Motor codelet calls {@link #step} with the cycle's
 * command records; the Sensory codelet reads the returned observation. One request per control cycle -- the
 * bridge applies the records, advances the simulation exactly once, and replies. CST drives the
 * clock.
 *
 * <p>Dependencies are two plain jars, both available from Maven Central, so a Gradle build needs
 * only:
 * <pre>
 *   implementation 'org.zeromq:jeromq:0.5.4'
 *   implementation 'com.google.code.gson:gson:2.11.0'
 * </pre>
 * jeromq is pure Java -- no native library, no code generation, nothing to build. That is the whole
 * reason this transport was chosen over CoppeliaSim's own Java client (DEC-03).
 *
 * <p><b>Threading.</b> A ZeroMQ REQ socket is strictly one request, one reply, and is not safe to
 * use from two threads at once -- a second send while a reply is outstanding throws
 * "Operation cannot be accomplished in current state". CST codelets each run on their own thread,
 * so {@link #call} is synchronized: sharing one client across codelets is then safe, though the
 * cycle is still strictly serialised (which is what a synchronous simulation wants anyway).
 */
public class BridgeClient implements AutoCloseable {

    private final ZContext ctx;
    private final ZMQ.Socket sock;
    private final Gson gson = new Gson();

    public BridgeClient(String host, int port, int timeoutMs) {
        ctx = new ZContext();
        sock = ctx.createSocket(SocketType.REQ);
        sock.setReceiveTimeOut(timeoutMs);
        sock.setLinger(0);
        sock.connect("tcp://" + host + ":" + port);
    }

    /** Send one request, get one reply. Throws if the bridge reports failure or does not answer. */
    public synchronized JsonObject call(JsonObject req) {
        sock.send(req.toString());
        String raw = sock.recvStr();
        if (raw == null) {
            throw new IllegalStateException("bridge did not reply within the timeout");
        }
        JsonObject rep = gson.fromJson(raw, JsonObject.class);
        if (!rep.has("ok") || !rep.get("ok").getAsBoolean()) {
            throw new IllegalStateException(
                    "bridge error: " + (rep.has("error") ? rep.get("error").getAsString() : raw));
        }
        return rep;
    }

    private JsonObject op(String name) {
        JsonObject o = new JsonObject();
        o.addProperty("op", name);
        return o;
    }

    public JsonObject ping() {
        return call(op("ping"));
    }

    public JsonObject info() {
        return call(op("info"));
    }

    public JsonObject reset(int seed, int episode) {
        JsonObject o = op("reset");
        o.addProperty("seed", seed);
        o.addProperty("episode", episode);
        return call(o);
    }

    /** Apply one cycle's command records and advance the simulation once. */
    public JsonObject step(JsonArray records) {
        JsonObject o = op("step");
        o.add("records", records);
        return call(o);
    }

    public void shutdown() {
        call(op("shutdown"));
    }

    /**
     * A MOVE record, in cap4's record schema: rotate one joint by {@code angle} radians (signed,
     * relative to where the step started; on the wire, the angle still to go) at {@code speed}
     * rad/s (a magnitude). See actions.py for the full contract.
     */
    public static JsonObject move(int joint, double angle, double speed) {
        JsonObject r = new JsonObject();
        r.addProperty("action", "MOVE");
        r.addProperty("joint", joint);
        r.addProperty("angle", angle);
        r.addProperty("speed", speed);
        r.addProperty("force", 20.0);
        r.addProperty("step", 0);
        return r;
    }

    /** A GRAB record. Negative force expresses release, per cap4 4.4.1. */
    public static JsonObject grab(boolean opening) {
        JsonObject r = new JsonObject();
        r.addProperty("action", "GRAB");
        r.addProperty("joint", -1);
        r.addProperty("angle", 0.0);
        r.addProperty("speed", 0.0);
        r.addProperty("force", opening ? -20.0 : 20.0);
        r.addProperty("step", 0);
        return r;
    }

    @Override
    public void close() {
        sock.close();
        ctx.close();
    }
}
