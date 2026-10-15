package agent;

import agent.sim.BridgeClient;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.HashMap;
import java.util.Map;

/**
 * Runs the agent against the simulation bridge, in the two phases of cap4 4.6.2.
 *
 * <pre>
 *   python3 coppelia_environment/bridge.py --log runs/C0_s1.jsonl.gz --condition C0   # CoppeliaSim open
 *   ./gradlew liveRun -PagentArgs="--condition C0 --seed 1 --emax 50 --eref 20"
 *   python3 coppelia_environment/metrics.py runs/C0_s1.jsonl.gz
 * </pre>
 *
 * Phase 1 (bootstrap) runs with Effort's gain at zero until the first success, at most {@code emax}
 * episodes; Phase 2 (refinement) runs {@code eref} more with it raised. A run with no success in
 * Phase 1 has no Phase 2. Episode indices continue across phases, so the bridge's placements -- a
 * function of (seed, episode) -- are the same for every condition.
 */
public final class AgentMain {

    public static void main(String[] args) {
        Map<String, String> a = parse(args);
        String host = a.getOrDefault("host", "127.0.0.1");
        int port = Integer.parseInt(a.getOrDefault("port", "5555"));
        Config cfg = Config.forCondition(a.getOrDefault("condition", "C0"));
        int seed = Integer.parseInt(a.getOrDefault("seed", "1"));
        int emax = Integer.parseInt(a.getOrDefault("emax", "50"));
        int eref = Integer.parseInt(a.getOrDefault("eref", "20"));

        int status = 0;
        try (BridgeClient bridge = new BridgeClient(host, port, 60000)) {
            JsonObject info = bridge.info();
            checkCondition(info, cfg.condition);
            AgentMind m = new AgentMind(cfg, bridge, seed);
            System.out.printf("agent %s seed %d: %d habits, step limit %d, log %s%n", cfg.condition,
                    seed, m.pool.getAllMemories().size(), info.get("stepLimit").getAsInt(),
                    str(info.get("log")));

            int episode = 0;
            Integer first = null;
            for (; episode < emax; episode++) {
                AgentMind.EpisodeResult r = m.runEpisode(seed, episode);
                print("bootstrap", r);
                if (r.success()) {
                    first = episode;
                    episode++;
                    break;
                }
            }
            if (first == null) {
                System.out.printf("no success within E_max = %d episodes: no refinement phase%n", emax);
            } else {
                System.out.printf("first success at episode %d; refinement for %d episodes%n", first,
                        eref);
                m.enterRefinement();
                for (int k = 0; k < eref; k++, episode++) {
                    print("refinement", m.runEpisode(seed, episode));
                }
            }
            // The bridge finishes the run log only when it shuts down: a gzip left open is
            // unreadable. One bridge per run, so the run ends it -- unless asked not to.
            if (Boolean.parseBoolean(a.getOrDefault("shutdown", "true"))) {
                bridge.shutdown();
            }
        } catch (RuntimeException e) {
            e.printStackTrace();
            status = 1;
        }
        // CST codelets each own a java.util.Timer thread, which keeps the JVM alive.
        System.exit(status);
    }

    private static void checkCondition(JsonObject info, String condition) {
        JsonElement logged = info.get("condition");
        if (logged != null && !logged.isJsonNull() && !logged.getAsString().equals(condition)) {
            throw new IllegalStateException("the bridge logs condition " + logged.getAsString()
                    + " but the agent runs " + condition + ": the log would be mislabeled");
        }
    }

    private static void print(String phase, AgentMind.EpisodeResult r) {
        System.out.printf("  %-10s ep %3d  steps %4d  success %-5s  goals %s  pool %d%n", phase,
                r.episode(), r.steps(), r.success(), r.goalsMet(), r.poolSize());
    }

    private static String str(JsonElement e) {
        return e == null || e.isJsonNull() ? "none" : e.getAsString();
    }

    private static Map<String, String> parse(String[] args) {
        Map<String, String> m = new HashMap<>();
        for (int i = 0; i < args.length; i++) {
            if (!args[i].startsWith("--") || i + 1 >= args.length) {
                throw new IllegalArgumentException("expected --name value pairs, got " + args[i]);
            }
            m.put(args[i].substring(2), args[++i]);
        }
        return m;
    }
}
