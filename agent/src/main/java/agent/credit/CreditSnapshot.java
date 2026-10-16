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
            Collections.emptyMap(), 0, new double[Drives.N], new double[Drives.N][Drives.N]);

    private final double[] totalSum;
    private final long totalCount;
    private final Map<String, CreditTable.Cell> byContext;
    private final long samples;
    private final double[] sampleMean;
    private final double[][] scatter;

    CreditSnapshot(double[] totalSum, long totalCount, Map<String, CreditTable.Cell> byContext,
                   long samples, double[] sampleMean, double[][] scatter) {
        this.totalSum = totalSum;
        this.totalCount = totalCount;
        this.byContext = byContext;
        this.samples = samples;
        this.sampleMean = sampleMean;
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
     * The spread every habit starts from: how much one execution's score sum_d w_d * credit_d varies
     * across the repertoire -- the standard deviation of the equal-weight mixture of the habits'
     * finished executions (each habit's spread around its own mean, plus how far its mean sits from
     * the others'). Every habit counts once however often it ran, so one habit repeated thousands of
     * times cannot set the scale for the rest: pooled by executions, a no-op repeated 4978 times set
     * it to ~0 and UCB stopped retrying the habits tried once (2026-10-16). 0 until some habit has a
     * finished execution, and while every habit's results are the same.
     */
    public static double reference(Iterable<CreditSnapshot> pool, double[] weights) {
        double sumMean = 0.0;
        double sumMeanSq = 0.0;
        double sumWithin = 0.0;
        int habits = 0;
        for (CreditSnapshot c : pool) {
            if (c.samples < 1) {
                continue;
            }
            double m = 0.0;
            for (int d = 0; d < Drives.N; d++) {
                m += weights[d] * c.sampleMean[d];
            }
            habits++;
            sumMean += m;
            sumMeanSq += m * m;
            sumWithin += quadratic(weights, c.scatter) / c.samples;
        }
        if (habits == 0) {
            return 0.0;
        }
        double mean = sumMean / habits;
        double v = sumMeanSq / habits - mean * mean + sumWithin / habits;
        return Math.sqrt(Math.max(0.0, v));
    }

    /**
     * This habit's spread: its own finished executions' variance, shrunk toward the reference by
     * {@code priorWeight} pseudo-executions, (priorWeight * reference^2 + scatter) /
     * (priorWeight + n - 1). Run once, a habit has the reference; a habit whose results never vary
     * falls toward 0 as its own executions accumulate, and drags no other habit with it.
     */
    public double spread(double reference, double[] weights, double priorWeight) {
        double dof = Math.max(samples - 1, 0);
        if (priorWeight + dof <= 0) {
            return reference;
        }
        double v = (priorWeight * reference * reference + quadratic(weights, scatter))
                / (priorWeight + dof);
        return Math.sqrt(Math.max(0.0, v));
    }

    private static double quadratic(double[] w, double[][] m) {
        double v = 0.0;
        for (int i = 0; i < Drives.N; i++) {
            for (int j = 0; j < Drives.N; j++) {
                v += w[i] * m[i][j] * w[j];
            }
        }
        return v;
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
