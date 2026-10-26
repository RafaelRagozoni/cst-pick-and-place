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

    private long lastTrackedCycle = Long.MIN_VALUE;
    private Plan plan;                  // in execution, or null
    private List<List<Command>> planSteps;
    private int stepIndex;
    private StepCompletion stepCompletion;
    private long stepStartCycle;
    private long loadedPlanSerial = -1;
    private Goal trackedGoal;
    private long lastMetGoalId = -1;

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
        Observation observation = Observation.of(sensoryMO);
        ExecutionBuffer executionBuffer = (ExecutionBuffer) executionMO.getI();
        if (observation.cycle() != lastTrackedCycle) {
            lastTrackedCycle = observation.cycle();
            track(observation, executionBuffer);
        } else {
            load(observation, executionBuffer);
        }
        executionMO.setI(executionBuffer);
        trackerMO.setI(state(observation));
    }

    private void track(Observation observation, ExecutionBuffer executionBuffer) {
        if (observation.episodeStart()) {
            plan = null;
            trackedGoal = null;
        }
        if (plan != null) {
            String stepOutcome = stepCompletion.update(observation);
            if (stepOutcome != null) {
                record(executionBuffer, observation, stepOutcome);
                stepIndex++;
                if (stepIndex >= planSteps.size()) {
                    plan = null;
                } else {
                    stepCompletion = new StepCompletion(planSteps.get(stepIndex), observation);
                    stepStartCycle = observation.cycle();
                }
            }
        }

        if (trackedGoal != null && trackedGoal.met(observation, Drives.of(driveMO), cfg.curiosityGoalMet,
                cfg.safetyGoalMet)) {
            if (plan != null) {
                record(executionBuffer, observation, CLOSED);
                plan = null;
            }
            executionBuffer.addGoalMark(trackedGoal.name(), trackedGoal.id(), trackedGoal.source(),
                    observation.cycle(), observation.episode());
            lastMetGoalId = trackedGoal.id();
            trackedGoal = null;
        }
        if (observation.terminal() && plan != null) {
            record(executionBuffer, observation, INTERRUPTED);
            plan = null;
        }

        Goal currentGoal = Goal.of(goalMO);
        if (currentGoal != null && currentGoal.id() != lastMetGoalId
                && (trackedGoal == null || currentGoal.id() != trackedGoal.id())) {
            trackedGoal = currentGoal;
        }
    }

    private void load(Observation observation, ExecutionBuffer executionBuffer) {
        Plan decidedPlan = (Plan) planMO.getI();
        if (observation.terminal() || decidedPlan == null || decidedPlan.serial() == loadedPlanSerial) {
            return;
        }
        if (plan != null) {
            record(executionBuffer, observation, PREEMPTED);
        }
        loadedPlanSerial = decidedPlan.serial();
        planSteps = HabitIdeas.steps(decidedPlan.habit());
        if (planSteps.isEmpty()) {
            plan = null;
            return;
        }
        plan = decidedPlan;
        stepIndex = 0;
        stepCompletion = new StepCompletion(planSteps.get(0), observation);
        stepStartCycle = observation.cycle();
    }

    /** Append the current step. A step cut on the cycle it started never ran, so it is not kept. */
    private void record(ExecutionBuffer executionBuffer, Observation observation, String stepOutcome) {
        if (observation.cycle() == stepStartCycle) {
            return;
        }
        executionBuffer.addStep(HabitIdeas.id(plan.habit()), plan.serial(), stepIndex, planSteps.size(),
                stepCompletion.records(), stepStartCycle, observation.cycle(), stepOutcome, plan.goal(),
                plan.goalId(), plan.context(), observation.episode());
    }

    private TrackerState state(Observation observation) {
        if (plan == null) {
            return TrackerState.idle(observation.cycle());
        }
        return new TrackerState(true, HabitIdeas.id(plan.habit()), plan.serial(), stepIndex,
                planSteps.size(), stepCompletion.commands(observation), observation.cycle());
    }
}
