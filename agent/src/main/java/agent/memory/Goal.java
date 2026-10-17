package agent.memory;

import agent.motivation.Drives;
import agent.sim.Observation;
import agent.task.TaskStages;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.representation.idea.Idea;

/**
 * The GoalMO Idea (cap4 4.3.3): "a target together with the measure that says when it is achieved".
 *
 * <pre>
 *   Idea GoalMO
 *     id          increments whenever the goal changes -- the PlanTracker and Effort key on it
 *     source      task | curiosity | safety: the drive that set it
 *     name        reach | grasp | transport | release | done | explore | recover
 *     stage       the task stage index (4 = done), kept even while another drive holds the goal
 *     setAtCycle
 *     target      double[]: the stage's target position; empty for explore and recover
 * </pre>
 *
 * The measure is {@link #met}, a pure function of the goal, one observation and the drive levels, so
 * the Goal Generator and the PlanTracker evaluate the same thing.
 */
public final class Goal {

    public static final String TASK = "task";
    public static final String CURIOSITY = "curiosity";
    public static final String SAFETY = "safety";
    public static final String EXPLORE = "explore";
    public static final String RECOVER = "recover";

    private final Idea idea;

    public Goal(Idea idea) {
        this.idea = idea;
    }

    public static Goal of(Memory goalMO) {
        Object i = goalMO.getI();
        return i instanceof Idea ? new Goal((Idea) i) : null;
    }

    public static Idea toIdea(long id, String source, String name, int stage, long setAtCycle,
                              double[] target) {
        Idea g = new Idea("GoalMO", null, 18);
        g.add(new Idea("id", id, 1));
        g.add(new Idea("source", source, 1));
        g.add(new Idea("name", name, 1));
        g.add(new Idea("stage", stage, 1));
        g.add(new Idea("setAtCycle", setAtCycle, 1));
        g.add(new Idea("target", target, 1));
        return g;
    }

    public long id() {
        return ((Number) idea.get("id").getValue()).longValue();
    }

    public String source() {
        return (String) idea.get("source").getValue();
    }

    public String name() {
        return (String) idea.get("name").getValue();
    }

    public int stage() {
        return ((Number) idea.get("stage").getValue()).intValue();
    }

    /** Is this goal achieved, given what is perceived and the drive levels? */
    public boolean met(Observation o, Drives drives, double curiosityMet, double safetyMet) {
        switch (source()) {
            case TASK:
                return stage() < TaskStages.DONE && TaskStages.termination(stage(), o);
            case CURIOSITY:
                return drives != null && drives.boredom() < curiosityMet;
            case SAFETY:
                return drives != null && drives.raw(Drives.SAFETY) < safetyMet;
            default:
                return false;
        }
    }
}
