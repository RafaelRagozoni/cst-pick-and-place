package agent.memory;

import agent.habit.Command;

import java.util.List;

/**
 * The content of PlanTrackerMO (cap4 4.2): the plan in execution with its current step and
 * completion, and the commands the Motor sends this cycle.
 *
 * <p>{@code planSerial} is the PlanMO decision being executed. When the plan has ended -- its last
 * step completed, its goal was met, or the episode ended -- {@code running} is false and the
 * Behavior Generator chooses again.
 */
public record TrackerState(boolean running, String habit, long planSerial, int stepIndex, int nSteps,
                           List<Command> commands, long cycle) {

    public static TrackerState idle(long cycle) {
        return new TrackerState(false, null, -1, 0, 0, List.of(), cycle);
    }
}
