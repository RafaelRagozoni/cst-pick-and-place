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

    public static final CreditSnapshot EMPTY =
            new CreditSnapshot(new double[Drives.N], 0, Collections.emptyMap());

    private final double[] totalSum;
    private final long totalCount;
    private final Map<String, CreditTable.Cell> byContext;

    CreditSnapshot(double[] totalSum, long totalCount, Map<String, CreditTable.Cell> byContext) {
        this.totalSum = totalSum;
        this.totalCount = totalCount;
        this.byContext = byContext;
    }

    public long executions() {
        return totalCount;
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
