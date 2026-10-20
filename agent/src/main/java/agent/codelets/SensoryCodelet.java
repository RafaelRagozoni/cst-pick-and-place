package agent.codelets;

import agent.memory.SensoryBuffer;
import agent.sim.Observation;
import agent.sim.SimLink;
import agent.task.Carry;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.representation.idea.Idea;

/**
 * Sensory (cap4 4.2): reads the simulator through the bridge and writes one Idea to SensoryMO,
 * appending it to SensoryBuffer. The Idea also holds what the agent remembers of the carry
 * ({@link Carry}), forgotten when an episode starts, like the buffer.
 *
 * <p>Outputs: SensoryMO, SensoryBuffer.
 */
public final class SensoryCodelet extends AgentCodelet {

    private final SimLink link;
    private final Carry carry = new Carry();
    private Memory sensoryMO;
    private Memory bufferMO;

    public SensoryCodelet(SimLink link) {
        super("Sensory");
        this.link = link;
    }

    @Override
    public void accessMemoryObjects() {
        if (sensoryMO == null) {
            sensoryMO = out("SensoryMO");
            bufferMO = out("SensoryBuffer");
        }
    }

    @Override
    public void proc() {
        Idea obs = Observation.toIdea(link.latest().getAsJsonObject("obs"), link.cycle(),
                link.episode(), link.episodeStart(), link.done());
        SensoryBuffer buffer = (SensoryBuffer) bufferMO.getI();
        if (link.episodeStart()) {
            buffer.clear();
            carry.reset();
        }
        carry.observe(obs);
        buffer.add(obs);
        bufferMO.setI(buffer);
        sensoryMO.setI(obs);
    }
}
