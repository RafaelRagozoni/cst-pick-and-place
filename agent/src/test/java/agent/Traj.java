package agent;

import agent.sim.Observation;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** The recorded expert trajectory (coppelia_environment/traj.jsonl), as JSON and as SensoryMO. */
public final class Traj {

    private static List<JsonObject> cache;

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
        return new Observation(Observation.toIdea(json().get(i), i, 0, i == 0, false));
    }

    /** A copy of observation i's JSON, for tests that edit fields. */
    public static JsonObject copy(int i) {
        return json().get(i).deepCopy();
    }
}
