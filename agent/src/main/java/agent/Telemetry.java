package agent;

import agent.habit.HabitIdeas;
import agent.memory.Goal;
import agent.memory.TrackerState;
import agent.motivation.Drives;
import br.unicamp.cst.core.entities.Memory;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;

import java.util.Map;
import java.util.TreeMap;
import java.util.function.DoubleSupplier;

/**
 * What the agent attaches to each step of the bridge's run log (translog.py's {@code annotate}):
 * the habit in execution, the goal, the drive levels, the selection mechanism and the spread it
 * used, and the repertoire for metric 4.
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
    private final DoubleSupplier spread;
    private String phase = "bootstrap";

    /**
     * @param selection the selection mechanism's name
     * @param spread    the spread the Behavior Generator's last selection used, read from it rather
     *                  than recomputed, so the log shows what the selector saw
     */
    public Telemetry(Memory trackerMO, Memory goalMO, Memory driveMO, MemoryContainer pool,
                     String selection, DoubleSupplier spread) {
        this.trackerMO = trackerMO;
        this.goalMO = goalMO;
        this.driveMO = driveMO;
        this.pool = pool;
        this.selection = selection;
        this.spread = spread;
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
        }
        a.addProperty("phase", phase);
        a.addProperty("selection", selection);
        a.addProperty("spread", spread.getAsDouble());
        a.add("repertoire", repertoire());
        return a;
    }

    /** Pool size and how many habits each operator produced: metric 4's raw material. */
    public JsonObject repertoire() {
        Map<String, Integer> byOrigin = new TreeMap<>();
        int n = 0;
        for (Memory m : pool.getAllMemories()) {
            byOrigin.merge(HabitIdeas.origin((Idea) m.getI()), 1, Integer::sum);
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
