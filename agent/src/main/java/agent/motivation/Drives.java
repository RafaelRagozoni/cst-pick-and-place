package agent.motivation;

import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.representation.idea.Idea;

/**
 * The drive set D = {Curiosity, Task, Safety, Effort} of cap4 4.3.2, and the DriveMO Idea.
 *
 * <pre>
 *   Idea DriveMO
 *     cycle
 *     curiosity, task, safety, effort   levels after the Drive Generator's gains -- what D_d means
 *     raw       curiosity, task, safety, effort   the same before the gains
 *     taskStage        the stage the Task drive inferred (Credit Assignment ignores Task's change
 *                      across a stage switch: that is a new target, not the habit's doing)
 *     effortRestarted  Effort restarted this cycle because a new goal was set (likewise ignored)
 *     novelty          the novelty Curiosity was computed from, for inspection
 *     boredom          Curiosity's first factor, 1 / (1 + novelty / scale): what its goal is met by
 *     yield            Curiosity's second factor (CuriosityYield); raw curiosity = boredom * yield
 * </pre>
 *
 * Every vector over drives in this package is indexed by the constants below.
 */
public final class Drives {

    public static final int CURIOSITY = 0;
    public static final int TASK = 1;
    public static final int SAFETY = 2;
    public static final int EFFORT = 3;
    public static final int N = 4;
    public static final String[] NAMES = {"curiosity", "task", "safety", "effort"};

    private final Idea idea;

    public Drives(Idea idea) {
        this.idea = idea;
    }

    /** The current DriveMO, or null before the Drive Generator first ran. */
    public static Drives of(Memory driveMO) {
        Object i = driveMO.getI();
        return i instanceof Idea ? new Drives((Idea) i) : null;
    }

    /** With Curiosity all boredom (yield 1), as before CUR-01. */
    public static Idea toIdea(long cycle, double[] gained, double[] raw, int taskStage,
                              boolean effortRestarted, double novelty) {
        return toIdea(cycle, gained, raw, taskStage, effortRestarted, novelty, raw[CURIOSITY], 1.0);
    }

    public static Idea toIdea(long cycle, double[] gained, double[] raw, int taskStage,
                              boolean effortRestarted, double novelty, double boredom,
                              double curiosityYield) {
        Idea root = new Idea("DriveMO", null, 0);
        root.add(new Idea("cycle", cycle, 1));
        Idea r = new Idea("raw", null, 0);
        for (int d = 0; d < N; d++) {
            root.add(new Idea(NAMES[d], gained[d], 1));
            r.add(new Idea(NAMES[d], raw[d], 1));
        }
        root.add(r);
        root.add(new Idea("taskStage", taskStage, 1));
        root.add(new Idea("effortRestarted", effortRestarted, 1));
        root.add(new Idea("novelty", novelty, 1));
        root.add(new Idea("boredom", boredom, 1));
        root.add(new Idea("yield", curiosityYield, 1));
        return root;
    }

    public Idea idea() {
        return idea;
    }

    public long cycle() {
        return ((Number) idea.get("cycle").getValue()).longValue();
    }

    /** D_d: the levels the selection weights by and Credit Assignment differences. */
    public double[] levels() {
        double[] v = new double[N];
        for (int d = 0; d < N; d++) {
            v[d] = ((Number) idea.get(NAMES[d]).getValue()).doubleValue();
        }
        return v;
    }

    public double level(int d) {
        return ((Number) idea.get(NAMES[d]).getValue()).doubleValue();
    }

    public double raw(int d) {
        return ((Number) idea.get("raw." + NAMES[d]).getValue()).doubleValue();
    }

    public int taskStage() {
        return ((Number) idea.get("taskStage").getValue()).intValue();
    }

    public boolean effortRestarted() {
        return (Boolean) idea.get("effortRestarted").getValue();
    }

    public double novelty() {
        return ((Number) idea.get("novelty").getValue()).doubleValue();
    }

    /** Curiosity's boredom, before the yield and the gain: whether its goal is met. */
    public double boredom() {
        return ((Number) idea.get("boredom").getValue()).doubleValue();
    }

    /** Curiosity's yield: 1 under "none". */
    public double curiosityYield() {
        return ((Number) idea.get("yield").getValue()).doubleValue();
    }
}
