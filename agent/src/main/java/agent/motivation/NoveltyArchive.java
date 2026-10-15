package agent.motivation;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;

/**
 * The novelty measure of cap4 4.3.2: novelty-search sparseness (mean distance to the k nearest
 * characterizations in a growing archive, Lehman &amp; Stanley 2011) divided by the decaying visit
 * count of the current bin, so a region the agent keeps returning to pays progressively less and an
 * exhausted region pays again if left alone long enough (Singh et al. 2004's satiation).
 *
 * <p>Archive admission is novelty search's usual threshold rule: a point enters only if its
 * sparseness exceeds {@code addThreshold}. Without it the archive would grow by one point per cycle
 * and the nearest-neighbour search, which is brute force here, would grow with it. A full archive
 * replaces its oldest point.
 *
 * <p>Visit counts decay geometrically per cycle. The decay is applied lazily, on read, so the cost
 * per cycle does not grow with the number of bins ever visited.
 */
public final class NoveltyArchive {

    /**
     * Sparseness reported against an empty archive. Zero, not "maximally novel": an empty archive is
     * no evidence of novelty, and a large value here made the first cycle of a run look novel and the
     * second familiar -- a drop in Curiosity charged to whichever habit happened to run first, which
     * in a live run was enough to keep it from ever being chosen again.
     */
    public static final double EMPTY_SPARSENESS = 0.0;

    private final int k;
    private final double addThreshold;
    private final int cap;
    private final double decay;
    private final List<double[]> archive = new ArrayList<>();
    private int oldest;
    private final Map<String, double[]> counts = new HashMap<>();   // key -> {count, cycle}

    public NoveltyArchive(int k, double addThreshold, int cap, double decayPerCycle) {
        this.k = k;
        this.addThreshold = addThreshold;
        this.cap = cap;
        this.decay = decayPerCycle;
    }

    public int size() {
        return archive.size();
    }

    /** Mean distance from b to its k nearest archive points (fewer while the archive is small). */
    public double sparseness(double[] b) {
        if (archive.isEmpty()) {
            return EMPTY_SPARSENESS;
        }
        PriorityQueue<Double> nearest = new PriorityQueue<>(k, (x, y) -> Double.compare(y, x));
        for (double[] p : archive) {
            double s = 0;
            for (int i = 0; i < b.length; i++) {
                double d = b[i] - p[i];
                s += d * d;
            }
            double dist = Math.sqrt(s);
            if (nearest.size() < k) {
                nearest.add(dist);
            } else if (dist < nearest.peek()) {
                nearest.poll();
                nearest.add(dist);
            }
        }
        double sum = 0;
        for (double d : nearest) {
            sum += d;
        }
        return sum / nearest.size();
    }

    /** The bin's visit count as of {@code cycle}, decayed, without counting a visit. */
    public double count(String key, long cycle) {
        double[] c = counts.get(key);
        return c == null ? 0.0 : c[0] * Math.pow(decay, cycle - c[1]);
    }

    /**
     * One cycle spent at b, in bin {@code key}: count the visit, maybe archive b, and return the
     * novelty (sparseness / visit count). The count includes this visit, so it is at least 1.
     */
    public double visit(double[] b, String key, long cycle) {
        double sparse = sparseness(b);
        double n = count(key, cycle) + 1.0;
        counts.put(key, new double[]{n, cycle});
        if (archive.size() < k || sparse > addThreshold) {
            if (archive.size() < cap) {
                archive.add(b.clone());
            } else {
                archive.set(oldest, b.clone());
                oldest = (oldest + 1) % cap;
            }
        }
        return sparse / n;
    }
}
