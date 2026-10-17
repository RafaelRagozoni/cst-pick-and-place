package agent;

import agent.sim.BridgeClient;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;

/**
 * Runs the agent against the simulation bridge, in the two phases of cap4 4.6.2.
 *
 * <pre>
 *   python3 coppelia_environment/bridge.py --log runs/C0_s1.jsonl.gz --condition C0   # CoppeliaSim open
 *   ./gradlew liveRun -PagentArgs="--condition C0 --seed 1 --emax 50 --eref 20 --selection ucb"
 *   python3 coppelia_environment/metrics.py runs/C0_s1.jsonl.gz
 * </pre>
 *
 * Phase 1 (bootstrap) runs with Effort's gain at zero until the first success, at most {@code emax}
 * episodes; Phase 2 (refinement) runs {@code eref} more with it raised. A run with no success in
 * Phase 1 has no Phase 2. Episode indices continue across phases, so the bridge's placements -- a
 * function of (seed, episode) -- are the same for every condition.
 *
 * <p>{@code --selection} (greedy, ucb, ucb:&lt;c&gt;, thompson; default greedy) picks the selection
 * mechanism; every logged step records it and the spread it used. C6 is the random baseline and
 * refuses any other. {@code --curiosity} (none, count, count:&lt;W&gt;, lp, lp:&lt;W&gt;; default none)
 * picks the Curiosity yield; every logged step records it and the yield's value.
 *
 * <p>Checkpoints ({@link Checkpoint}): {@code --checkpoint FILE} saves the agent after every
 * episode, overwriting; {@code --keep-every N} also keeps a copy every N episodes beside it, in
 * {@code checkpoints/after-epNNNNNN.json.gz}; {@code --resume FILE} continues a run from one, with
 * the same condition, selection and seed, from the episode after it -- with a larger
 * {@code --emax}, a run that ended without success goes on looking for one.
 */
public final class AgentMain {

    public static void main(String[] args) {
        Map<String, String> a = parse(args);
        String host = a.getOrDefault("host", "127.0.0.1");
        int port = Integer.parseInt(a.getOrDefault("port", "5555"));
        Config cfg = Config.forCondition(a.getOrDefault("condition", "C0"));
        if (a.containsKey("selection")) {
            cfg.withSelection(a.get("selection"));
        }
        if (a.containsKey("curiosity")) {
            cfg.withCuriosity(a.get("curiosity"));
        }
        int seed = Integer.parseInt(a.getOrDefault("seed", "1"));
        int emax = Integer.parseInt(a.getOrDefault("emax", "50"));
        int eref = Integer.parseInt(a.getOrDefault("eref", "20"));

        Path checkpoint = a.containsKey("checkpoint") ? Path.of(a.get("checkpoint")) : null;
        int keepEvery = Integer.parseInt(a.getOrDefault("keep-every", "0"));

        int status = 0;
        try (BridgeClient bridge = new BridgeClient(host, port, 60000)) {
            JsonObject info = bridge.info();
            checkCondition(info, cfg.condition);
            AgentMind m = new AgentMind(cfg, bridge, seed);
            System.out.printf("agent %s seed %d selection %s curiosity %s: %d habits, step limit %d, "
                    + "log %s%n", cfg.condition, seed, cfg.selection, cfg.curiosityYield,
                    m.pool.getAllMemories().size(),
                    info.get("stepLimit").getAsInt(), str(info.get("log")));

            Checkpoint.Progress at = new Checkpoint.Progress(seed, 0, null);
            if (a.containsKey("resume")) {
                at = Checkpoint.restore(m, Checkpoint.read(Path.of(a.get("resume"))));
                if (at.seed() != seed) {
                    throw new IllegalArgumentException("the checkpoint is of seed " + at.seed()
                            + ", not " + seed + ": the cube placements would not continue");
                }
                System.out.printf("resumed from %s at episode %d, %s%n", a.get("resume"),
                        at.nextEpisode(), at.firstSuccess() == null ? "bootstrap"
                                : "refinement (first success at episode " + at.firstSuccess() + ")");
            }

            int episode = at.nextEpisode();
            Integer first = at.firstSuccess();
            boolean refining = first != null;
            for (; first == null && episode < emax; episode++) {
                AgentMind.EpisodeResult r = m.runEpisode(seed, episode);
                if (r.success()) {
                    first = episode;
                }
                print("bootstrap", r, save(m, seed, episode, first, checkpoint, keepEvery));
            }
            if (first == null) {
                System.out.printf("no success within E_max = %d episodes: no refinement phase%n", emax);
            } else {
                if (!refining) {
                    System.out.printf("first success at episode %d; refinement for %d episodes%n",
                            first, eref);
                    m.enterRefinement();
                }
                for (; episode <= first + eref; episode++) {
                    AgentMind.EpisodeResult r = m.runEpisode(seed, episode);
                    print("refinement", r, save(m, seed, episode, first, checkpoint, keepEvery));
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

    /** Checkpoint after {@code episode}, if asked; returns the milliseconds it took (-1: none). */
    private static long save(AgentMind m, int seed, int episode, Integer first, Path checkpoint,
                             int keepEvery) {
        if (checkpoint == null) {
            return -1;
        }
        long t0 = System.nanoTime();
        Checkpoint.write(Checkpoint.of(m, new Checkpoint.Progress(seed, episode + 1, first)),
                checkpoint);
        if (keepEvery > 0 && (episode + 1) % keepEvery == 0) {
            Path kept = checkpoint.resolveSibling("checkpoints")
                    .resolve(String.format("after-ep%06d.json.gz", episode));
            try {
                Files.createDirectories(kept.getParent());
                Files.copy(checkpoint, kept, StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException e) {
                throw new UncheckedIOException("cannot keep checkpoint " + kept, e);
            }
        }
        return (System.nanoTime() - t0) / 1_000_000;
    }

    private static void print(String phase, AgentMind.EpisodeResult r, long checkpointMs) {
        System.out.printf("  %-10s ep %3d  steps %4d  success %-5s  goals %s  pool %d%s%n", phase,
                r.episode(), r.steps(), r.success(), r.goalsMet(), r.poolSize(),
                checkpointMs < 0 ? "" : "  checkpoint " + checkpointMs + " ms");
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
