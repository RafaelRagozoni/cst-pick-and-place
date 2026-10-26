package agent;

import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * A run paused between episodes and resumed from its checkpoint, in a new mind, is the run that
 * never stopped: every command sent and every logged decision (habit, goal, drive levels, novelty,
 * spread) the same, and the same state at the end. State the checkpoint leaves out shows up here
 * as a divergence, in the episode right after the pause.
 */
class CheckpointTest {

    private static final int SEED = 5;
    private static final int STEPS = 120;
    private static final int EPISODES = 6;

    /**
     * {@code offCredit}: the credit options that are off by default, on (progress, baseline).
     * {@code curiosity}: the Curiosity yield, whose history (entry counts; effect model and errors)
     * outlives an episode.
     */
    private static Config cfg(String condition, String selection, boolean offCredit, String curiosity) {
        Config c = Config.forCondition(condition).withCuriosity(curiosity);
        if (offCredit) {
            c.progressWindow = 20;
            c.baselineRate = 0.1;       // per-context state that outlives an episode
        }
        return selection.equals("-") ? c : c.withSelection(selection);
    }

    /** Episodes [from, to) on m; refinement starts after episode {@code refineAfter} (-1: never). */
    private static void run(AgentMind m, int from, int to, int refineAfter) {
        for (int e = from; e < to; e++) {
            m.runEpisode(SEED, e);
            if (e == refineAfter) {
                m.enterRefinement();
            }
        }
    }

    private static Integer first(int refineAfter, int done) {
        return refineAfter >= 0 && refineAfter < done ? refineAfter : null;
    }

    @ParameterizedTest
    @CsvSource({"C0, greedy, -1, false, none", "C0, ucb, -1, false, none",
            "C0, thompson, -1, false, none", "C0, ucb, 1, false, none", "C3, ucb, -1, false, none",
            "C6, -, -1, false, none", "C0, ucb, -1, true, none", "C0, ucb, -1, false, count:50",
            "C0, ucb, 1, false, lp:50"})
    void aResumedRunIsTheRunThatNeverStopped(String condition, String selection, int refineAfter,
                                             boolean offCredit, String curiosity, @TempDir Path dir) {
        int pause = 3;
        FakeEnvironment straightEnv = new FakeEnvironment(STEPS);
        AgentMind straight = new AgentMind(cfg(condition, selection, offCredit, curiosity), straightEnv, SEED);
        run(straight, 0, EPISODES, refineAfter);

        FakeEnvironment beforeEnv = new FakeEnvironment(STEPS);
        AgentMind before = new AgentMind(cfg(condition, selection, offCredit, curiosity), beforeEnv, SEED);
        run(before, 0, pause, refineAfter);
        Path file = dir.resolve("checkpoint.json.gz");
        Checkpoint.write(Checkpoint.of(before, new Checkpoint.Progress(SEED, pause,
                first(refineAfter, pause))), file);

        FakeEnvironment afterEnv = new FakeEnvironment(STEPS);
        AgentMind after = new AgentMind(cfg(condition, selection, offCredit, curiosity), afterEnv, SEED);
        Checkpoint.Progress p = Checkpoint.restore(after, Checkpoint.read(file));
        assertEquals(pause, p.nextEpisode());
        assertEquals(first(refineAfter, pause), p.firstSuccess());
        run(after, p.nextEpisode(), EPISODES, refineAfter);

        int cut = beforeEnv.records.size();
        assertTrue(afterEnv.records.size() > 100, "the resumed run ran");
        for (int i = 0; i < afterEnv.records.size(); i++) {
            assertEquals(straightEnv.annotations.get(cut + i), afterEnv.annotations.get(i),
                    "decision " + i + " after the pause");
            assertEquals(straightEnv.records.get(cut + i), afterEnv.records.get(i),
                    "command " + i + " after the pause");
        }
        assertEquals(straightEnv.records.size(), cut + afterEnv.records.size());
        Checkpoint.Progress end = new Checkpoint.Progress(SEED, EPISODES, first(refineAfter, EPISODES));
        assertEquals(Checkpoint.of(straight, end), Checkpoint.of(after, end), "same state at the end");
    }

    /** --describe: every Config field, the defaults too, and the bridge's handshake as it came. */
    @Test
    void describeHasEveryConfigFieldAndTheHandshake() {
        Config cfg = Config.forCondition("C4").withCuriosity("lp");
        JsonObject info = new FakeEnvironment(5).info();
        JsonObject d = AgentMain.describe(cfg, info);
        JsonObject saved = d.getAsJsonObject("config");
        for (java.lang.reflect.Field f : Config.class.getFields()) {
            assertTrue(saved.has(f.getName()), "agent.json has no " + f.getName());
        }
        assertEquals("lp", saved.get("curiosityYield").getAsString());
        assertEquals(Checkpoint.config(cfg), saved, "the Config a checkpoint saves");
        assertEquals(info, d.getAsJsonObject("bridge"));
    }

    @Test
    void refusesACheckpointFromAnotherConfigOrMidEpisode() {
        AgentMind m = new AgentMind(Config.forCondition("C0").withSelection("ucb"),
                new FakeEnvironment(STEPS), SEED);
        run(m, 0, 1, -1);
        JsonObject c = Checkpoint.of(m, new Checkpoint.Progress(SEED, 1, null));

        AgentMind greedy = new AgentMind(Config.forCondition("C0"), new FakeEnvironment(STEPS), SEED);
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> Checkpoint.restore(greedy, c));
        assertTrue(e.getMessage().contains("selection"), e.getMessage());

        AgentMind used = new AgentMind(Config.forCondition("C0").withSelection("ucb"),
                new FakeEnvironment(STEPS), SEED);
        run(used, 0, 1, -1);
        assertThrows(IllegalStateException.class, () -> Checkpoint.restore(used, c),
                "only into a mind that has not run");

        FakeEnvironment env = new FakeEnvironment(STEPS);
        AgentMind mid = new AgentMind(Config.forCondition("C0"), env, SEED);
        mid.link.reset(SEED, 0);
        mid.cycle();
        assertThrows(IllegalStateException.class,
                () -> Checkpoint.of(mid, new Checkpoint.Progress(SEED, 0, null)));
    }
}
