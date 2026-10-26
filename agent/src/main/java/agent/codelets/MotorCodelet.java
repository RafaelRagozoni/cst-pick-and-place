package agent.codelets;

import agent.Telemetry;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.TrackerState;
import agent.sim.Observation;
import agent.sim.SimLink;
import br.unicamp.cst.core.entities.Memory;

import java.util.List;

/**
 * Motor (cap4 4.2): reads the current step from PlanTrackerMO and sends its commands to the arm
 * through the bridge -- which advances the simulation exactly one step. With nothing running it
 * sends no records, and the actuator holds every joint still.
 *
 * <p>Inputs: PlanTrackerMO, SensoryMO (to skip the terminal observation, which is not acted on).
 */
public final class MotorCodelet extends AgentCodelet {

    private final SimLink link;
    private final Telemetry telemetry;
    private Memory trackerMO;
    private Memory sensoryMO;

    public MotorCodelet(SimLink link, Telemetry telemetry) {
        super("Motor");
        this.link = link;
        this.telemetry = telemetry;
    }

    @Override
    public void accessMemoryObjects() {
        if (trackerMO == null) {
            trackerMO = in("PlanTrackerMO");
            sensoryMO = in("SensoryMO");
        }
    }

    @Override
    public void proc() {
        if (Observation.of(sensoryMO).terminal()) {
            return;
        }
        TrackerState trackerState = (TrackerState) trackerMO.getI();
        List<Command> stepCommands = trackerState == null ? List.of() : trackerState.commands();
        link.step(HabitIdeas.toJson(stepCommands), telemetry == null ? null : telemetry.annotation());
    }
}
