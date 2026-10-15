package agent.selection;

import br.unicamp.cst.representation.idea.Idea;

import java.util.List;
import java.util.Random;

/**
 * How the Behavior Generator picks a habit once every habit in the pool is scored (cap4 4.3.5).
 *
 * <p>The Behavior Generator computes the scores; a Selector only decides. The mechanism in use is one
 * line of {@link agent.Config}: {@code selector = Selectors.GREEDY}. Implementations live in
 * {@link Selectors}.
 */
@FunctionalInterface
public interface Selector {

    /** A habit and its score E(h) under the current goal, state and drive levels. */
    record Candidate(Idea habit, double score) {
    }

    /**
     * @param candidates every habit in the pool, scored, in pool order; never empty
     * @param running    the candidate whose plan is in execution, or null when nothing runs
     * @param rng        the Behavior Generator's seeded generator: draw only from this one, or a
     *                   seed no longer reproduces a run
     * @return the habit to start, or null to keep the plan in execution
     */
    Candidate select(List<Candidate> candidates, Candidate running, Random rng);
}
