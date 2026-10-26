package agent.memory;

import br.unicamp.cst.representation.idea.Idea;

/**
 * The content of PlanMO: the habit the Behavior Generator chose, and why.
 *
 * <p>{@code serial} identifies the decision. The Behavior Generator issues a new serial when it
 * switches habits or starts one after the last ended, and leaves PlanMO alone when it keeps the
 * plan in execution, so the PlanTracker restarts a plan only on a new serial. {@code goal} and
 * {@code context} are the goal and the (goal, state) key at the moment of choice: the credit the
 * habit earns is recorded under them (cap4 4.3.1, 4.3.4).
 */
public record Plan(long serial, Idea habit, String goal, long goalId, String context, double score) {
}
