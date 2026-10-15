package agent.selection;

import agent.selection.Selector.Candidate;

import java.util.ArrayList;
import java.util.List;

/** The selection mechanisms. Pick one in {@link agent.Config#selector}. */
public final class Selectors {

    private Selectors() {
    }

    /** Scores closer than this are a tie. */
    static final double EPS = 1e-12;

    /**
     * cap4 as written: the best score wins. The plan in execution is kept unless another habit scores
     * strictly higher, and ties are broken uniformly at random -- which is all the exploration there
     * is, when every credit is zero. Live runs lock in on it (README, "First live runs").
     */
    public static final Selector GREEDY = (candidates, running, rng) -> {
        double best = Double.NEGATIVE_INFINITY;
        List<Candidate> ties = new ArrayList<>();
        for (Candidate c : candidates) {
            if (c.score() > best + EPS) {
                best = c.score();
                ties.clear();
                ties.add(c);
            } else if (Math.abs(c.score() - best) <= EPS) {
                ties.add(c);
            }
        }
        if (running != null && best <= running.score() + EPS) {
            return null;
        }
        return ties.get(rng.nextInt(ties.size()));
    };

    /** C6: scores ignored; a uniform-random habit each time the plan in execution ends. */
    public static final Selector RANDOM = (candidates, running, rng) ->
            running != null ? null : candidates.get(rng.nextInt(candidates.size()));
}
