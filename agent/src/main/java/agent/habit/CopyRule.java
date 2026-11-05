package agent.habit;

import java.util.ArrayList;
import java.util.List;

/**
 * The control rule of vault spec MAC-01: every executed step becomes a step of the macro, with the
 * commands it had. A step that belonged to a macro brings that macro's commands, so a macro is
 * always flat, primitive commands only (MAC-01 D6, cap4's "flat normal form").
 */
public final class CopyRule implements MacroRule {

    @Override
    public List<Command> build(List<List<Command>> executedSteps) {
        List<Command> macroCommands = new ArrayList<>();
        for (int stepIndex = 0; stepIndex < executedSteps.size(); stepIndex++) {
            for (Command command : executedSteps.get(stepIndex)) {
                macroCommands.add(command.withStep(stepIndex));
            }
        }
        return macroCommands;
    }
}
