package agent.selection;

import br.unicamp.cst.representation.idea.Idea;

import java.util.List;
import java.util.Random;

/**
 * How the Behavior Generator picks a habit once every habit in the pool is scored (cap4 4.3.5).
 *
 * <p>The Behavior Generator computes the scores; a Selector only decides. The mechanism in use is one
 * line of {@link agent.Config}: {@code selection = "greedy"}, or {@code --selection} on the command
 * line. Implementations live in {@link Selectors}, and {@link Selectors#byName} maps the names.
 */
@FunctionalInterface
public interface Selector {

    /**
     * A habit and what is known about it under the current goal, state and drive levels.
     *
     * @param score  E(h), eq. (4.1)
     * @param count  executions behind that score: under this context, or in total where the habit
     *               has no record here (the same cell the score comes from)
     * @param spread standard deviation of one execution's score, the same for every candidate
     *               ({@link agent.credit.CreditSnapshot#spread}); 0 until it can be estimated
     */
    record Candidate(Idea habit, double score, long count, double spread) {
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
