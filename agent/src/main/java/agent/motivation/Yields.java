package agent.motivation;

import agent.Checkpoint;
import agent.sim.Observation;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;

/**
 * The Curiosity yields, by name in {@link agent.Config#curiosityYield} and on the command line
 * ({@code --curiosity}): none, count, count:&lt;W&gt;, lp, lp:&lt;W&gt;.
 *
 * <p>count and lp both turn a per-cycle signal x in [0, 1] into y by an exponential running mean
 * over W cycles, y += (x - y) / W, starting at y = 1 (nothing known yet). They differ in x:
 * <ul>
 *   <li>count: 1 / sqrt(E), E the times the agent has entered the current bin in its whole life --
 *       the count-based bonus of MBIE-EB (Strehl and Littman 2008) and #Exploration (Tang et al.
 *       2017), whose state hash the bins already are.</li>
 *   <li>lp: the learning progress of IAC (Oudeyer, Kaplan and Hafner 2007) in the current bin: how
 *       fast the error of predicting a habit's effect there is falling.</li>
 * </ul>
 */
public final class Yields {

    /** Cycles in y's running mean: ~5 episodes, the order of the visit counts' half-life. */
    public static final double DEFAULT_WINDOW = 2500.0;
    /** lp: a bin's progress compares the mean of its last K prediction errors with the K before. */
    public static final int LP_HISTORY = 10;
    /**
     * lp: an error this small, in bins (0.05 mm of hand position), is a perfect prediction. Without
     * it a learned effect's errors are rounding noise (~1e-17), and the relative fall of noise is
     * anywhere in [0, 1].
     */
    public static final double LP_FLOOR = 1e-3;

    private Yields() {
    }

    /** The yield a name stands for. A fresh one per call: each holds one mind's history. */
    public static CuriosityYield byName(String name) {
        int colon = name.indexOf(':');
        String kind = colon < 0 ? name : name.substring(0, colon);
        double window = DEFAULT_WINDOW;
        if (colon >= 0) {
            try {
                window = Double.parseDouble(name.substring(colon + 1));
            } catch (NumberFormatException e) {
                window = Double.NaN;
            }
            if (!(window >= 1) || Double.isInfinite(window) || kind.equals("none")) {
                throw new IllegalArgumentException(kind + ":<W> needs a finite window W >= 1 cycle, got "
                        + name);
            }
        }
        return switch (kind) {
            case "none" -> new None();
            case "count" -> new Count(window);
            case "lp" -> new LearningProgress(window, LP_HISTORY);
            default -> throw new IllegalArgumentException("unknown curiosity yield '" + name
                    + "': none, count, count:<W>, lp, lp:<W>");
        };
    }

    /** y = 1 always: the Curiosity of cap4 as written, boredom alone. */
    static final class None implements CuriosityYield {

        @Override
        public double observe(Observation o, String bin, double[] b, String habit) {
            return 1.0;
        }

        @Override
        public JsonObject state() {
            return new JsonObject();
        }

        @Override
        public void restore(JsonObject s) {
        }
    }

    /** The running mean both measures share. */
    abstract static class Averaged implements CuriosityYield {

        private final double window;
        private double y = 1.0;

        Averaged(double window) {
            this.window = window;
        }

        double average(double x) {
            y += (x - y) / window;
            return y;
        }

        JsonObject state(JsonObject s) {
            s.addProperty("y", y);
            return s;
        }

        void restoreY(JsonObject s) {
            y = s.get("y").getAsDouble();
        }
    }

    /**
     * x = 1 / sqrt(entries into the current bin, ever). Entries, not cycles: an execution moves the
     * hand ~0.2 cm and a bin is 5 cm, so the agent spends ~25 cycles in a bin it crosses, and
     * counting cycles would make a bin never seen before worth 1/5 on its first crossing. The counts
     * never decay; the archive's per-cycle counts, which do, are boredom's business.
     */
    static final class Count extends Averaged {

        private final Map<String, Long> entries = new HashMap<>();
        private String last;

        Count(double window) {
            super(window);
        }

        @Override
        public double observe(Observation o, String bin, double[] b, String habit) {
            if (o.episodeStart()) {
                last = null;                    // the reset puts the arm somewhere: an entry
            }
            if (!bin.equals(last)) {
                entries.merge(bin, 1L, Long::sum);
            }
            last = bin;
            return average(1.0 / Math.sqrt(entries.get(bin)));
        }

        @Override
        public JsonObject state() {
            JsonObject e = new JsonObject();
            for (Map.Entry<String, Long> x : entries.entrySet()) {
                e.addProperty(x.getKey(), x.getValue());
            }
            JsonObject s = new JsonObject();
            s.add("entries", e);
            return state(s);
        }

        @Override
        public void restore(JsonObject s) {
            entries.clear();
            for (Map.Entry<String, JsonElement> x : s.getAsJsonObject("entries").entrySet()) {
                entries.put(x.getKey(), x.getValue().getAsLong());
            }
            restoreY(s);
        }
    }

    /**
     * x = the learning progress of the current bin, IAC with the bins as its regions (R-IAC splits
     * regions adaptively; here they are fixed).
     *
     * <p>A model of each habit's effect in each bin: the mean change of the characterization vector
     * b the habit produced starting from that bin, 0 before it has run there. Each cycle, the
     * transition just made -- from last cycle's bin, by the habit that ran -- is predicted by that
     * mean, its error |change - mean| joins the bin's last 2K errors, and then the mean is updated.
     * A bin's progress is how much the mean of its last K errors fell below the mean of the K before,
     * relative to that: max(0, older - recent) / (older + LP_FLOOR), in [0, 1). A bin with fewer than
     * 2K errors has 1: not yet judged, worth going to.
     *
     * <p>An effect learned (arm moving in free space) and an effect that cannot be learned (contact
     * noise, which Bullet varies from process to process) both leave the error flat, so both have
     * progress 0: the "noisy TV" that prediction-error curiosity (ICM) gets stuck on is not a trap
     * here. The transition across a reset and cycles with no habit in execution are not effects.
     */
    static final class LearningProgress extends Averaged {

        private final int k;
        /** "bin|habit" -> {n, mean change per dimension}. */
        private final Map<String, double[]> effects = new HashMap<>();
        /** bin -> its last 2K prediction errors, oldest first. */
        private final Map<String, ArrayDeque<Double>> errors = new HashMap<>();
        private String lastBin;
        private double[] lastB;

        LearningProgress(double window, int k) {
            super(window);
            this.k = k;
        }

        @Override
        public double observe(Observation o, String bin, double[] b, String habit) {
            if (!o.episodeStart() && lastBin != null && habit != null) {
                learn(lastBin, habit, lastB, b);
            }
            lastBin = bin;
            lastB = b.clone();
            return average(progress(bin));
        }

        private void learn(String from, String habit, double[] before, double[] after) {
            double[] m = effects.computeIfAbsent(from + "|" + habit, key -> new double[1 + before.length]);
            double n = m[0] + 1.0;
            double sq = 0.0;
            for (int i = 0; i < before.length; i++) {
                double change = after[i] - before[i];
                double miss = change - m[1 + i];
                sq += miss * miss;
                m[1 + i] += miss / n;
            }
            m[0] = n;
            ArrayDeque<Double> e = errors.computeIfAbsent(from, key -> new ArrayDeque<>(2 * k + 1));
            e.addLast(Math.sqrt(sq));
            if (e.size() > 2 * k) {
                e.removeFirst();
            }
        }

        /** The bin's learning progress, in [0, 1); 1 while it has fewer than 2K errors. */
        double progress(String bin) {
            ArrayDeque<Double> e = errors.get(bin);
            if (e == null || e.size() < 2 * k) {
                return 1.0;
            }
            double older = 0.0;
            double recent = 0.0;
            int i = 0;
            for (double x : e) {
                if (i++ < k) {
                    older += x;
                } else {
                    recent += x;
                }
            }
            older /= k;
            recent /= k;
            return Math.max(0.0, older - recent) / (older + LP_FLOOR);
        }

        @Override
        public JsonObject state() {
            JsonObject fx = new JsonObject();
            for (Map.Entry<String, double[]> x : effects.entrySet()) {
                fx.add(x.getKey(), Checkpoint.array(x.getValue()));
            }
            JsonObject er = new JsonObject();
            for (Map.Entry<String, ArrayDeque<Double>> x : errors.entrySet()) {
                JsonArray a = new JsonArray(x.getValue().size());
                x.getValue().forEach(a::add);
                er.add(x.getKey(), a);
            }
            JsonObject s = new JsonObject();
            s.add("effects", fx);
            s.add("errors", er);
            return state(s);
        }

        @Override
        public void restore(JsonObject s) {
            effects.clear();
            for (Map.Entry<String, JsonElement> x : s.getAsJsonObject("effects").entrySet()) {
                effects.put(x.getKey(), Checkpoint.doubles(x.getValue()));
            }
            errors.clear();
            for (Map.Entry<String, JsonElement> x : s.getAsJsonObject("errors").entrySet()) {
                ArrayDeque<Double> e = new ArrayDeque<>(2 * k + 1);
                for (double v : Checkpoint.doubles(x.getValue())) {
                    e.addLast(v);
                }
                errors.put(x.getKey(), e);
            }
            restoreY(s);
        }
    }
}
