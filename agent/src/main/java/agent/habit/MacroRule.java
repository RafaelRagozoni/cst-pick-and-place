package agent.habit;

import java.util.List;

/**
 * How the steps that led to a goal become a macro (cap4 4.4.2, sequence fusion; vault spec MAC-01).
 * cap4 leaves open which executed steps enter the macro: this is that choice, one line of
 * {@link agent.Config} ({@code macroRule}) or {@code --macro} on the command line, so the rules of
 * the WP3 table can be tried one at a time without touching the HabitLearner.
 */
@FunctionalInterface
public interface MacroRule {

    /**
     * @param executedSteps each executed step's commands, in the order they ran; the HabitLearner
     *                      gives a step cut short as far as it ran (Step#executedCommands)
     * @return the macro's commands, steps numbered from 0; empty for no macro
     */
    List<Command> build(List<List<Command>> executedSteps);

    /** The rules by name; "none" has none. */
    static MacroRule byName(String name) {
        switch (name) {
            case "copy":
                return new CopyRule();
            case "sum":
                return new SumRule();
            default:
                throw new IllegalArgumentException("unknown macro rule '" + name
                        + "' (none, copy, sum)");
        }
    }
}
