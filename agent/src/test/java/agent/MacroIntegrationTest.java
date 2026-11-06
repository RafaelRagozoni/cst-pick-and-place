package agent;

import agent.habit.HabitIdeas;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The whole mind with macros on (vault spec MAC-01), on the fake environment starting over the
 * cube, where a short run meets Task goals: macros are built, chosen in their own context and run,
 * and the repertoire grows. In this run the first Task goal is met in episode 7, so it takes 30
 * episodes for a context with a macro to come back.
 */
class MacroIntegrationTest {

    @ParameterizedTest
    @ValueSource(strings = {"copy", "sum"})
    void macrosAreBuiltChosenAndRun(String rule) {
        Config config = Config.forCondition("C0").withSelection("ucb:0.1").withCuriosity("lp")
                .withMacroRule(rule);
        FakeEnvironment environment = FakeEnvironment.startingOverTheCube(300);
        AgentMind mind = new AgentMind(config, environment, 7);
        AgentMind.EpisodeResult lastEpisode = null;
        for (int episode = 0; episode < 30; episode++) {
            lastEpisode = mind.runEpisode(7, episode);
        }
        Map<String, Integer> eventsByKind = new TreeMap<>();
        int stepsInMacros = 0;
        for (JsonObject annotation : environment.annotations) {
            if (annotation.has("macro")) {
                for (JsonElement event : annotation.getAsJsonArray("macro")) {
                    eventsByKind.merge(event.getAsJsonObject().get("kind").getAsString(), 1,
                            Integer::sum);
                }
            }
            if (annotation.get("habit_id").getAsString().startsWith("macro_")) {
                stepsInMacros++;
            }
        }
        int activeMacros = 0;
        int retiredMacros = 0;
        for (Idea habit : mind.learner.habits().values()) {
            if (HabitIdeas.isMacro(habit)) {
                if (HabitIdeas.isRetired(habit)) {
                    retiredMacros++;
                } else {
                    activeMacros++;
                }
            }
        }
        System.out.printf("%s: events %s, %d macros active and %d retired, %d of %d steps inside a "
                + "macro, repertoire %s%n", rule, eventsByKind, activeMacros, retiredMacros,
                stepsInMacros, environment.annotations.size(), mind.telemetry.repertoire());
        assertTrue(eventsByKind.getOrDefault("created", 0) >= 1, "a macro was built: " + eventsByKind);
        assertTrue(stepsInMacros > 0, "a macro was chosen and ran");
        JsonObject repertoire = mind.telemetry.repertoire();
        assertEquals(14 + activeMacros, repertoire.get("size").getAsInt(), "the retired ones apart");
        assertTrue(activeMacros > 0, "the repertoire grew");
        assertTrue(retiredMacros > 0, "a macro was retired, so the pool size below is put to the test");
        assertEquals(14 + activeMacros, lastEpisode.poolSize(),
                "the episode's pool size (the agent's stdout) counts like the log: retired apart");
    }

    /**
     * The macro events of an episode's terminal cycle reach its terminal record (code review of PR
     * #4, finding 3). A Task stage met on the last observation -- the release of every success --
     * builds its macro on the cycle that does not act, which used to send nothing, and the next
     * episode's first cycle cleared the events. After runEpisode the learner still holds that
     * cycle's events, so they are what the episode's end must carry. With an 80-step limit and seed
     * 1, a stage is met on the last observation of episode 20 (no success in the fake this early).
     */
    @ParameterizedTest
    @ValueSource(strings = {"copy", "sum"})
    void theTerminalCyclesMacroEventsReachTheEpisodesEnd(String rule) {
        Config config = Config.forCondition("C0").withSelection("ucb:0.1").withCuriosity("lp")
                .withMacroRule(rule);
        FakeEnvironment environment = FakeEnvironment.startingOverTheCube(80);
        AgentMind mind = new AgentMind(config, environment, 1);
        List<String> producedOnTerminalCycles = new ArrayList<>();
        for (int episode = 0; episode < 21; episode++) {
            mind.runEpisode(1, episode);
            mind.learner.macroEvents().forEach(event -> producedOnTerminalCycles.add(event.kind()));
        }
        List<String> loggedOnEnds = new ArrayList<>();
        for (JsonObject endAnnotation : environment.endAnnotations) {
            if (endAnnotation != null) {
                for (JsonElement event : endAnnotation.getAsJsonArray("macro")) {
                    loggedOnEnds.add(event.getAsJsonObject().get("kind").getAsString());
                }
            }
        }
        assertEquals(21, environment.endAnnotations.size(), "every episode ended once");
        assertFalse(producedOnTerminalCycles.isEmpty(),
                "the run has a terminal cycle with macro events, so the case is exercised");
        assertEquals(producedOnTerminalCycles, loggedOnEnds);
    }
}
