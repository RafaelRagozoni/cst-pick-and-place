package agent;

import agent.credit.CreditSnapshot;
import agent.motivation.Drives;
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

    // --- Goal Generator (cap4 4.3.3) -------------------------------------------
    /** A drive must exceed the one that set the current goal by this much to replace it. */
    public double goalHysteresis = 0.1;
    /** Safety at or above this (after gain) sets the goal regardless of the others (subsumption). */
    public double safetyOverride = 0.5;
    /** Curiosity's goal is met when the raw Curiosity level falls below this. */
    public double curiosityGoalMet = 0.3;
    /** Safety's goal is met when the raw Safety level falls below this. */
    public double safetyGoalMet = 0.2;

    // --- Credit Assignment (cap4 4.3.4) ----------------------------------------
    /** Eligibility trace decay per cycle. C3 sets 0: only the habit that just executed is credited. */
    public double lambda = 0.9;
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

    // --- HabitLearner (cap4 4.4) -------------------------------------------------
    /** False in C4 and C6: the pool stays the primitives. Credit is still copied in (C4). */
    public boolean generation = true;
    /** False in C2: no parallel fusion and no macros. */
    public boolean fusion = true;

    // --- buffers -------------------------------------------------------------------
    public int sensoryBufferSize = 64;
    public int executionBufferSize = 4096;

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
