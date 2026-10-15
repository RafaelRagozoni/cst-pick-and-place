package agent.codelets;

import br.unicamp.cst.core.entities.Codelet;
import br.unicamp.cst.core.entities.Memory;

/**
 * Common ground for the eight codelets of cap4 4.2. All are plain codelets; none is a habit
 * executioner.
 *
 * <p>They are run by {@link agent.AgentMind#cycle}, once each per control cycle in a fixed order,
 * through CST's own {@code notifyCodelet} entry point -- not on free-running timers, and not chained
 * as memory observers. AgentMind's documentation says why.
 */
abstract class AgentCodelet extends Codelet {

    AgentCodelet(String name) {
        setName(name);
    }

    @Override
    public void calculateActivation() {
        // Activation stays 0 with threshold 0: every scheduled call runs proc().
    }

    /** An input by name; failing loudly beats a codelet quietly reading nothing. */
    protected Memory in(String name) {
        Memory m = getInput(name);
        if (m == null) {
            throw new IllegalStateException(getName() + " has no input " + name);
        }
        return m;
    }

    protected Memory out(String name) {
        Memory m = getOutput(name);
        if (m == null) {
            throw new IllegalStateException(getName() + " has no output " + name);
        }
        return m;
    }
}
