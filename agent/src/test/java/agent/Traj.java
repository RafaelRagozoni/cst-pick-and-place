package agent;

import agent.sim.Observation;
import agent.task.Carry;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * The recorded expert trajectory (coppelia_environment/traj.jsonl), as JSON and as SensoryMO -- with
 * the carry the Sensory codelet would remember, having perceived it from the first observation.
 */
public final class Traj {

    private static List<JsonObject> cache;
    private static List<Idea> carries;

    private Traj() {
    }

    public static Path simDir() {
        return Path.of(System.getProperty("sim.dir", "../coppelia_environment"));
    }

    public static synchronized List<JsonObject> json() {
        if (cache == null) {
            try {
                List<JsonObject> out = new ArrayList<>();
                for (String line : Files.readAllLines(simDir().resolve("traj.jsonl"))) {
                    if (!line.isBlank()) {
                        out.add(JsonParser.parseString(line).getAsJsonObject());
                    }
                }
                cache = out;
            } catch (IOException e) {
                throw new IllegalStateException("cannot read traj.jsonl under " + simDir(), e);
            }
        }
        return cache;
    }

    /** Observation i, numbered as cycle i of episode 0. */
    public static Observation obs(int i) {
        Idea o = Observation.toIdea(json().get(i), i, 0, i == 0, false);
        Observation c = new Observation(carries().get(i));
        Observation.setCarry(o, c.carried(), c.placing(), c.still());
        return new Observation(o);
    }

    private static synchronized List<Idea> carries() {
        if (carries == null) {
            Carry carry = new Carry();
            List<Idea> out = new ArrayList<>();
            for (int i = 0; i < json().size(); i++) {
                Idea o = Observation.toIdea(json().get(i), i, 0, i == 0, false);
                carry.observe(o);
                out.add(o);
            }
            carries = out;
        }
        return carries;
    }

    /** A copy of observation i's JSON, for tests that edit fields. */
    public static JsonObject copy(int i) {
        return json().get(i).deepCopy();
    }
}
