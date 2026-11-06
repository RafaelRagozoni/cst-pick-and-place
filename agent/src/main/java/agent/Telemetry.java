package agent;

import agent.codelets.BehaviorGeneratorCodelet;
import agent.codelets.HabitLearnerCodelet;
import agent.habit.HabitIdeas;
import agent.memory.Goal;
import agent.memory.TrackerState;
import agent.motivation.Drives;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.function.DoubleSupplier;
import java.util.function.Supplier;

/**
 * What the agent attaches to each step of the bridge's run log (translog.py's {@code annotate}):
 * the habit in execution, the goal, the drive levels, Curiosity's yield, the selection mechanism and
 * the spread it used, the Curiosity yield's name, what was known when the plan in execution was
 * chosen, and the repertoire for metric 4.
 *
 * <p>Instrumentation, not part of the architecture: it reads memories but no codelet reads it, and
 * nothing the agent decides depends on it. Field names avoid the ones the log owns (translog.OWNED).
 */
public final class Telemetry {

    private final Memory trackerMO;
    private final Memory goalMO;
    private final Memory driveMO;
    private final MemoryContainer pool;
    private final String selection;
    private final String curiosity;
    private final DoubleSupplier spread;
    private final Supplier<BehaviorGeneratorCodelet.Choice> lastChoice;
    private final Supplier<List<HabitLearnerCodelet.MacroEvent>> macroEvents;
    private String phase = "bootstrap";

    /**
     * @param selection the selection mechanism's name
     * @param curiosity the Curiosity yield's name
     * @param spread    the spread the Behavior Generator's last selection used, read from it rather
     *                  than recomputed, so the log shows what the selector saw
     * @param lastChoice the Behavior Generator's last choice, logged with every step of its plan
     * @param macroEvents the HabitLearner's macro events of this cycle (vault spec MAC-01), logged
     *                    as "macro" on the step they happened in
     */
    public Telemetry(Memory trackerMO, Memory goalMO, Memory driveMO, MemoryContainer pool,
                     String selection, String curiosity, DoubleSupplier spread,
                     Supplier<BehaviorGeneratorCodelet.Choice> lastChoice,
                     Supplier<List<HabitLearnerCodelet.MacroEvent>> macroEvents) {
        this.trackerMO = trackerMO;
        this.goalMO = goalMO;
        this.driveMO = driveMO;
        this.pool = pool;
        this.selection = selection;
        this.curiosity = curiosity;
        this.spread = spread;
        this.lastChoice = lastChoice;
        this.macroEvents = macroEvents;
    }

    public void setPhase(String phase) {
        this.phase = phase;
    }

    public String phase() {
        return phase;
    }

    public JsonObject annotation() {
        JsonObject a = new JsonObject();
        TrackerState ts = (TrackerState) trackerMO.getI();
        boolean running = ts != null && ts.running();
        a.addProperty("habit_id", running ? ts.habit() : "idle");
        if (running) {
            a.addProperty("plan", ts.planSerial());
            a.addProperty("planStep", ts.stepIndex());
        }
        Goal g = Goal.of(goalMO);
        if (g != null) {
            a.addProperty("goal", g.name());
            a.addProperty("goalSource", g.source());
        }
        Drives d = Drives.of(driveMO);
        if (d != null) {
            JsonObject dj = new JsonObject();
            for (int i = 0; i < Drives.N; i++) {
                dj.addProperty(Drives.NAMES[i], d.level(i));
            }
            a.add("drives", dj);
            a.addProperty("novelty", d.novelty());
            a.addProperty("yield", d.curiosityYield());
        }
        a.addProperty("phase", phase);
        a.addProperty("selection", selection);
        a.addProperty("curiosity", curiosity);
        a.addProperty("spread", spread.getAsDouble());
        BehaviorGeneratorCodelet.Choice choice = lastChoice.get();
        if (running && choice != null && choice.planSerial() == ts.planSerial()) {
            JsonObject c = new JsonObject();
            c.addProperty("executionsHere", choice.executionsHere());
            c.addProperty("priorCount", choice.priorCount());
            c.addProperty("untried", choice.untried());
            c.addProperty("candidates", choice.candidates());
            a.add("choice", c);
        }
        List<HabitLearnerCodelet.MacroEvent> events = macroEvents.get();
        if (!events.isEmpty()) {
            JsonArray eventsJson = new JsonArray();
            events.forEach(event -> eventsJson.add(event.toJson()));
            a.add("macro", eventsJson);
        }
        a.add("repertoire", repertoire());
        return a;
    }

    /**
     * What goes on the episode's terminal record: the macro events of the terminal cycle (a Task
     * stage met on the last observation, the release of every success, builds its macro there), or
     * null when there are none, so a run without them logs as before. The rest of the step
     * annotation describes acting, and the terminal cycle does not act.
     */
    public JsonObject terminalAnnotation() {
        List<HabitLearnerCodelet.MacroEvent> events = macroEvents.get();
        if (events.isEmpty()) {
            return null;
        }
        JsonArray eventsJson = new JsonArray();
        events.forEach(event -> eventsJson.add(event.toJson()));
        JsonObject terminal = new JsonObject();
        terminal.add("macro", eventsJson);
        return terminal;
    }

    /**
     * Pool size and how many habits each operator produced: metric 4's raw material. Retired macros
     * (MAC-01 D4) stay in the pool but are counted apart, as "retired", and not in "size": a
     * repertoire that grew only by replacing would otherwise look like one that grew.
     */
    public JsonObject repertoire() {
        Map<String, Integer> byOrigin = new TreeMap<>();
        int n = 0;
        for (Memory m : pool.getAllMemories()) {
            Idea habit = (Idea) m.getI();
            if (HabitIdeas.isRetired(habit)) {
                byOrigin.merge("retired", 1, Integer::sum);
                continue;
            }
            byOrigin.merge(HabitIdeas.origin(habit), 1, Integer::sum);
            n++;
        }
        JsonObject r = new JsonObject();
        r.addProperty("size", n);
        for (Map.Entry<String, Integer> e : byOrigin.entrySet()) {
            r.addProperty(e.getKey(), e.getValue());
        }
        return r;
    }
}
