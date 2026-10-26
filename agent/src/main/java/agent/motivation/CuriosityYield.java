package agent.motivation;

import agent.sim.Observation;
import com.google.gson.JsonObject;

/**
 * "Is exploring still paying?": the factor y in [0, 1] the Curiosity level is multiplied by
 * (vault spec CUR-01). The level of cap4 4.3.2 is boredom where the agent is, and boredom never runs
 * out -- the fuller the novelty archive, the more bored the agent everywhere -- so Curiosity held the
 * goal ~97% of the time and Task could not take it at all (README, "Curiosity that runs out"). y
 * falls when exploring stops finding anything and rises when it finds something again, and Task
 * takes the goal when y is low.
 *
 * <p>Chosen by name ({@link Yields#byName}, {@code Config.curiosityYield}, {@code --curiosity}),
 * as the selection mechanism is. Called once per cycle by the Drive Generator, in cycle order.
 */
public interface CuriosityYield {

    /**
     * One cycle: the observation, its bin and characterization vector (as the novelty archive gets
     * them), and the habit whose commands produced it -- the one in execution last cycle, or null when
     * none ran. Returns y for this cycle.
     */
    double observe(Observation o, String bin, double[] b, String habit);

    /** What outlives an episode, for a checkpoint. */
    JsonObject state();

    void restore(JsonObject s);
}
