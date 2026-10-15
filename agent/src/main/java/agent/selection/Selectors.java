package agent.selection;

import agent.habit.HabitIdeas;
import agent.selection.Selector.Candidate;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.function.ToDoubleFunction;

/**
 * The selection mechanisms, by name in {@link agent.Config#selection} and on the command line
 * ({@code --selection}): greedy, ucb, ucb:&lt;c&gt;, thompson, random.
 *
 * <p>All but RANDOM share one rule and differ only in the value they rank by: the highest value
 * starts; the plan in execution is kept unless another habit's value is strictly higher; ties are
 * broken uniformly at random.
 */
public final class Selectors {

    private Selectors() {
    }

    /**
     * The selector a name stands for: greedy, ucb (c = 1), ucb:&lt;c&gt;, thompson, random. A fresh
     * one per call, so a stateful selector (thompson) belongs to the one mind that asked.
     */
    public static Selector byName(String name) {
        if (name.startsWith("ucb:")) {
            double c;
            try {
                c = Double.parseDouble(name.substring(4));
            } catch (NumberFormatException e) {
                c = Double.NaN;
            }
            if (!(c >= 0) || Double.isInfinite(c)) {
                throw new IllegalArgumentException("ucb:<c> needs a finite c >= 0, got " + name);
            }
            return ucb(c);
        }
        return switch (name) {
            case "greedy" -> GREEDY;
            case "ucb" -> ucb(1.0);
            case "thompson" -> thompson();
            case "random" -> RANDOM;
            default -> throw new IllegalArgumentException("unknown selection '" + name
                    + "': greedy, ucb, ucb:<c>, thompson, random");
        };
    }

    /** Values closer than this are a tie. */
    static final double EPS = 1e-12;

    /**
     * UCB's value for a habit never executed: above any other, and equal among such habits, so they
     * are tried first, in random order. Finite, so that ties among them still compare equal.
     */
    static final double UNTRIED = Double.MAX_VALUE;

    /**
     * cap4 as written: rank by the score. Untried habits score 0, which is all the exploration there
     * is. Live runs lock in on it (README, "First live runs").
     */
    public static final Selector GREEDY = (candidates, running, rng) ->
            argmax(candidates, running, rng, Candidate::score);

    /** C6: scores ignored; a uniform-random habit each time the plan in execution ends. */
    public static final Selector RANDOM = (candidates, running, rng) ->
            running != null ? null : candidates.get(rng.nextInt(candidates.size()));

    /**
     * UCB1 (Auer et al. 2002): rank by score + c * spread * sqrt(2 ln N / n), n the habit's executions
     * behind its score and N the sum of n over the pool. A habit tried less than the rest gets a bonus
     * that grows slowly while it is passed over, so one unlucky early result is retried rather than
     * believed forever; a never-executed habit is tried before any other. The noise scale is the
     * pooled spread, so c = 1 needs no calibration to the units of the drives.
     */
    public static Selector ucb(double c) {
        return (candidates, running, rng) -> {
            long total = 0;
            for (Candidate k : candidates) {
                total += k.count();
            }
            double logN = Math.log(Math.max(total, 1));
            return argmax(candidates, running, rng, k -> k.count() == 0 ? UNTRIED
                    : k.score() + c * k.spread() * Math.sqrt(2.0 * logN / k.count()));
        };
    }

    /**
     * Gaussian Thompson sampling (Agrawal and Goyal 2013): rank by a draw from each habit's posterior,
     * score + spread / sqrt(n + 1) * z with z ~ N(0, 1). A habit is chosen with the probability that
     * it is the best, given how often it was tried; a never-executed one draws around 0 with the full
     * spread. No parameter.
     *
     * <p>One draw per decision: z is drawn for every habit when nothing is running, and held while
     * the plan runs. Drawing anew every cycle would let some habit's lucky draw preempt the running
     * plan almost every cycle; held, the plan is preempted only when the scores themselves move.
     * Stateful: one per mind.
     */
    public static Selector thompson() {
        Map<String, Double> z = new HashMap<>();
        return (candidates, running, rng) -> {
            if (running == null) {
                z.clear();
            }
            for (Candidate k : candidates) {
                z.computeIfAbsent(HabitIdeas.id(k.habit()), id -> rng.nextGaussian());
            }
            return argmax(candidates, running, rng, k -> k.score()
                    + k.spread() / Math.sqrt(k.count() + 1.0) * z.get(HabitIdeas.id(k.habit())));
        };
    }

    /** The shared rule: highest value starts, the running plan is kept unless beaten, random ties. */
    static Candidate argmax(List<Candidate> candidates, Candidate running, Random rng,
                            ToDoubleFunction<Candidate> value) {
        double best = Double.NEGATIVE_INFINITY;
        List<Candidate> ties = new ArrayList<>();
        for (Candidate c : candidates) {
            double v = value.applyAsDouble(c);
            if (v > best + EPS) {
                best = v;
                ties.clear();
                ties.add(c);
            } else if (Math.abs(v - best) <= EPS) {
                ties.add(c);
            }
        }
        if (running != null && best <= value.applyAsDouble(running) + EPS) {
            return null;
        }
        return ties.get(rng.nextInt(ties.size()));
    }
}
