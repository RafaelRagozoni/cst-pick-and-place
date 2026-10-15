package agent.memory;

import agent.habit.Command;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * The content of ExecutionBuffer (cap4 4.3.3): every executed habit step, and a mark at every goal
 * completion. Written only by the PlanTracker; Credit Assignment reads the steps, the HabitLearner
 * reads the stretch between goal marks to build macros (WP3).
 *
 * <p>Entries carry a sequence number so a reader can take what is new since it last looked. The
 * buffer is bounded; a reader that falls further behind than {@code capacity} entries loses the
 * oldest ones, which {@link #since} reports by throwing rather than by returning a gap.
 */
public final class ExecutionBuffer {

    public sealed interface Entry permits Step, GoalMark {
        long seq();
    }

    /**
     * One habit step, from the cycle its commands were first sent ({@code startCycle}) to the cycle
     * whose observation ended it ({@code endCycle}). {@code outcome} is StepCompletion's (done,
     * stalled, timeout) or why it was cut short: preempted (another habit took over), closed (the
     * goal was met mid-step), interrupted (the episode ended).
     */
    public record Step(long seq, String habit, long instance, int stepIndex, int nSteps,
                       List<Command> commands, long startCycle, long endCycle, String outcome,
                       String goal, long goalId, String context, int episode) implements Entry {
    }

    /** The goal {@code goal} (id {@code goalId}) was achieved on {@code cycle}. */
    public record GoalMark(long seq, String goal, long goalId, String source, long cycle,
                           int episode) implements Entry {
    }

    private final int capacity;
    private final ArrayDeque<Entry> entries = new ArrayDeque<>();
    private long nextSeq;

    public ExecutionBuffer(int capacity) {
        this.capacity = capacity;
    }

    public Step addStep(String habit, long instance, int stepIndex, int nSteps, List<Command> commands,
                        long startCycle, long endCycle, String outcome, String goal, long goalId,
                        String context, int episode) {
        Step s = new Step(nextSeq++, habit, instance, stepIndex, nSteps, List.copyOf(commands),
                startCycle, endCycle, outcome, goal, goalId, context, episode);
        push(s);
        return s;
    }

    public GoalMark addGoalMark(String goal, long goalId, String source, long cycle, int episode) {
        GoalMark g = new GoalMark(nextSeq++, goal, goalId, source, cycle, episode);
        push(g);
        return g;
    }

    private void push(Entry e) {
        entries.addLast(e);
        while (entries.size() > capacity) {
            entries.removeFirst();
        }
    }

    /** Sequence number the next entry will get; a reader that has seen everything holds this. */
    public long nextSeq() {
        return nextSeq;
    }

    /**
     * Continue the numbering of a run resumed from a checkpoint. The entries themselves are not
     * kept: in WP2 nothing reads one after its episode (Credit Assignment reads each once).
     */
    public void resumeAt(long seq) {
        if (!entries.isEmpty()) {
            throw new IllegalStateException("resume an ExecutionBuffer before anything is added");
        }
        nextSeq = seq;
    }

    /** Entries with seq >= {@code seq}, oldest first. */
    public List<Entry> since(long seq) {
        if (!entries.isEmpty() && seq < entries.peekFirst().seq()) {
            throw new IllegalStateException("reader fell behind the ExecutionBuffer: wanted " + seq
                    + ", oldest kept is " + entries.peekFirst().seq());
        }
        List<Entry> out = new ArrayList<>();
        for (Entry e : entries) {
            if (e.seq() >= seq) {
                out.add(e);
            }
        }
        return out;
    }
}
