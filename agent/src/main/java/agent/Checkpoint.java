package agent;

import agent.memory.ExecutionBuffer;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Reader;
import java.io.UncheckedIOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.zip.Deflater;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/**
 * Everything a run carries from one episode to the next, saved between episodes so the run can be
 * resumed: the training checkpoint of an ML run (PyTorch's state_dict + optimizer + epoch, YOLO's
 * last.pt). There are no weights here; what the agent has learned is
 * <ul>
 *   <li>the credit table (Credit Assignment), and the credit copied from it into the pool;</li>
 *   <li>the novelty archive and the decaying visit counts (Curiosity);</li>
 *   <li>the Behavior Generator's random generator, mid-sequence;</li>
 *   <li>the counters that number things across the run: cycles, goals, plans, ExecutionBuffer
 *       entries;</li>
 *   <li>where the run stands: next episode, first success (and so the phase).</li>
 * </ul>
 * The rest -- traces, the plan in execution, the goal, buffers -- is reset at every episode start,
 * so a checkpoint is taken only between episodes. The PlanTracker's last plan and goal numbers
 * need no saving either: the numberings they are compared against continue. {@code CheckpointTest}
 * holds a resumed run to the run that never stopped, decision for decision, which is what catches
 * state left out of here.
 *
 * <p>Not saved, and refused rather than resumed wrong: a pool that is not the primary repertoire
 * (WP3's generated habits are not written yet), and a run whose Config differs from the one saved.
 *
 * <p>Format: JSON, gzipped when the path ends in {@code .gz}; readable with {@code zcat | jq}.
 */
public final class Checkpoint {

    public static final int FORMAT = 1;
    private static final Gson GSON = new GsonBuilder().serializeNulls()
            .serializeSpecialFloatingPointValues().create();

    private Checkpoint() {
    }

    /** Where the run stands: the next episode to run, and the episode of the first success. */
    public record Progress(int seed, int nextEpisode, Integer firstSuccess) {
    }

    /** The mind's state after {@code p.nextEpisode() - 1} episodes. Only between episodes. */
    public static JsonObject of(AgentMind m, Progress p) {
        if (!m.link.done()) {
            throw new IllegalStateException("a checkpoint is taken between episodes, not during one");
        }
        JsonObject c = new JsonObject();
        c.addProperty("format", FORMAT);
        c.addProperty("seed", p.seed());
        c.addProperty("nextEpisode", p.nextEpisode());
        c.addProperty("firstSuccess", p.firstSuccess());
        c.add("config", GSON.toJsonTree(m.cfg));
        JsonArray pool = new JsonArray();
        for (String id : m.learner.habits().keySet()) {
            pool.add(id);
        }
        c.add("pool", pool);
        c.addProperty("cycle", m.link.cycle());
        c.addProperty("executionSeq", ((ExecutionBuffer) m.executionMO.getI()).nextSeq());
        c.add("drive", m.drive.state());
        c.add("goal", m.goal.state());
        c.add("credit", m.credit.state());
        c.add("behavior", m.behavior.state());
        return c;
    }

    /**
     * Put a checkpoint into a mind just built and not yet run, and return where the run stands.
     * Refuses a checkpoint from another format, Config or pool.
     */
    public static Progress restore(AgentMind m, JsonObject c) {
        int format = c.get("format").getAsInt();
        if (format != FORMAT) {
            throw new IllegalArgumentException("checkpoint format " + format + ", this agent reads "
                    + FORMAT);
        }
        JsonObject saved = c.getAsJsonObject("config");
        JsonObject now = GSON.toJsonTree(m.cfg).getAsJsonObject();
        if (!saved.equals(now)) {
            List<String> diff = new ArrayList<>();
            Set<String> keys = new TreeSet<>(now.keySet());
            keys.addAll(saved.keySet());
            for (String k : keys) {
                if (!now.get(k).equals(saved.get(k))) {
                    diff.add(k + " " + saved.get(k) + " -> " + now.get(k));
                }
            }
            throw new IllegalArgumentException("the checkpoint was saved with another Config: "
                    + String.join(", ", diff));
        }
        List<String> pool = new ArrayList<>();
        c.getAsJsonArray("pool").forEach(e -> pool.add(e.getAsString()));
        List<String> mine = new ArrayList<>(m.learner.habits().keySet());
        if (!pool.equals(mine)) {
            throw new IllegalArgumentException("the checkpoint's pool (" + pool.size()
                    + " habits) is not this agent's (" + mine.size() + "): another repertoire, or "
                    + "generated habits, which checkpoints do not hold yet (WP3)");
        }

        m.link.resumeAt(c.get("cycle").getAsLong());
        ((ExecutionBuffer) m.executionMO.getI()).resumeAt(c.get("executionSeq").getAsLong());
        m.drive.restore(c.getAsJsonObject("drive"));
        m.goal.restore(c.getAsJsonObject("goal"));
        m.credit.restore(c.getAsJsonObject("credit"));
        m.learner.refreshCredit(m.credit.table());
        m.behavior.restore(c.getAsJsonObject("behavior"));

        JsonElement first = c.get("firstSuccess");
        Progress p = new Progress(c.get("seed").getAsInt(), c.get("nextEpisode").getAsInt(),
                first == null || first.isJsonNull() ? null : first.getAsInt());
        if (p.firstSuccess() != null) {
            m.enterRefinement();
        }
        return p;
    }

    /** Write atomically: a run stopped mid-write leaves the previous checkpoint whole. */
    public static void write(JsonObject c, Path path) {
        Path tmp = path.resolveSibling(path.getFileName() + ".tmp");
        try {
            if (path.getParent() != null) {
                Files.createDirectories(path.getParent());
            }
            OutputStream out = Files.newOutputStream(tmp);
            if (path.toString().endsWith(".gz")) {
                // Fastest level: at 5000 archive points and 70k credit cells a save took 0.44 s, 0.29 s
                // of it the default level; this one takes 0.06 s, for a file 10% larger.
                out = new GZIPOutputStream(out, 1 << 16) {
                    {
                        def.setLevel(Deflater.BEST_SPEED);
                    }
                };
            }
            try (Writer w = new OutputStreamWriter(out, StandardCharsets.UTF_8)) {
                GSON.toJson(c, w);
            }
            Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot write checkpoint " + path, e);
        }
    }

    public static JsonObject read(Path path) {
        try {
            InputStream in = Files.newInputStream(path);
            if (path.toString().endsWith(".gz")) {
                in = new GZIPInputStream(in, 1 << 16);
            }
            try (Reader r = new InputStreamReader(in, StandardCharsets.UTF_8)) {
                return JsonParser.parseReader(r).getAsJsonObject();
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read checkpoint " + path, e);
        }
    }

    // --- helpers for the components' state() / restore() --------------------------------------

    public static JsonArray array(double[] v) {
        JsonArray a = new JsonArray(v.length);
        for (double x : v) {
            a.add(x);
        }
        return a;
    }

    public static double[] doubles(JsonElement e) {
        JsonArray a = e.getAsJsonArray();
        double[] v = new double[a.size()];
        for (int i = 0; i < v.length; i++) {
            v[i] = a.get(i).getAsDouble();
        }
        return v;
    }
}
