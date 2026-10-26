package agent;

import agent.credit.CreditSnapshot;
import agent.motivation.Drives;
import agent.motivation.Yields;
import agent.selection.Selectors;

/**
 * Every tunable of the agent, and the ablation conditions of cap4 4.6.1 as settings of them.
 *
 * <p>The values are starting points, not tuned results. Each one says what it is in the units the
 * code uses; cap4 names most of them without fixing a number.
 */
public final class Config {

    public String condition = "C0";

    // --- Drive Generator (cap4 4.3.2) -----------------------------------------
    /** Per-drive gain applied before DriveMO, indexed by Drives.*. Effort starts at 0 (bootstrap). */
    public double[] gains = {1.0, 1.0, 1.0, 0.0};
    /** Effort's gain in Phase 2 (refinement), cap4 4.6.2. */
    public double effortRefineGain = 1.0;
    /** Task level = target distance / this, capped at 1. Meters; ~ the arm's reach across the table. */
    public double taskDistanceScale = 0.5;
    /** Safety rises as a joint comes within this many radians of its limit. */
    public double safetyMargin = Math.toRadians(15);
    /** Effort level = cycles on the current goal / this. */
    public double effortScale = 100.0;
    /**
     * Curiosity level = 1 / (1 + novelty / noveltyScale): 1 when bored, toward 0 when novel, 0.5 at
     * novelty == noveltyScale. NOT calibrated. In a live C0 run (2026-10-14, 3000 steps) novelty had
     * median 0.006 and 90th percentile 0.066, so at 1.0 Curiosity sits near 0.97 and holds the goal
     * almost always. Setting it to the median (0.01) made the run lock into two habits that never
     * leave the home bin -- larger credit swings make greedy selection lock in sooner (README, "First
     * live runs"). Fix selection before calibrating this.
     */
    public double noveltyScale = 1.0;
    /** k nearest neighbours in the novelty archive. */
    public int noveltyK = 5;
    /** A characterization enters the archive when its sparseness exceeds this many bins. */
    public double archiveAddThreshold = 1.0;
    public int archiveCap = 5000;
    /** Per-cycle decay of bin visit counts: 0.9997 halves a count in ~2300 cycles (~5 episodes). */
    public double visitDecay = 0.9997;
    /** Weight of the holding and contact events in the characterization, in bins. */
    public double salience = 3.0;
    /**
     * Curiosity = boredom * yield, the yield by name (Yields.byName), or --curiosity: "none" (yield
     * 1, cap4 as written), "count", "count:<W>", "lp", "lp:<W>"; W the cycles of its running mean.
     * "none" is NOT a safe default but the old behavior, kept to compare with earlier batches: with
     * it Task cannot take the goal from Curiosity at all (Task is capped at 1, it must beat Curiosity
     * by goalHysteresis, and boredom sits at ~0.995). Vault spec CUR-01; README, "Curiosity that runs
     * out".
     */
    public String curiosityYield = "none";

    // --- Goal Generator (cap4 4.3.3) -------------------------------------------
    /** A drive must exceed the one that set the current goal by this much to replace it. */
    public double goalHysteresis = 0.1;
    /** Safety at or above this (after gain) sets the goal regardless of the others (subsumption). */
    public double safetyOverride = 0.5;
    /**
     * Curiosity's goal is met when its boredom falls below this -- boredom, not the level: a low
     * yield is exploring having stopped paying, not novelty found.
     */
    public double curiosityGoalMet = 0.3;
    /** Safety's goal is met when the raw Safety level falls below this. */
    public double safetyGoalMet = 0.2;

    // --- Credit Assignment (cap4 4.3.4) ----------------------------------------
    /**
     * Eligibility trace decay per cycle. C3 sets 0: only the habit that just executed is credited.
     * Was 0.9 until 2026-10-16: with primitives that last one cycle, each execution's credit was
     * shared with the ~30 executions after it, and ~60% of a habit's recorded credit was what the
     * habits after it did (a habit's own effect on Task kept its sign in 81-89% of repeats in a bin,
     * its recorded credit in 67-73%). At 0.5 a trace lasts ~7 cycles, ~2 executions' worth of weight.
     */
    public double lambda = 0.5;
    /**
     * Task credit is progress beyond the closest the arm came in the last this-many cycles of the
     * current stage: a cycle's Task credit is max(0, lowest recent Task level - this cycle's).
     * Coming back to where it had been earns nothing and moving away is not charged, so going back
     * and forth pays nothing. 0 = the plain per-cycle change. Live at 20 (2026-10-16, README
     * "Credit, round 1") it was worse in every seed: 70% of executions earn exactly 0, and the gap
     * between the best and worst habit in a bin fell 4-5x. Off.
     */
    public int progressWindow = 0;
    /**
     * With progressWindow on: a cycle that moves away from the target is charged its plain change
     * (negative), as with progressWindow 0, instead of 0. Only coming back over ground covered in
     * the window earns nothing. Off: moving away earns 0 too.
     */
    public boolean progressChargesRetreat = false;
    /**
     * A step's drive changes are credited minus what a step in its context (goal, state bin)
     * changes whatever runs there: an exponential running mean per context, this the weight of each
     * new step. It takes out what happens anyway -- Curiosity rising as a bin grows familiar charged
     * every habit that ran there. Per step, not per cycle times the step's length: scaled by
     * length, 44-cycle grabs were charged dozens of one-cycle bin crossings. 0 = no baseline. Live
     * at 0.1 (2026-10-16, README "Credit, round 1") no clear gain: a baseline every habit in a
     * context shares barely changes their ranking there. Off.
     */
    public double baselineRate = 0.0;
    /** Traces below this are dropped. */
    public double traceFloor = 0.01;
    /** False in C6: no credit updates at all. */
    public boolean creditUpdates = true;

    // --- Behavior Generator (cap4 4.3.5) ---------------------------------------
    /**
     * How a stored credit is read when scoring. cap4 says credit "accumulates"; read as a raw SUM, a
     * habit's score grows with how often it ran rather than with how well, and a context's sum and the
     * total it falls back to are on different scales. MEAN reads credit per execution. Both are
     * stored, so this is a reading choice, not a different learner.
     */
    public CreditSnapshot.Read creditRead = CreditSnapshot.Read.MEAN;
    /**
     * How the scores become a choice, by name (Selectors.byName). Swapping the mechanism is this one
     * line, or --selection: "greedy" (cap4 as written), "ucb", "ucb:<c>", "thompson". C6 sets
     * "random" and takes no other (withSelection).
     */
    public String selection = "greedy";
    /**
     * How many executions' worth of weight the repertoire's reference spread has in each habit's
     * spread (CreditSnapshot#spread): a habit run once has the reference; after this many more its
     * own results weigh as much. Before 2026-10-16 one spread was pooled over every execution, and a
     * no-op repeated thousands of times set it to ~0 for every habit.
     */
    public double spreadPriorWeight = 2.0;

    // --- HabitLearner (cap4 4.4) -------------------------------------------------
    /** False in C4 and C6: the pool stays the primitives. Credit is still copied in (C4). */
    public boolean generation = true;
    /** False in C2: no parallel fusion and no macros. */
    public boolean fusion = true;

    // --- buffers -------------------------------------------------------------------
    public int sensoryBufferSize = 64;
    public int executionBufferSize = 4096;

    /** Set the Curiosity yield by name, refusing a bad name now rather than at the first cycle. */
    public Config withCuriosity(String name) {
        Yields.byName(name);
        curiosityYield = name;
        return this;
    }

    /** Set the selection by name, refusing a bad name now rather than at the first cycle. */
    public Config withSelection(String name) {
        Selectors.byName(name);
        if (condition.equals("C6") && !name.equals("random")) {
            throw new IllegalArgumentException(
                    "C6 is the random baseline: selection '" + name + "' would make it another run");
        }
        selection = name;
        return this;
    }

    public static Config forCondition(String c) {
        Config k = new Config();
        k.condition = c;
        switch (c) {
            case "C0":
                break;
            case "C1":                                  // no Curiosity
                k.gains[Drives.CURIOSITY] = 0.0;
                break;
            case "C2":                                  // no fusion
                k.fusion = false;
                break;
            case "C3":                                  // one-step credit
                k.lambda = 0.0;
                break;
            case "C4":                                  // pool frozen at the primitives
                k.generation = false;
                break;
            case "C5":                                  // Curiosity only: no Task, no Effort, ever
                k.gains[Drives.TASK] = 0.0;
                k.effortRefineGain = 0.0;
                break;
            case "C6":                                  // random baseline
                k.selection = "random";
                k.creditUpdates = false;
                k.generation = false;
                break;
            default:
                throw new IllegalArgumentException("unknown condition " + c + " (C0..C6)");
        }
        return k;
    }
}
