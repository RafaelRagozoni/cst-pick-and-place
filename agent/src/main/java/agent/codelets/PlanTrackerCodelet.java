package agent.codelets;

import agent.Config;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.ExecutionBuffer;
import agent.memory.Goal;
import agent.memory.Plan;
import agent.memory.TrackerState;
import agent.motivation.Drives;
import agent.sim.Observation;
import agent.sim.StepCompletion;
import br.unicamp.cst.core.entities.Memory;

import java.util.List;

/**
 * PlanTracker (cap4 4.3.3): TROCA's tracking rule applied to the steps of the habit in execution,
 * and to the goal.
 *
 * <p>It runs twice per cycle (AgentMind's schedule), and each call does what is pending:
 * <ol>
 *   <li><b>Track</b>, on the first call of a cycle: account the new observation against the current
 *       step (StepCompletion); a finished step is appended to ExecutionBuffer and the next one
 *       started. Then the goal: if the goal being tracked is met, close the plan and mark the goal's
 *       completion in ExecutionBuffer. PlanTrackerMO then tells the Behavior Generator whether a plan
 *       is still running.</li>
 *   <li><b>Load</b>, after the Behavior Generator: if PlanMO holds a new decision, replace the plan in
 *       execution and start it from its first step. Then publish the current step's commands for the
 *       Motor.</li>
 * </ol>
 * Running twice is what lets a habit that ends on this cycle's observation be followed by the next
 * one in the same cycle. With one call, either the Behavior Generator would decide before knowing the
 * plan had ended, or the Motor would act before the new plan was loaded; both cost an idle cycle per
 * habit, which is a third to a half of all cycles when habits are one-degree primitives.
 *
 * <p>Inputs: SensoryMO, GoalMO, DriveMO, PlanMO. Outputs: PlanTrackerMO, ExecutionBuffer.
 */
public final class PlanTrackerCodelet extends AgentCodelet {

    public static final String PREEMPTED = "preempted";
    public static final String CLOSED = "closed";
    public static final String INTERRUPTED = "interrupted";

    private final Config cfg;
    private Memory sensoryMO;
    private Memory goalMO;
    private Memory driveMO;
    private Memory planMO;
    private Memory trackerMO;
    private Memory executionMO;

    private long trackedCycle = Long.MIN_VALUE;
    private Plan plan;                  // in execution, or null
    private List<List<Command>> steps;
    private int stepIndex;
    private StepCompletion completion;
    private long stepStart;
    private long loadedSerial = -1;
    private Goal tracked;
    private long lastMetGoal = -1;

    public PlanTrackerCodelet(Config cfg) {
        super("PlanTracker");
        this.cfg = cfg;
    }

    @Override
    public void accessMemoryObjects() {
        if (sensoryMO == null) {
            sensoryMO = in("SensoryMO");
            goalMO = in("GoalMO");
            driveMO = in("DriveMO");
            planMO = in("PlanMO");
            trackerMO = out("PlanTrackerMO");
            executionMO = out("ExecutionBuffer");
        }
    }

    @Override
    public void proc() {
        Observation o = Observation.of(sensoryMO);
        ExecutionBuffer buffer = (ExecutionBuffer) executionMO.getI();
        if (o.cycle() != trackedCycle) {
            trackedCycle = o.cycle();
            track(o, buffer);
        } else {
            load(o, buffer);
        }
        executionMO.setI(buffer);
        trackerMO.setI(state(o));
    }

    private void track(Observation o, ExecutionBuffer buffer) {
        if (o.episodeStart()) {
            plan = null;
            tracked = null;
        }
        if (plan != null) {
            String outcome = completion.update(o);
            if (outcome != null) {
                record(buffer, o, outcome);
                stepIndex++;
                if (stepIndex >= steps.size()) {
                    plan = null;
                } else {
                    completion = new StepCompletion(steps.get(stepIndex), o);
                    stepStart = o.cycle();
                }
            }
        }

        if (tracked != null && tracked.met(o, Drives.of(driveMO), cfg.curiosityGoalMet,
                cfg.safetyGoalMet)) {
            if (plan != null) {
                record(buffer, o, CLOSED);
                plan = null;
            }
            buffer.addGoalMark(tracked.name(), tracked.id(), tracked.source(), o.cycle(), o.episode());
            lastMetGoal = tracked.id();
            tracked = null;
        }
        if (o.terminal() && plan != null) {
            record(buffer, o, INTERRUPTED);
            plan = null;
        }

        Goal goal = Goal.of(goalMO);
        if (goal != null && goal.id() != lastMetGoal && (tracked == null || goal.id() != tracked.id())) {
            tracked = goal;
        }
    }

    private void load(Observation o, ExecutionBuffer buffer) {
        Plan p = (Plan) planMO.getI();
        if (o.terminal() || p == null || p.serial() == loadedSerial) {
            return;
        }
        if (plan != null) {
            record(buffer, o, PREEMPTED);
        }
        loadedSerial = p.serial();
        steps = HabitIdeas.steps(p.habit());
        if (steps.isEmpty()) {
            plan = null;
            return;
        }
        plan = p;
        stepIndex = 0;
        completion = new StepCompletion(steps.get(0), o);
        stepStart = o.cycle();
    }

    /** Append the current step. A step cut on the cycle it started never ran, so it is not kept. */
    private void record(ExecutionBuffer buffer, Observation o, String outcome) {
        if (o.cycle() == stepStart) {
            return;
        }
        buffer.addStep(HabitIdeas.id(plan.habit()), plan.serial(), stepIndex, steps.size(),
                completion.records(), stepStart, o.cycle(), outcome, plan.goal(), plan.goalId(),
                plan.context(), o.episode());
    }

    private TrackerState state(Observation o) {
        if (plan == null) {
            return TrackerState.idle(o.cycle());
        }
        return new TrackerState(true, HabitIdeas.id(plan.habit()), plan.serial(), stepIndex,
                steps.size(), completion.commands(o), o.cycle());
    }
}
