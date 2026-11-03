package agent.habit;

import agent.sim.StepCompletion;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * The first rule of vault spec MAC-01: each joint's net turn between two gripper events, as one
 * parallel step.
 *
 * <p>It adds up each joint's angle over the steps (D8: the commanded angle; the HabitLearner hands
 * a step cut short as far as it ran). At every GRAB that changes what the gripper was last told
 * (D7), it closes one parallel step with the joints whose net turn is not zero, puts the GRAB as
 * the next step and starts over. A GRAB that repeats the last one kept is dropped; the first one is
 * kept, because the gripper's state when the stretch began is not in the ExecutionBuffer.
 *
 * <p>Speeds (D9) make every joint of a parallel step finish together, the synchronous
 * point-to-point move of industrial controllers: the joint that turns most goes at the fastest speed
 * its commands had (0.4 rad/s for the primitives), the others in proportion, none below
 * {@link #MINIMUM_JOINT_SPEED}. A joint whose net turn is within StepCompletion.ANGLE_TOL is left
 * out: the step would count it finished at once.
 */
public final class SumRule implements MacroRule {

    /**
     * Slowest speed a joint of a summed step gets, rad/s. The PlanTracker takes a joint that turns
     * less than StepCompletion.STALL_ANGLE (0.01 deg) in a 50 ms tick for blocked, i.e. below
     * ~0.0035 rad/s; this is ~6 times that. A joint held to it finishes before the others, which
     * changes the path but not where it ends.
     */
    public static final double MINIMUM_JOINT_SPEED = 0.02;

    @Override
    public List<Command> build(List<List<Command>> executedSteps) {
        List<Command> macroCommands = new ArrayList<>();
        Map<Integer, Double> netTurnByJoint = new TreeMap<>();
        Map<Integer, Command> lastMoveByJoint = new TreeMap<>();
        double fastestSpeed = 0.0;
        Boolean lastGripperOpening = null;
        for (List<Command> step : executedSteps) {
            for (Command command : step) {
                if (command.isMove()) {
                    netTurnByJoint.merge(command.joint(), command.angle(), Double::sum);
                    lastMoveByJoint.put(command.joint(), command);
                    fastestSpeed = Math.max(fastestSpeed, Math.abs(command.speed()));
                } else if (command.isGrab()) {
                    boolean opening = command.force() < 0;
                    if (lastGripperOpening != null && lastGripperOpening == opening) {
                        continue;
                    }
                    addParallelStep(macroCommands, netTurnByJoint, lastMoveByJoint, fastestSpeed);
                    macroCommands.add(command.withStep(nextStepIndex(macroCommands)));
                    lastGripperOpening = opening;
                    netTurnByJoint.clear();
                    lastMoveByJoint.clear();
                    fastestSpeed = 0.0;
                }
                // HOLD turns nothing and changes nothing: it adds nothing to the sum.
            }
        }
        addParallelStep(macroCommands, netTurnByJoint, lastMoveByJoint, fastestSpeed);
        return macroCommands;
    }

    private static void addParallelStep(List<Command> macroCommands, Map<Integer, Double> netTurnByJoint,
                                        Map<Integer, Command> lastMoveByJoint, double fastestSpeed) {
        double largestTurn = 0.0;
        for (double netTurn : netTurnByJoint.values()) {
            if (Math.abs(netTurn) > StepCompletion.ANGLE_TOL) {
                largestTurn = Math.max(largestTurn, Math.abs(netTurn));
            }
        }
        if (largestTurn == 0.0) {
            return;
        }
        int stepIndex = nextStepIndex(macroCommands);
        for (Map.Entry<Integer, Double> joint : netTurnByJoint.entrySet()) {
            double netTurn = joint.getValue();
            if (Math.abs(netTurn) <= StepCompletion.ANGLE_TOL) {
                continue;
            }
            double speed = Math.max(MINIMUM_JOINT_SPEED, fastestSpeed * Math.abs(netTurn) / largestTurn);
            macroCommands.add(lastMoveByJoint.get(joint.getKey()).withAngle(netTurn).withSpeed(speed)
                    .withStep(stepIndex));
        }
    }

    private static int nextStepIndex(List<Command> macroCommands) {
        return macroCommands.isEmpty() ? 0 : macroCommands.get(macroCommands.size() - 1).step() + 1;
    }
}
