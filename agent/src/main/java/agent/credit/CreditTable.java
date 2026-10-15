package agent.credit;

import agent.motivation.Drives;

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
     * Credit {@code weight * delta} to the habit under {@code context}. {@code execution} marks the
     * start of one execution of the habit, which is what the per-execution mean divides by.
     */
    public void add(String habit, String context, double[] delta, double weight, boolean execution) {
        Row r = rows.computeIfAbsent(habit, h -> new Row());
        Cell c = r.byContext.computeIfAbsent(context, k -> new Cell());
        for (int d = 0; d < Drives.N; d++) {
            r.total.sum[d] += weight * delta[d];
            c.sum[d] += weight * delta[d];
        }
        if (execution) {
            r.total.count++;
            c.count++;
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
        Map<String, Cell> ctx = new HashMap<>(r.byContext.size() * 2);
        for (Map.Entry<String, Cell> e : r.byContext.entrySet()) {
            ctx.put(e.getKey(), e.getValue().copy());
        }
        return new CreditSnapshot(r.total.sum.clone(), r.total.count, ctx, r.samples.n,
                r.samples.scatterCopy());
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
}
