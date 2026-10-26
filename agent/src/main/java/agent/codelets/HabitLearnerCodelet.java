package agent.codelets;

import agent.Config;
import agent.credit.CreditTable;
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
    private final Map<String, Idea> habitsById = new LinkedHashMap<>();
    private Memory creditMO;
    private MemoryContainer habitPool;

    public HabitLearnerCodelet(Config cfg, Mind mind) {
        super("HabitLearner");
        this.cfg = cfg;
        this.mind = mind;
    }

    @Override
    public void accessMemoryObjects() {
        if (creditMO == null) {
            creditMO = in("CreditMO");
            habitPool = (MemoryContainer) out("HabitPoolMC");
        }
    }

    /** Put the primary repertoire into the pool, before the first cycle. */
    public void seed(List<Idea> primitives) {
        accessMemoryObjects();
        for (Idea primitive : primitives) {
            add(primitive);
        }
    }

    private void add(Idea habit) {
        String habitId = HabitIdeas.id(habit);
        if (habitsById.containsKey(habitId)) {
            throw new IllegalArgumentException("duplicate habit id " + habitId);
        }
        MemoryObject poolMember = mind.createMemoryObject(habitId, habit);
        habitPool.add(poolMember);
        habitsById.put(habitId, habit);
    }

    public Map<String, Idea> habits() {
        return Collections.unmodifiableMap(habitsById);
    }

    /** Copy every habit's credit from the table: after a checkpoint is restored into it. */
    public void refreshCredit(CreditTable creditTable) {
        for (Map.Entry<String, Idea> habitEntry : habitsById.entrySet()) {
            HabitIdeas.setCredit(habitEntry.getValue(), creditTable.snapshot(habitEntry.getKey()));
        }
    }

    @Override
    public void proc() {
        Object creditContent = creditMO.getI();
        if (!(creditContent instanceof CreditUpdate creditUpdate)) {
            return;
        }
        for (String habitId : creditUpdate.changed()) {
            Idea habit = habitsById.get(habitId);
            if (habit != null) {
                HabitIdeas.setCredit(habit, creditUpdate.table().snapshot(habitId));
            }
        }
    }
}
