package agent.credit;

import agent.motivation.Drives;

import java.util.Collections;
import java.util.Map;

/**
 * One habit's credit, frozen: what the HabitLearner copies into the HabitPool member and the
 * Behavior Generator reads (cap4 4.3.5).
 *
 * <p>Credit is a vector over the drives, kept as a total and per context (goal, state), each as a
 * sum of credited drive changes and a count of executions. {@link #value} returns c(h | g, s), or
 * the total where the habit has no record under that context yet.
 */
public final class CreditSnapshot {

    /** How the stored sums are read at selection. See Config.creditRead. */
    public enum Read {
        /** Credit per execution: sum / executions. */
        MEAN,
        /** The accumulated sum, as cap4 4.3.4 words it. */
        SUM
    }

    public static final CreditSnapshot EMPTY = new CreditSnapshot(new double[Drives.N], 0,
            Collections.emptyMap(), 0, new double[Drives.N][Drives.N]);

    private final double[] totalSum;
    private final long totalCount;
    private final Map<String, CreditTable.Cell> byContext;
    private final long samples;
    private final double[][] scatter;

    CreditSnapshot(double[] totalSum, long totalCount, Map<String, CreditTable.Cell> byContext,
                   long samples, double[][] scatter) {
        this.totalSum = totalSum;
        this.totalCount = totalCount;
        this.byContext = byContext;
        this.samples = samples;
        this.scatter = scatter;
    }

    public long executions() {
        return totalCount;
    }

    /**
     * Executions under this context: 0 where the habit has no record here, however often it ran
     * elsewhere. Not the cell {@link #value} reads, which falls back to the total: the score may
     * borrow the habit's record elsewhere, but how much is known about the habit HERE is what UCB
     * and Thompson weigh. Returning the total here gave a habit tried once in a bin the largest
     * bonus there, and the 2026-10-15 baseline repeated such a habit in 99% of its choices.
     */
    public long count(String context) {
        CreditTable.Cell c = byContext.get(context);
        return c != null ? c.count : 0;
    }

    /** Finished executions, each one sample of a single execution's credit. */
    public long samples() {
        return samples;
    }

    /**
     * The standard deviation of one execution's score sum_d w_d * credit_d, pooled over the habits:
     * the within-habit covariance of per-execution credit, sum of scatters over sum of (n - 1), read
     * through the weights. 0 until some habit has two finished executions. One scale for the whole
     * pool, so a habit with few samples borrows it from the rest.
     */
    public static double spread(Iterable<CreditSnapshot> pool, double[] weights) {
        double[][] s = new double[Drives.N][Drives.N];
        long dof = 0;
        for (CreditSnapshot c : pool) {
            if (c.samples < 2) {
                continue;
            }
            dof += c.samples - 1;
            for (int i = 0; i < Drives.N; i++) {
                for (int j = 0; j < Drives.N; j++) {
                    s[i][j] += c.scatter[i][j];
                }
            }
        }
        if (dof == 0) {
            return 0.0;
        }
        double v = 0.0;
        for (int i = 0; i < Drives.N; i++) {
            for (int j = 0; j < Drives.N; j++) {
                v += weights[i] * s[i][j] * weights[j];
            }
        }
        return Math.sqrt(Math.max(0.0, v / dof));
    }

    public boolean hasContext(String context) {
        return byContext.containsKey(context);
    }

    public int contexts() {
        return byContext.size();
    }

    /** c(h | context) per drive, or the total when the context has no record. */
    public double[] value(String context, Read read) {
        CreditTable.Cell c = byContext.get(context);
        return c != null ? read(c.sum, c.count, read) : total(read);
    }

    public double[] total(Read read) {
        return read(totalSum, totalCount, read);
    }

    private static double[] read(double[] sum, long count, Read read) {
        if (read == Read.SUM || count <= 1) {
            return sum.clone();
        }
        double[] v = new double[sum.length];
        for (int d = 0; d < v.length; d++) {
            v[d] = sum[d] / count;
        }
        return v;
    }
}
