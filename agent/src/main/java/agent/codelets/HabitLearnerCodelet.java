package agent.codelets;

import agent.Config;
import agent.credit.CreditTable;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.habit.MacroRule;
import agent.memory.CreditUpdate;
import agent.memory.ExecutionBuffer;
import agent.memory.Goal;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.core.entities.MemoryObject;
import br.unicamp.cst.core.entities.Mind;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * HabitLearner (cap4 4.4): the only writer of the HabitPool.
 *
 * <p>What it does: seeds the pool with the primary repertoire, one single-record habit per
 * primitive command, and every cycle copies the credit of the habits whose credit changed from
 * CreditMO into their pool members, where the Behavior Generator reads it. That copy runs in every
 * condition except C6, including C4, whose pool is frozen but whose selection is still motivated.
 *
 * <p>Macros at goal completion (vault spec MAC-01), when {@code Config.macroRule} is not "none":
 * <ol>
 *   <li>It reads the ExecutionBuffer's new entries, as Credit Assignment does, and keeps the steps
 *       since the last Task goal mark of the episode, or its start (D2). Curiosity's and Safety's
 *       steps in between stay in.</li>
 *   <li>At a Task goal mark (D3), the stretch's initiation is the goal met plus the state bin of its
 *       first step: the context the macro may be chosen in (D1).</li>
 *   <li>If that context has an active macro, and the stretch is not shorter in steps, it is a
 *       repetition. A shorter one retires the active macro -- it stays in the pool with its credit,
 *       never chosen again -- and builds another (D4).</li>
 *   <li>The rule builds the macro's commands from the steps, a step that ran to its end as commanded
 *       (D8), one cut short as far as it ran. Nothing is built from an empty result or one equal to
 *       a habit already in the pool: a macro that ran alone and met its goal rebuilds itself, and
 *       retiring it for its own copy would throw its credit away.</li>
 *   <li>A new context finds the pool at {@code maxActiveMacros} active macros: refused (D10).
 *       Otherwise the macro {@code macro_<goal>_<n>} joins the pool with empty credit (D5).</li>
 * </ol>
 * Each of these is a macro event, which the run log carries ({@link #macroEvents}).
 *
 * <p>What it does not do yet (WP3): mutation, parallel fusion, culling.
 *
 * <p>Inputs: CreditMO, ExecutionBuffer. Output: HabitPoolMC.
 */
public final class HabitLearnerCodelet extends AgentCodelet {

    public static final String CREATED = "created";
    public static final String REPLACED = "replaced";
    public static final String REPEATED = "repeated";
    public static final String EXISTS = "exists";
    public static final String EMPTY = "empty";
    public static final String REFUSED = "refused";

    /**
     * What happened at one Task goal mark. {@code macro} is the macro created, or the habit already
     * there for a repetition or an equal result (null when none); {@code retired} the macro a shorter
     * stretch replaced.
     */
    public record MacroEvent(String kind, String goal, String initiation, int stretchSteps,
                             String macro, String retired) {

        public JsonObject toJson() {
            JsonObject event = new JsonObject();
            event.addProperty("kind", kind);
            event.addProperty("goal", goal);
            event.addProperty("initiation", initiation);
            event.addProperty("stretchSteps", stretchSteps);
            event.addProperty("macro", macro);
            event.addProperty("retired", retired);
            return event;
        }
    }

    private final Config cfg;
    private final Mind mind;
    private final MacroRule macroRule;
    private final Map<String, Idea> habitsById = new LinkedHashMap<>();
    private int primitiveCount;
    private Memory creditMO;
    private Memory executionMO;
    private MemoryContainer habitPool;

    private long nextUnreadSeq;
    private int stretchEpisode = -1;
    private final List<ExecutionBuffer.Step> stretch = new ArrayList<>();
    private final Map<String, Idea> activeMacroByInitiation = new HashMap<>();
    private final Map<String, Integer> macrosBuiltByGoal = new HashMap<>();
    private final List<MacroEvent> macroEvents = new ArrayList<>();

    public HabitLearnerCodelet(Config cfg, Mind mind) {
        super("HabitLearner");
        this.cfg = cfg;
        this.mind = mind;
        boolean buildsMacros = !cfg.macroRule.equals("none") && cfg.generation && cfg.fusion;
        this.macroRule = buildsMacros ? MacroRule.byName(cfg.macroRule) : null;
    }

    @Override
    public void accessMemoryObjects() {
        if (creditMO == null) {
            creditMO = in("CreditMO");
            executionMO = in("ExecutionBuffer");
            habitPool = (MemoryContainer) out("HabitPoolMC");
        }
    }

    /** Put the primary repertoire into the pool, before the first cycle. */
    public void seed(List<Idea> primitives) {
        accessMemoryObjects();
        for (Idea primitive : primitives) {
            add(primitive);
        }
        primitiveCount = habitsById.size();
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

    /** The macro events of the last cycle, for the run log; empty on most cycles. */
    public List<MacroEvent> macroEvents() {
        return Collections.unmodifiableList(macroEvents);
    }

    /** Copy every habit's credit from the table: after a checkpoint is restored into it. */
    public void refreshCredit(CreditTable creditTable) {
        for (Map.Entry<String, Idea> habitEntry : habitsById.entrySet()) {
            HabitIdeas.setCredit(habitEntry.getValue(), creditTable.snapshot(habitEntry.getKey()));
        }
    }

    @Override
    public void proc() {
        macroEvents.clear();
        Object creditContent = creditMO.getI();
        if (creditContent instanceof CreditUpdate creditUpdate) {
            for (String habitId : creditUpdate.changed()) {
                Idea habit = habitsById.get(habitId);
                if (habit != null) {
                    HabitIdeas.setCredit(habit, creditUpdate.table().snapshot(habitId));
                }
            }
        }
        if (macroRule == null) {
            return;
        }
        ExecutionBuffer executionBuffer = (ExecutionBuffer) executionMO.getI();
        for (ExecutionBuffer.Entry entry : executionBuffer.since(nextUnreadSeq)) {
            if (entry instanceof ExecutionBuffer.Step step) {
                startStretchIfNewEpisode(step.episode());
                stretch.add(step);
            } else if (entry instanceof ExecutionBuffer.GoalMark goalMark) {
                startStretchIfNewEpisode(goalMark.episode());
                if (Goal.TASK.equals(goalMark.source())) {
                    if (!stretch.isEmpty()) {
                        consolidate(goalMark.goal());
                    }
                    stretch.clear();
                }
            }
        }
        nextUnreadSeq = executionBuffer.nextSeq();
    }

    private void startStretchIfNewEpisode(int episode) {
        if (episode != stretchEpisode) {
            stretch.clear();
            stretchEpisode = episode;
        }
    }

    /** Steps 2-5 of the class comment, for the stretch that ended with {@code goal} met. */
    private void consolidate(String goal) {
        String firstContext = stretch.get(0).context();
        String initiation = CreditTable.context(goal,
                firstContext.substring(firstContext.indexOf('|') + 1));
        int stretchSteps = stretch.size();
        Idea activeMacro = activeMacroByInitiation.get(initiation);
        if (activeMacro != null && stretchSteps >= HabitIdeas.stretchSteps(activeMacro)) {
            macroEvents.add(new MacroEvent(REPEATED, goal, initiation, stretchSteps,
                    HabitIdeas.id(activeMacro), null));
            return;
        }
        List<List<Command>> executedSteps = new ArrayList<>();
        Set<String> parents = new LinkedHashSet<>();
        for (ExecutionBuffer.Step step : stretch) {
            executedSteps.add(step.ranToItsEnd() ? step.commands() : step.executedCommands());
            parents.add(step.habit());
        }
        List<Command> macroCommands = macroRule.build(executedSteps);
        if (macroCommands.isEmpty()) {
            macroEvents.add(new MacroEvent(EMPTY, goal, initiation, stretchSteps, null, null));
            return;
        }
        Idea sameHabit = habitWithCommands(macroCommands);
        if (sameHabit != null) {
            macroEvents.add(new MacroEvent(EXISTS, goal, initiation, stretchSteps,
                    HabitIdeas.id(sameHabit), null));
            return;
        }
        if (activeMacro == null && activeMacroByInitiation.size() >= cfg.maxActiveMacros) {
            macroEvents.add(new MacroEvent(REFUSED, goal, initiation, stretchSteps, null, null));
            return;
        }
        int number = macrosBuiltByGoal.merge(goal, 1, Integer::sum);
        Idea macro = HabitIdeas.createMacro("macro_" + goal + "_" + number, new ArrayList<>(parents),
                macroCommands, initiation, stretchSteps);
        if (activeMacro != null) {
            HabitIdeas.retire(activeMacro);
        }
        add(macro);
        activeMacroByInitiation.put(initiation, macro);
        macroEvents.add(new MacroEvent(activeMacro == null ? CREATED : REPLACED, goal, initiation,
                stretchSteps, HabitIdeas.id(macro),
                activeMacro == null ? null : HabitIdeas.id(activeMacro)));
    }

    /** A habit in the pool, retired or not, with exactly these commands; null if none. */
    private Idea habitWithCommands(List<Command> commands) {
        for (Idea habit : habitsById.values()) {
            if (HabitIdeas.commands(habit).equals(commands)) {
                return habit;
            }
        }
        return null;
    }

    /**
     * What outlives an episode, for a checkpoint: the habits it built, in the order they joined the
     * pool, their numbering, and how far it has read the ExecutionBuffer. The stretch does not: it
     * starts over with every episode.
     */
    public JsonObject state() {
        JsonArray built = new JsonArray();
        List<Idea> habits = new ArrayList<>(habitsById.values());
        for (Idea habit : habits.subList(primitiveCount, habits.size())) {
            JsonObject habitJson = new JsonObject();
            habitJson.addProperty("id", HabitIdeas.id(habit));
            habitJson.addProperty("origin", HabitIdeas.origin(habit));
            JsonArray parents = new JsonArray();
            HabitIdeas.parents(habit).forEach(parents::add);
            habitJson.add("parents", parents);
            habitJson.add("commands", HabitIdeas.toJson(HabitIdeas.commands(habit)));
            habitJson.addProperty("initiation", HabitIdeas.initiation(habit));
            habitJson.addProperty("stretchSteps", HabitIdeas.stretchSteps(habit));
            habitJson.addProperty("retired", HabitIdeas.isRetired(habit));
            built.add(habitJson);
        }
        JsonObject numbering = new JsonObject();
        macrosBuiltByGoal.forEach(numbering::addProperty);
        JsonObject stateJson = new JsonObject();
        stateJson.add("built", built);
        stateJson.add("macrosBuiltByGoal", numbering);
        stateJson.addProperty("readSeq", nextUnreadSeq);
        return stateJson;
    }

    /** Put back the habits a checkpoint holds, into a learner seeded and not yet run. */
    public void restore(JsonObject stateJson) {
        if (habitsById.size() != primitiveCount) {
            throw new IllegalStateException("restore a HabitLearner before it builds anything");
        }
        for (JsonElement element : stateJson.getAsJsonArray("built")) {
            JsonObject habitJson = element.getAsJsonObject();
            if (!HabitIdeas.MACRO.equals(habitJson.get("origin").getAsString())) {
                throw new IllegalArgumentException("a checkpoint holds a habit of origin "
                        + habitJson.get("origin") + ", which this agent does not build");
            }
            List<Command> commands = new ArrayList<>();
            for (JsonElement command : habitJson.getAsJsonArray("commands")) {
                commands.add(Command.fromJson(command.getAsJsonObject()));
            }
            List<String> parents = new ArrayList<>();
            habitJson.getAsJsonArray("parents").forEach(parent -> parents.add(parent.getAsString()));
            Idea macro = HabitIdeas.createMacro(habitJson.get("id").getAsString(), parents, commands,
                    habitJson.get("initiation").getAsString(),
                    habitJson.get("stretchSteps").getAsInt());
            if (habitJson.get("retired").getAsBoolean()) {
                HabitIdeas.retire(macro);
            } else {
                activeMacroByInitiation.put(HabitIdeas.initiation(macro), macro);
            }
            add(macro);
        }
        macrosBuiltByGoal.clear();
        stateJson.getAsJsonObject("macrosBuiltByGoal").entrySet()
                .forEach(entry -> macrosBuiltByGoal.put(entry.getKey(), entry.getValue().getAsInt()));
        nextUnreadSeq = stateJson.get("readSeq").getAsLong();
    }
}
