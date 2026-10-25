package agent.codelets;

import agent.Config;
import agent.memory.Goal;
import agent.memory.TrackerState;
import agent.motivation.Characterization;
import agent.motivation.CuriosityYield;
import agent.motivation.Drives;
import agent.motivation.NoveltyArchive;
import agent.motivation.Yields;
import agent.sim.Observation;
import agent.task.TaskStages;
import br.unicamp.cst.core.entities.Memory;
import com.google.gson.JsonObject;

/**
 * Drive Generator (cap4 4.3.2): computes the four drive levels from SensoryMO and writes them,
 * multiplied by their gains, as one Idea to DriveMO.
 *
 * <p>Each level rises with the need it represents and is in [0, 1] before its gain, except Effort,
 * which grows without bound for as long as a goal takes:
 * <ul>
 *   <li>Curiosity = boredom * yield. Boredom = 1 / (1 + novelty / scale): novelty is NoveltyArchive's
 *       sparseness over visit count, so boredom is high where the agent has been recently and falls
 *       where it has not. Yield ({@link CuriosityYield}, {@code Config.curiosityYield}) is whether
 *       exploring is still paying; 1 under "none", cap4 as written. Boredom alone never runs out,
 *       and kept Task from ever taking the goal (README, "Curiosity that runs out").</li>
 *   <li>Task = distance to the inferred stage's target / scale, capped at 1.</li>
 *   <li>Safety = 1 on any collision, else how far the closest joint has come into the margin before
 *       its limit.</li>
 *   <li>Effort = cycles since the current goal was set / scale.</li>
 * </ul>
 *
 * <p>Inputs: SensoryMO, GoalMO (Effort restarts when the goal changes; the GoalMO read is the
 * previous cycle's, since the Goal Generator runs after this), PlanTrackerMO (the habit whose
 * commands produced this observation -- last cycle's, likewise; only the "lp" yield uses it).
 * Output: DriveMO.
 */
public final class DriveGeneratorCodelet extends AgentCodelet {

    private final Config cfg;
    private final double[] gains;
    private final NoveltyArchive archive;
    private final CuriosityYield yield;
    private Memory sensoryMO;
    private Memory goalMO;
    private Memory trackerMO;
    private Memory driveMO;
    private long lastGoalId = Long.MIN_VALUE;
    private long cyclesOnGoal;

    public DriveGeneratorCodelet(Config cfg) {
        super("DriveGenerator");
        this.cfg = cfg;
        this.gains = cfg.gains.clone();
        this.archive = new NoveltyArchive(cfg.noveltyK, cfg.archiveAddThreshold, cfg.archiveCap,
                cfg.visitDecay);
        this.yield = Yields.byName(cfg.curiosityYield);
    }

    /** The phase switch of cap4 4.6.2 and the drive ablations of 4.6.1 are both gain settings. */
    public void setGain(int drive, double gain) {
        gains[drive] = gain;
    }

    public double gain(int drive) {
        return gains[drive];
    }

    public NoveltyArchive archive() {
        return archive;
    }

    /**
     * What outlives an episode, for a checkpoint: the novelty archive and the yield's history. Gains
     * follow the phase.
     */
    public JsonObject state() {
        JsonObject s = new JsonObject();
        s.add("archive", archive.state());
        s.add("yield", yield.state());
        return s;
    }

    public void restore(JsonObject s) {
        archive.restore(s.getAsJsonObject("archive"));
        yield.restore(s.getAsJsonObject("yield"));
    }

    @Override
    public void accessMemoryObjects() {
        if (sensoryMO == null) {
            sensoryMO = in("SensoryMO");
            goalMO = in("GoalMO");
            trackerMO = in("PlanTrackerMO");
            driveMO = out("DriveMO");
        }
    }

    @Override
    public void proc() {
        Observation observation = Observation.of(sensoryMO);
        double[] rawDriveLevels = new double[Drives.N];

        String binKey = Characterization.key(observation);
        double[] characterizationVector = Characterization.vector(observation, cfg.salience);   // b, cap4 4.3.1
        double novelty = archive.visit(characterizationVector, binKey, observation.cycle());
        double boredom = 1.0 / (1.0 + novelty / cfg.noveltyScale);
        double yieldFactor = yield.observe(observation, binKey, characterizationVector,   // y, CUR-01
                habitThatRan(observation));
        rawDriveLevels[Drives.CURIOSITY] = boredom * yieldFactor;

        int stage = TaskStages.infer(observation);
        rawDriveLevels[Drives.TASK] = Math.min(1.0,
                TaskStages.targetDistance(stage, observation) / cfg.taskDistanceScale);

        double safety = (observation.envCollision() || observation.selfCollision()) ? 1.0 : 0.0;
        for (double jointMargin : observation.jointLimitMargin()) {
            double limitProximity = 1.0 - jointMargin / cfg.safetyMargin;   // 1 at the limit, 0 at safetyMargin
            safety = Math.max(safety, Math.min(1.0, Math.max(0.0, limitProximity)));
        }
        rawDriveLevels[Drives.SAFETY] = safety;

        Goal goal = Goal.of(goalMO);
        long goalId = goal == null ? -1 : goal.id();
        boolean effortRestarted = observation.episodeStart() || goalId != lastGoalId;
        if (effortRestarted) {
            cyclesOnGoal = 0;
            lastGoalId = goalId;
        } else {
            cyclesOnGoal++;
        }
        rawDriveLevels[Drives.EFFORT] = cyclesOnGoal / cfg.effortScale;

        double[] gainedDriveLevels = new double[Drives.N];
        for (int drive = 0; drive < Drives.N; drive++) {
            gainedDriveLevels[drive] = gains[drive] * rawDriveLevels[drive];
        }
        driveMO.setI(Drives.toIdea(observation.cycle(), gainedDriveLevels, rawDriveLevels, stage,
                effortRestarted, novelty, boredom, yieldFactor));
    }

    /** The habit in execution last cycle, whose commands led to the observation; null if none ran. */
    private String habitThatRan(Observation observation) {
        Object trackerContent = trackerMO.getI();
        if (!(trackerContent instanceof TrackerState trackerState) || !trackerState.running()
                || trackerState.cycle() != observation.cycle() - 1) {
            return null;
        }
        return trackerState.habit();
    }
}
