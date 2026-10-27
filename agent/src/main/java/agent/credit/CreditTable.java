package agent.credit;

import agent.Checkpoint;
import agent.motivation.Drives;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Accumulated per-drive credit, the content of CreditMO (cap4 4.3.4). Written only by Credit
 * Assignment; the HabitLearner reads the habits marked dirty and copies their snapshots into the
 * HabitPool.
 *
 * <p>Credit is never collapsed here: every cell keeps one sum per drive (late fusion). Collapsing
 * into one score happens only in the Behavior Generator, weighted by the drive levels of the moment.
 */
public final class CreditTable {

    static final class Cell {
        final double[] sum = new double[Drives.N];
        long count;

        Cell copy() {
            Cell c = new Cell();
            System.arraycopy(sum, 0, c.sum, 0, sum.length);
            c.count = count;
            return c;
        }

        JsonObject state() {
            JsonObject s = new JsonObject();
            s.add("sum", Checkpoint.array(sum));
            s.addProperty("count", count);
            return s;
        }

        static Cell of(JsonObject s) {
            Cell c = new Cell();
            System.arraycopy(Checkpoint.doubles(s.get("sum")), 0, c.sum, 0, Drives.N);
            c.count = s.get("count").getAsLong();
            return c;
        }
    }

    /**
     * The credit of each finished execution of one habit, as running statistics (Welford): how much
     * one execution's credit varies, which is what UCB and Thompson need to know how far to trust a
     * mean. An execution's credit keeps arriving through its trace after it ends, so it is one sample
     * only once it is complete: when the habit runs again (its trace restarts) or the episode ends.
     */
    static final class Samples {
        long n;
        final double[] mean = new double[Drives.N];
        /** Sum of outer products of deviations from the mean: covariance * (n - 1). */
        final double[][] scatter = new double[Drives.N][Drives.N];

        void add(double[] x) {
            n++;
            double[] before = new double[Drives.N];
            for (int d = 0; d < Drives.N; d++) {
                before[d] = x[d] - mean[d];
                mean[d] += before[d] / n;
            }
            for (int i = 0; i < Drives.N; i++) {
                for (int j = 0; j < Drives.N; j++) {
                    scatter[i][j] += before[i] * (x[j] - mean[j]);
                }
            }
        }

        double[][] scatterCopy() {
            double[][] c = new double[Drives.N][];
            for (int i = 0; i < Drives.N; i++) {
                c[i] = scatter[i].clone();
            }
            return c;
        }
    }

    private static final class Row {
        final Cell total = new Cell();
        final Map<String, Cell> byContext = new HashMap<>();
        /** The same credit under each middle context (#middleContext), what a context borrows. */
        final Map<String, Cell> byMiddle = new HashMap<>();
        final Samples samples = new Samples();
        /** Credit of the execution still receiving it, or null. */
        double[] open;
    }

    private final Map<String, Row> rows = new LinkedHashMap<>();
    private final Set<String> dirty = new LinkedHashSet<>();
    private long version;

    /** The context key credit is recorded under: goal g and state bin s. */
    public static String context(String goal, String stateKey) {
        return goal + "|" + stateKey;
    }

    /**
     * The coarser context a context borrows from (vault spec CRE-01): the same goal, and whether the
     * hand holds the cube -- Characterization.key's "h" flag, read back from the key, so nothing new
     * travels from the Behavior Generator to here. With the Task holding the goal, the goal is the
     * stage, so "transport, holding" sets opening on the way apart from "release, holding". A
     * context with no such flag (hand-made in a test) is its own middle.
     */
    public static String middleContext(String context) {
        int bar = context.indexOf('|');
        if (bar < 0) {
            return context;
        }
        int holdingFlag = context.indexOf('h', bar + 1);
        if (holdingFlag < 0 || holdingFlag + 1 >= context.length()) {
            return context;
        }
        return context.substring(0, bar) + "|h" + context.charAt(holdingFlag + 1);
    }

    /**
     * Credit {@code weight * delta} to the habit under {@code context}. {@code execution} marks the
     * start of one execution of the habit, which is what the per-execution mean divides by.
     */
    public void add(String habit, String context, double[] delta, double weight, boolean execution) {
        Row r = rows.computeIfAbsent(habit, h -> new Row());
        Cell c = r.byContext.computeIfAbsent(context, k -> new Cell());
        Cell middle = r.byMiddle.computeIfAbsent(middleContext(context), k -> new Cell());
        for (int d = 0; d < Drives.N; d++) {
            r.total.sum[d] += weight * delta[d];
            c.sum[d] += weight * delta[d];
            middle.sum[d] += weight * delta[d];
        }
        if (execution) {
            r.total.count++;
            c.count++;
            middle.count++;
            close(r);
            r.open = new double[Drives.N];
        }
        if (r.open != null) {
            for (int d = 0; d < Drives.N; d++) {
                r.open[d] += weight * delta[d];
            }
        }
        dirty.add(habit);
        version++;
    }

    /** The episode ended: no more credit reaches any execution in it, so each one is a sample. */
    public void closeExecutions() {
        for (Map.Entry<String, Row> e : rows.entrySet()) {
            if (e.getValue().open != null) {
                close(e.getValue());
                dirty.add(e.getKey());
                version++;
            }
        }
    }

    private static void close(Row r) {
        if (r.open != null) {
            r.samples.add(r.open);
            r.open = null;
        }
    }

    public CreditSnapshot snapshot(String habit) {
        Row r = rows.get(habit);
        if (r == null) {
            return CreditSnapshot.EMPTY;
        }
        return new CreditSnapshot(r.total.sum.clone(), r.total.count, copy(r.byContext),
                copy(r.byMiddle), r.samples.n, r.samples.mean.clone(), r.samples.scatterCopy());
    }

    private static Map<String, Cell> copy(Map<String, Cell> cells) {
        Map<String, Cell> out = new HashMap<>(cells.size() * 2);
        for (Map.Entry<String, Cell> e : cells.entrySet()) {
            out.put(e.getKey(), e.getValue().copy());
        }
        return out;
    }

    /** Habits whose credit changed since the last call; clears the set. */
    public Set<String> drainDirty() {
        Set<String> out = new LinkedHashSet<>(dirty);
        dirty.clear();
        return out;
    }

    public long version() {
        return version;
    }

    public Set<String> habits() {
        return rows.keySet();
    }

    /** Everything, for a checkpoint. Only between episodes: an open execution is mid-credit. */
    public JsonObject state() {
        JsonObject out = new JsonObject();
        for (Map.Entry<String, Row> e : rows.entrySet()) {
            Row r = e.getValue();
            if (r.open != null) {
                throw new IllegalStateException(e.getKey() + " has an execution still receiving "
                        + "credit: checkpoint between episodes");
            }
            JsonObject contexts = new JsonObject();
            for (Map.Entry<String, Cell> c : r.byContext.entrySet()) {
                contexts.add(c.getKey(), c.getValue().state());
            }
            // Saved, not summed again from the contexts on restore: a sum in another order is
            // another double, and the resumed run would part from the one that never stopped.
            JsonObject middles = new JsonObject();
            for (Map.Entry<String, Cell> c : r.byMiddle.entrySet()) {
                middles.add(c.getKey(), c.getValue().state());
            }
            JsonArray scatter = new JsonArray();
            for (double[] row : r.samples.scatter) {
                scatter.add(Checkpoint.array(row));
            }
            JsonObject samples = new JsonObject();
            samples.addProperty("n", r.samples.n);
            samples.add("mean", Checkpoint.array(r.samples.mean));
            samples.add("scatter", scatter);
            JsonObject row = new JsonObject();
            row.add("total", r.total.state());
            row.add("contexts", contexts);
            row.add("middles", middles);
            row.add("samples", samples);
            out.add(e.getKey(), row);
        }
        JsonObject s = new JsonObject();
        s.addProperty("version", version);
        s.add("rows", out);
        return s;
    }

    public void restore(JsonObject s) {
        rows.clear();
        dirty.clear();
        for (Map.Entry<String, JsonElement> e : s.getAsJsonObject("rows").entrySet()) {
            JsonObject row = e.getValue().getAsJsonObject();
            Row r = new Row();
            Cell total = Cell.of(row.getAsJsonObject("total"));
            System.arraycopy(total.sum, 0, r.total.sum, 0, Drives.N);
            r.total.count = total.count;
            for (Map.Entry<String, JsonElement> c : row.getAsJsonObject("contexts").entrySet()) {
                r.byContext.put(c.getKey(), Cell.of(c.getValue().getAsJsonObject()));
            }
            for (Map.Entry<String, JsonElement> c : row.getAsJsonObject("middles").entrySet()) {
                r.byMiddle.put(c.getKey(), Cell.of(c.getValue().getAsJsonObject()));
            }
            JsonObject samples = row.getAsJsonObject("samples");
            r.samples.n = samples.get("n").getAsLong();
            System.arraycopy(Checkpoint.doubles(samples.get("mean")), 0, r.samples.mean, 0, Drives.N);
            JsonArray scatter = samples.getAsJsonArray("scatter");
            for (int i = 0; i < Drives.N; i++) {
                System.arraycopy(Checkpoint.doubles(scatter.get(i)), 0, r.samples.scatter[i], 0,
                        Drives.N);
            }
            rows.put(e.getKey(), r);
        }
        version = s.get("version").getAsLong();
    }
}
