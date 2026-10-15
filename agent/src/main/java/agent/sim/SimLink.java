package agent.sim;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/**
 * The one connection to the simulator, shared by the two codelets cap4 4.2 says touch it: the Motor
 * sends a cycle's commands through it, the Sensory reads the resulting observation from it.
 *
 * <p>The bridge is request-reply, so the observation arrives as the reply to the Motor's step. This
 * keeps it until the Sensory codelet reads it on the next cycle. It also numbers the cycles: one per
 * reply, monotonic over the whole run, which is the clock the drives' decays and the credit traces
 * run on.
 */
public final class SimLink {

    private final Environment env;
    private JsonObject latest;
    private long cycle = -1;
    private int episode = -1;

    public SimLink(Environment env) {
        this.env = env;
    }

    public JsonObject info() {
        return env.info();
    }

    public JsonObject reset(int seed, int episode) {
        this.episode = episode;
        latest = env.reset(seed, episode);
        cycle++;
        return latest;
    }

    public JsonObject step(JsonArray records, JsonObject annotate) {
        if (done()) {
            throw new IllegalStateException("episode is over: reset first");
        }
        latest = env.step(records, annotate);
        cycle++;
        return latest;
    }

    /** The most recent reply: {obs, success, done, step, ...}. */
    public JsonObject latest() {
        return latest;
    }

    public long cycle() {
        return cycle;
    }

    /** Continue the numbering of a run resumed from a checkpoint: the next reply is cycle + 1. */
    public void resumeAt(long cycle) {
        if (latest != null) {
            throw new IllegalStateException("resume a run before its first reset, not after");
        }
        this.cycle = cycle;
    }

    public int episode() {
        return episode;
    }

    public boolean episodeStart() {
        return latest != null && latest.get("step").getAsInt() == 0;
    }

    public boolean done() {
        return latest != null && latest.get("done").getAsBoolean();
    }

    public boolean success() {
        return latest != null && latest.get("success").getAsBoolean();
    }
}
