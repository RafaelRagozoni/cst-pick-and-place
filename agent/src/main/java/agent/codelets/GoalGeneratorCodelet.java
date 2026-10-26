package agent.codelets;

import agent.Config;
import agent.memory.Goal;
import agent.motivation.Drives;
import agent.sim.Observation;
import agent.task.TaskStages;
import br.unicamp.cst.core.entities.Memory;
import com.google.gson.JsonObject;

/**
 * Goal Generator (cap4 4.3.3): decides what the agent pursues and writes it to GoalMO.
 *
 * <p>Two decisions, every cycle:
 * <ol>
 *   <li>The task stage, by TROCA's tracking rule over the static plan reach / grasp / transport /
 *       release: move to the next stage when the current one's termination holds and the next one's
 *       precondition is met. If the current stage's own precondition stops holding -- the cube was
 *       dropped mid-transport -- fall back to the stage perception shows.</li>
 *   <li>Which drive sets the goal: of the three that carry goals, the most pressing. Safety at or above
 *       {@code safetyOverride} takes over outright (TROCA's Avoid Collision subsumes the rest);
 *       otherwise a drive must beat the one holding the goal by {@code goalHysteresis}, so goals do
 *       not flicker between two drives at similar levels. A drive whose goal is already met is not a
 *       candidate, or it would be set and completed on alternate cycles.</li>
 * </ol>
 *
 * <p>Inputs: SensoryMO, DriveMO. Output: GoalMO.
 */
public final class GoalGeneratorCodelet extends AgentCodelet {

    private final Config cfg;
    private Memory sensoryMO;
    private Memory driveMO;
    private Memory goalMO;
    private int taskStage;
    private String goalSource = Goal.TASK;
    private String goalName;
    private long goalId;
    private long goalSetAtCycle;

    public GoalGeneratorCodelet(Config cfg) {
        super("GoalGenerator");
        this.cfg = cfg;
    }

    /** What outlives an episode, for a checkpoint: the goal numbering. The rest restarts per episode. */
    public JsonObject state() {
        JsonObject s = new JsonObject();
        s.addProperty("id", goalId);
        return s;
    }

    public void restore(JsonObject s) {
        goalId = s.get("id").getAsLong();
    }

    @Override
    public void accessMemoryObjects() {
        if (sensoryMO == null) {
            sensoryMO = in("SensoryMO");
            driveMO = in("DriveMO");
            goalMO = out("GoalMO");
        }
    }

    @Override
    public void proc() {
        Observation observation = Observation.of(sensoryMO);
        Drives drives = Drives.of(driveMO);
        boolean forceNewGoal = observation.episodeStart() || goalName == null;
        if (observation.episodeStart()) {
            taskStage = 0;
            goalSource = Goal.TASK;
        }

        while (taskStage < TaskStages.DONE && TaskStages.termination(taskStage, observation)
                && (taskStage + 1 == TaskStages.DONE
                    || TaskStages.precondition(taskStage + 1, observation))) {
            taskStage++;
        }
        if (taskStage < TaskStages.DONE && !TaskStages.precondition(taskStage, observation)) {
            taskStage = TaskStages.infer(observation);
        }

        String nextGoalSource = chooseGoalSource(drives);
        String nextGoalName = Goal.TASK.equals(nextGoalSource) ? TaskStages.name(taskStage)
                : Goal.CURIOSITY.equals(nextGoalSource) ? Goal.EXPLORE : Goal.RECOVER;
        if (forceNewGoal || !nextGoalSource.equals(goalSource) || !nextGoalName.equals(goalName)) {
            goalId++;
            goalSetAtCycle = observation.cycle();
        }
        goalSource = nextGoalSource;
        goalName = nextGoalName;
        double[] taskTarget = Goal.TASK.equals(goalSource)
                ? TaskStages.target(taskStage, observation) : new double[0];
        goalMO.setI(Goal.toIdea(goalId, goalSource, goalName, taskStage, goalSetAtCycle, taskTarget));
    }

    private String chooseGoalSource(Drives drives) {
        boolean safetyIsCandidate = drives.raw(Drives.SAFETY) >= cfg.safetyGoalMet;
        boolean taskIsCandidate = taskStage < TaskStages.DONE;
        boolean curiosityIsCandidate = drives.boredom() >= cfg.curiosityGoalMet;
        if (safetyIsCandidate && drives.level(Drives.SAFETY) >= cfg.safetyOverride) {
            return Goal.SAFETY;
        }
        // Sources in tie-breaking order: safety, task, curiosity.
        String strongestSource = null;
        double strongestLevel = Double.NEGATIVE_INFINITY;
        String[] sources = {Goal.SAFETY, Goal.TASK, Goal.CURIOSITY};
        boolean[] sourceIsCandidate = {safetyIsCandidate, taskIsCandidate, curiosityIsCandidate};
        int[] sourceDrives = {Drives.SAFETY, Drives.TASK, Drives.CURIOSITY};
        double currentSourceLevel = Double.NEGATIVE_INFINITY;
        for (int i = 0; i < sources.length; i++) {
            if (!sourceIsCandidate[i]) {
                continue;
            }
            double sourceLevel = drives.level(sourceDrives[i]);
            if (sourceLevel > strongestLevel) {
                strongestLevel = sourceLevel;
                strongestSource = sources[i];
            }
            if (sources[i].equals(goalSource)) {
                currentSourceLevel = sourceLevel;
            }
        }
        if (strongestSource == null) {
            return Goal.TASK;                   // nothing pressing: stay on the task, done or not
        }
        return currentSourceLevel + cfg.goalHysteresis >= strongestLevel ? goalSource : strongestSource;
    }
}
