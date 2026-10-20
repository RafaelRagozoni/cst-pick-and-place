package agent;

import agent.habit.Command;
import agent.motivation.Characterization;
import agent.sim.Observation;
import agent.sim.StepCompletion;
import agent.task.Carry;
import agent.task.TaskStages;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * The Java ports agree with the Python they port, on the recorded expert trajectory: task
 * predicates (goals.py), the carry behind the success test S2 (goals.GoalTracker, also on
 * test_success.py's cases), characterization bins (metrics.characterise) and step completion
 * (actions.StepCompletion). The Python side is run fresh by tools/parity_dump.py, so this compares
 * against the current code, not a fixture that could go stale. Skipped if python3 is missing.
 */
class ParityTest {

    private static JsonObject dump;

    @BeforeAll
    static void runPython() throws IOException, InterruptedException {
        Path script = Traj.simDir().resolve("../agent/tools/parity_dump.py").normalize();
        Process p;
        try {
            p = new ProcessBuilder("python3", script.toString()).redirectErrorStream(false).start();
        } catch (IOException e) {
            assumeTrue(false, "python3 not available: " + e.getMessage());
            return;
        }
        String out = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        String err = new String(p.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
        assertTrue(p.waitFor(60, TimeUnit.SECONDS));
        assertEquals(0, p.exitValue(), "parity_dump.py failed:\n" + err);
        dump = JsonParser.parseString(out).getAsJsonObject();
    }

    @Test
    void taskPredicatesMatchGoalsPy() {
        JsonArray preds = dump.getAsJsonArray("predicates");
        assertEquals(Traj.json().size(), preds.size());
        int checked = 0;
        for (int i = 0; i < preds.size(); i++) {
            JsonArray p = preds.get(i).getAsJsonArray();
            Observation o = Traj.obs(i);
            String at = "observation " + i;
            assertEquals(p.get(0).getAsBoolean(), TaskStages.reached(o), at + " reached");
            assertEquals(p.get(1).getAsBoolean(), TaskStages.grasped(o), at + " grasped");
            assertEquals(p.get(2).getAsBoolean(), TaskStages.transported(o), at + " transported");
            assertEquals(p.get(3).getAsBoolean(), TaskStages.onPad(o), at + " on_pad");
            assertEquals(p.get(4).getAsBoolean(), TaskStages.placed(o), at + " placed");
            checked++;
        }
        assertTrue(checked > 800);
    }

    @Test
    void carryMatchesGoalTracker() {
        JsonArray traj = dump.getAsJsonArray("carry");
        assertEquals(Traj.json().size(), traj.size());
        for (int i = 0; i < traj.size(); i++) {
            sameCarry(traj.get(i).getAsJsonArray(), Traj.obs(i), "observation " + i);
        }
        assertTrue(TaskStages.settled(Traj.obs(traj.size() - 1)), "the expert succeeds under S2");

        JsonArray cases = dump.getAsJsonArray("cases");
        assertTrue(cases.size() >= 12);
        for (JsonElement ce : cases) {
            JsonObject c = ce.getAsJsonObject();
            JsonArray obs = c.getAsJsonArray("obs");
            JsonArray want = c.getAsJsonArray("carry");
            Carry carry = new Carry();
            for (int k = 0; k < obs.size(); k++) {
                Idea o = Observation.toIdea(obs.get(k).getAsJsonObject(), k, 0, k == 0, false);
                carry.observe(o);
                sameCarry(want.get(k).getAsJsonArray(), new Observation(o),
                        c.get("name").getAsString() + ", observation " + k);
            }
        }
    }

    private static void sameCarry(JsonArray want, Observation o, String at) {
        assertEquals(want.get(0).getAsBoolean(), o.carried(), at + " carried");
        assertEquals(want.get(1).getAsBoolean(), o.placing(), at + " placing");
        assertEquals(want.get(2).getAsInt(), o.still(), at + " still");
        assertEquals(want.get(3).getAsBoolean(), TaskStages.settled(o), at + " success");
    }

    @Test
    void binsMatchMetricsCharacterise() {
        JsonArray bins = dump.getAsJsonArray("bins");
        for (int i = 0; i < bins.size(); i++) {
            JsonArray b = bins.get(i).getAsJsonArray();
            int[] want = new int[b.size()];
            for (int k = 0; k < want.length; k++) {
                want[k] = b.get(k).getAsInt();
            }
            assertArrayEquals(want, Characterization.bins(Traj.obs(i)), "observation " + i);
        }
    }

    @Test
    void stepCompletionMatchesActionsPy() {
        JsonArray scenarios = dump.getAsJsonArray("completion");
        assertTrue(scenarios.size() >= 10);
        for (JsonElement se : scenarios) {
            JsonObject s = se.getAsJsonObject();
            String name = s.get("name").getAsString();
            int start = s.get("start").getAsInt();
            List<Command> records = new ArrayList<>();
            for (JsonElement r : s.getAsJsonArray("records")) {
                records.add(Command.fromJson(r.getAsJsonObject()));
            }
            StepCompletion sc = new StepCompletion(records, Traj.obs(start));
            JsonArray ticks = s.getAsJsonArray("ticks");
            for (int k = 0; k < ticks.size(); k++) {
                JsonObject tick = ticks.get(k).getAsJsonObject();
                Observation o = Traj.obs(start + k);
                String at = name + " tick " + k;
                if (k > 0) {
                    JsonElement want = tick.get("result");
                    assertEquals(want.isJsonNull() ? null : want.getAsString(), sc.update(o), at);
                }
                JsonArray wantCmds = tick.getAsJsonArray("commands");
                List<Command> got = sc.commands(o);
                assertEquals(wantCmds.size(), got.size(), at + " command count");
                for (int c = 0; c < got.size(); c++) {
                    Command w = Command.fromJson(wantCmds.get(c).getAsJsonObject());
                    assertEquals(w.action(), got.get(c).action(), at);
                    assertEquals(w.joint(), got.get(c).joint(), at);
                    assertEquals(w.angle(), got.get(c).angle(), 1e-12, at + " remaining angle");
                }
            }
        }
    }
}
