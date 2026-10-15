package agent.motivation;

import agent.sim.Observation;

/**
 * The behavior characterization b of cap4 4.3.1: task space (end-effector and cube positions),
 * augmented with the salient-event dimensions -- gripper holding, contact, cube displacement.
 *
 * <p>The bins are exactly {@code metrics.characterise}'s, so the region the Curiosity drive calls
 * novel and the region metric 5 (state-space coverage) counts as visited are the same thing;
 * {@code CharacterizationParityTest} holds the two together. The same bin key is the state s under
 * which credit is recorded (cap4 4.3.4).
 *
 * <p>The continuous vector, used for novelty distances, is in bin units, so 1.0 means "one bin away"
 * on every axis. The two event flags are scaled by {@code salience} bins: an event switching on
 * counts as that many bins of movement, which is what makes first contact or first lift register as
 * a large novelty. That weight is a designed inductive bias, present in every condition (cap4 4.3.1).
 */
public final class Characterization {

    public static final double POS_BIN = 0.05;
    public static final double DISP_BIN = 0.02;
    public static final int DIMS = 9;

    private Characterization() {
    }

    /** metrics.characterise as a flat int vector: eef bins (3), cube bins (3), holding, contact, disp. */
    public static int[] bins(Observation o) {
        double[] e = o.eefPos();
        double[] c = o.cubePos();
        return new int[]{
                (int) Math.floor(e[0] / POS_BIN), (int) Math.floor(e[1] / POS_BIN),
                (int) Math.floor(e[2] / POS_BIN),
                (int) Math.floor(c[0] / POS_BIN), (int) Math.floor(c[1] / POS_BIN),
                (int) Math.floor(c[2] / POS_BIN),
                o.holding() ? 1 : 0, o.contact() ? 1 : 0,
                (int) (o.cubeDisplacement() / DISP_BIN),
        };
    }

    /** The bin as a map key and as the state s. Never parses as a number (Idea would convert it). */
    public static String key(Observation o) {
        int[] b = bins(o);
        return "e" + b[0] + "," + b[1] + "," + b[2] + "c" + b[3] + "," + b[4] + "," + b[5]
                + "h" + b[6] + "k" + b[7] + "d" + b[8];
    }

    /** b in bin units, for distances. */
    public static double[] vector(Observation o, double salience) {
        double[] e = o.eefPos();
        double[] c = o.cubePos();
        return new double[]{
                e[0] / POS_BIN, e[1] / POS_BIN, e[2] / POS_BIN,
                c[0] / POS_BIN, c[1] / POS_BIN, c[2] / POS_BIN,
                o.holding() ? salience : 0.0, o.contact() ? salience : 0.0,
                o.cubeDisplacement() / DISP_BIN,
        };
    }
}
