package agent;

import agent.credit.CreditSnapshot;
import agent.habit.HabitIdeas;
import agent.memory.ExecutionBuffer;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The whole mind, closed-loop, against the kinematic stand-in for the bridge. */
class AgentMindTest {

    private static List<String> habitsRun(FakeEnvironment env) {
        List<String> out = new ArrayList<>();
        for (JsonObject a : env.annotations) {
            out.add(a.get("habit_id").getAsString());
        }
        return out;
    }

    private static FakeEnvironment run(Config cfg, int seed, int episodes, int stepLimit) {
        FakeEnvironment env = new FakeEnvironment(stepLimit);
        AgentMind m = new AgentMind(cfg, env, seed);
        for (int e = 0; e < episodes; e++) {
            m.runEpisode(seed, e);
        }
        return env;
    }

    @Test
    void oneSimulationStepPerCycleAndNoneOnTheTerminalObservation() {
        FakeEnvironment env = new FakeEnvironment(60);
        AgentMind m = new AgentMind(Config.forCondition("C0"), env, 3);
        for (int e = 0; e < 3; e++) {
            AgentMind.EpisodeResult r = m.runEpisode(3, e);
            assertEquals(60, r.steps());
        }
        assertEquals(3, env.resets);
        assertEquals(180, env.records.size());
        // reset + 60 steps per episode, each reply one cycle: 61 cycles numbered 0..182
        assertEquals(182, m.link.cycle());
    }

    @Test
    void aSeedReproducesTheRunExactly() {
        List<String> a = habitsRun(run(Config.forCondition("C0"), 11, 3, 80));
        List<String> b = habitsRun(run(Config.forCondition("C0"), 11, 3, 80));
        List<String> c = habitsRun(run(Config.forCondition("C0"), 12, 3, 80));
        assertEquals(a, b);
        assertNotEquals(a, c);
    }

    @Test
    void creditReachesThePoolAndStepsDoNotOverlap() {
        FakeEnvironment env = new FakeEnvironment(100);
        AgentMind m = new AgentMind(Config.forCondition("C0"), env, 5);
        for (int e = 0; e < 4; e++) {
            m.runEpisode(5, e);
        }
        int credited = 0;
        for (Idea h : m.learner.habits().values()) {
            if (HabitIdeas.credit(h).executions() > 0) {
                credited++;
            }
        }
        assertTrue(credited >= 3, "several habits ran and were credited, got " + credited);

        long lastEnd = -1;
        int steps = 0;
        for (ExecutionBuffer.Entry e : ((ExecutionBuffer) m.executionMO.getI()).since(0)) {
            if (e instanceof ExecutionBuffer.Step s) {
                assertTrue(s.startCycle() >= lastEnd, "step " + s + " overlaps the previous one");
                assertTrue(s.endCycle() > s.startCycle());
                lastEnd = s.endCycle();
                steps++;
            }
        }
        assertTrue(steps > 100);
        // Primitives complete in one tick here, so the arm is never left idle between habits.
        long idle = env.annotations.stream()
                .filter(a -> a.get("habit_id").getAsString().equals("idle")).count();
        assertEquals(0, idle);
    }

    @Test
    void theRandomBaselineLearnsNothing() {
        FakeEnvironment env = new FakeEnvironment(100);
        AgentMind m = new AgentMind(Config.forCondition("C6"), env, 5);
        for (int e = 0; e < 2; e++) {
            m.runEpisode(5, e);
        }
        for (Idea h : m.learner.habits().values()) {
            assertEquals(CreditSnapshot.EMPTY, HabitIdeas.credit(h));
        }
        assertTrue(habitsRun(env).stream().distinct().count() > 5);
    }

    @ParameterizedTest
    @ValueSource(strings = {"C0", "C1", "C2", "C3", "C4", "C5", "C6"})
    void everyConditionRunsClosedLoop(String condition) {
        FakeEnvironment env = run(Config.forCondition(condition), 2, 2, 50);
        assertEquals(100, env.records.size());
        JsonObject last = env.annotations.get(env.annotations.size() - 1);
        assertEquals(14, last.getAsJsonObject("repertoire").get("size").getAsInt());
        assertTrue(last.has("drives") && last.has("goal"));
    }

    /**
     * UCB and Thompson in the closed loop. The spread check is the silent failure: at spread 0 both
     * quietly rank by score alone and lock in like GREEDY, with nothing erroring.
     */
    @ParameterizedTest
    @ValueSource(strings = {"ucb", "thompson"})
    void exploringSelectorsTryEveryHabitAndReproducePerSeed(String name) {
        java.util.function.Supplier<Config> cfg = () -> Config.forCondition("C0").withSelection(name);
        FakeEnvironment env = new FakeEnvironment(150);
        AgentMind m = new AgentMind(cfg.get(), env, 4);
        for (int e = 0; e < 3; e++) {
            m.runEpisode(4, e);
        }
        assertEquals(14, new java.util.HashSet<>(habitsRun(env)).size(), "every habit tried");
        List<CreditSnapshot> credit = new ArrayList<>();
        for (Idea h : m.learner.habits().values()) {
            credit.add(HabitIdeas.credit(h));
        }
        assertTrue(CreditSnapshot.reference(credit, new double[]{1, 1, 1, 1}) > 0, "spread estimated");
        JsonObject last = env.annotations.get(env.annotations.size() - 1);
        assertEquals(name, last.get("selection").getAsString(), "the log says which selector ran");
        assertTrue(last.get("spread").getAsDouble() > 0, "and the spread it used");
        assertEquals(habitsRun(env), habitsRun(run(cfg.get(), 4, 3, 150)));
    }

    @Test
    void refinementRaisesEffortsGain() {
        FakeEnvironment env = new FakeEnvironment(30);
        AgentMind m = new AgentMind(Config.forCondition("C0"), env, 1);
        m.runEpisode(1, 0);
        JsonObject before = env.annotations.get(env.annotations.size() - 1);
        assertEquals(0.0, before.getAsJsonObject("drives").get("effort").getAsDouble());
        m.enterRefinement();
        m.runEpisode(1, 1);
        JsonObject after = env.annotations.get(env.annotations.size() - 1);
        assertEquals("refinement", after.get("phase").getAsString());
        assertTrue(after.getAsJsonObject("drives").get("effort").getAsDouble() > 0.0);
    }
}
