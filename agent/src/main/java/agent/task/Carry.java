package agent.task;

import agent.sim.Observation;
import br.unicamp.cst.representation.idea.Idea;

/**
 * What the agent remembers of the carry, so that the strict success test (BAS-01) is a function of
 * one SensoryMO: a port of goals.GoalTracker's {@code _track}. The Sensory codelet keeps one per
 * run, resets it when an episode starts, and writes its state into every observation's
 * {@code carry} group; {@link TaskStages#settled} then reads the test off that observation alone.
 *
 * <p>The agent keeps its own for the reason TaskStages gives: the bridge's tracker is the
 * environment's, and a robot outside the simulator would have none. Two copies of one rule stay
 * equal only through {@code ParityTest}, which compares them observation by observation on the
 * expert trajectory and on test_success.py's cases. One difference is left: the bridge's success
 * also needs its four steps to have fired in order, one per observation, which this does not track.
 * Its transport step is ready to fire by the third observation the cube is held, so the two part
 * only on a carry that is transported in nothing but the first two.
 */
public final class Carry {

    private boolean carried;        // since the cube was last grasped, it was transported
    private boolean placing;        // let go over the pad after a carry, and in the zone since
    private int still;              // observations in a row, while placing, below SETTLE_SPEED
    private boolean prevHeld;
    private double prevToPadXY;

    /** Forget the carry: a new episode starts with none. */
    public void reset() {
        carried = false;
        placing = false;
        still = 0;
        prevHeld = false;
    }

    /** Follow one more observation, and write the carry so far into its {@code carry} group. */
    public void observe(Idea observation) {
        Observation o = new Observation(observation);
        boolean held = TaskStages.grasped(o);
        if (held) {
            carried = (carried && prevHeld) || TaskStages.transported(o);
            placing = false;
        } else if (prevHeld) {                              // let go on this observation
            placing = carried && prevToPadXY <= TaskStages.TRANSPORT_XY;
        }
        if (placing && !TaskStages.onPad(o)) {
            placing = false;                                // bounced, rolled or fell off the zone
        }
        still = placing && TaskStages.cubeSpeed(o) < TaskStages.SETTLE_SPEED ? still + 1 : 0;
        prevHeld = held;
        prevToPadXY = o.cubeToPadXY();
        Observation.setCarry(observation, carried, placing, still);
    }
}
