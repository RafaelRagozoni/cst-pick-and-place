package agent.codelets;

import agent.Config;
import agent.habit.HabitIdeas;
import agent.memory.CreditUpdate;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.core.entities.MemoryObject;
import br.unicamp.cst.core.entities.Mind;
import br.unicamp.cst.representation.idea.Idea;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * HabitLearner (cap4 4.4): the only writer of the HabitPool.
 *
 * <p>What it does now (WP2): seeds the pool with the primary repertoire, one single-record habit per
 * primitive command, and every cycle copies the credit of the habits whose credit changed from
 * CreditMO into their pool members, where the Behavior Generator reads it. That copy runs in every
 * condition except C6, including C4, whose pool is frozen but whose selection is still motivated.
 *
 * <p>What it does not do yet (WP3): mutation, parallel fusion, macros at goal completion, culling.
 * {@code Config.generation} and {@code Config.fusion} already exist so the conditions are wired, but
 * nothing reads them until those operators are written.
 *
 * <p>Inputs: CreditMO, ExecutionBuffer (macros, WP3). Output: HabitPoolMC.
 */
public final class HabitLearnerCodelet extends AgentCodelet {

    private final Config cfg;
    private final Mind mind;
    private final Map<String, Idea> byId = new LinkedHashMap<>();
    private Memory creditMO;
    private MemoryContainer pool;

    public HabitLearnerCodelet(Config cfg, Mind mind) {
        super("HabitLearner");
        this.cfg = cfg;
        this.mind = mind;
    }

    @Override
    public void accessMemoryObjects() {
        if (creditMO == null) {
            creditMO = in("CreditMO");
            pool = (MemoryContainer) out("HabitPoolMC");
        }
    }

    /** Put the primary repertoire into the pool, before the first cycle. */
    public void seed(List<Idea> primitives) {
        accessMemoryObjects();
        for (Idea h : primitives) {
            add(h);
        }
    }

    private void add(Idea habit) {
        String id = HabitIdeas.id(habit);
        if (byId.containsKey(id)) {
            throw new IllegalArgumentException("duplicate habit id " + id);
        }
        MemoryObject member = mind.createMemoryObject(id, habit);
        pool.add(member);
        byId.put(id, habit);
    }

    public Map<String, Idea> habits() {
        return Collections.unmodifiableMap(byId);
    }

    @Override
    public void proc() {
        Object i = creditMO.getI();
        if (!(i instanceof CreditUpdate u)) {
            return;
        }
        for (String h : u.changed()) {
            Idea habit = byId.get(h);
            if (habit != null) {
                HabitIdeas.setCredit(habit, u.table().snapshot(h));
            }
        }
    }
}
