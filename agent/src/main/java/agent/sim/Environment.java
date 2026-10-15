package agent.sim;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/**
 * The bridge's protocol (coppelia_environment/bridge_client.py) as the agent needs it. BridgeClient
 * speaks it over ZeroMQ to the real simulator; tests substitute a kinematic stand-in.
 *
 * <p>Replies are the bridge's: {@code reset} and {@code step} return {obs, success, done, step, ...}.
 */
public interface Environment {

    /** {primitives, goalSteps, stepLimit, physics, log, condition}. */
    JsonObject info();

    JsonObject reset(int seed, int episode);

    /** Apply one cycle's records, advance exactly one simulation step. */
    JsonObject step(JsonArray records, JsonObject annotate);
}
