package agent.codelets;

import agent.Config;
import agent.memory.Goal;
import agent.motivation.Drives;
import agent.sim.Observation;
import agent.task.TaskStages;
import br.unicamp.cst.core.entities.Memory;

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
    private int stage;
    private String source = Goal.TASK;
    private String name;
    private long id;
    private long setAtCycle;

    public GoalGeneratorCodelet(Config cfg) {
        super("GoalGenerator");
        this.cfg = cfg;
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
        Observation o = Observation.of(sensoryMO);
        Drives drives = Drives.of(driveMO);
        boolean fresh = o.episodeStart() || name == null;
        if (o.episodeStart()) {
            stage = 0;
            source = Goal.TASK;
        }

        while (stage < TaskStages.DONE && TaskStages.termination(stage, o)
                && (stage + 1 == TaskStages.DONE || TaskStages.precondition(stage + 1, o))) {
            stage++;
        }
        if (stage < TaskStages.DONE && !TaskStages.precondition(stage, o)) {
            stage = TaskStages.infer(o);
        }

        String next = chooseSource(drives);
        String nextName = Goal.TASK.equals(next) ? TaskStages.name(stage)
                : Goal.CURIOSITY.equals(next) ? Goal.EXPLORE : Goal.RECOVER;
        if (fresh || !next.equals(source) || !nextName.equals(name)) {
            id++;
            setAtCycle = o.cycle();
        }
        source = next;
        name = nextName;
        double[] target = Goal.TASK.equals(source) ? TaskStages.target(stage, o) : new double[0];
        goalMO.setI(Goal.toIdea(id, source, name, stage, setAtCycle, target));
    }

    private String chooseSource(Drives d) {
        boolean safetyOk = d.raw(Drives.SAFETY) >= cfg.safetyGoalMet;
        boolean taskOk = stage < TaskStages.DONE;
        boolean curiosityOk = d.raw(Drives.CURIOSITY) >= cfg.curiosityGoalMet;
        if (safetyOk && d.level(Drives.SAFETY) >= cfg.safetyOverride) {
            return Goal.SAFETY;
        }
        // Candidates in tie-breaking order: safety, task, curiosity.
        String best = null;
        double bestLevel = Double.NEGATIVE_INFINITY;
        String[] names = {Goal.SAFETY, Goal.TASK, Goal.CURIOSITY};
        boolean[] ok = {safetyOk, taskOk, curiosityOk};
        int[] drive = {Drives.SAFETY, Drives.TASK, Drives.CURIOSITY};
        double current = Double.NEGATIVE_INFINITY;
        for (int i = 0; i < names.length; i++) {
            if (!ok[i]) {
                continue;
            }
            double level = d.level(drive[i]);
            if (level > bestLevel) {
                bestLevel = level;
                best = names[i];
            }
            if (names[i].equals(source)) {
                current = level;
            }
        }
        if (best == null) {
            return Goal.TASK;                   // nothing pressing: stay on the task, done or not
        }
        return current + cfg.goalHysteresis >= bestLevel ? source : best;
    }
}
