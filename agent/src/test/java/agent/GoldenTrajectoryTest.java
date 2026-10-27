package agent;

import agent.credit.CreditSnapshot;
import agent.habit.HabitIdeas;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonObject;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

/**
 * Golden master of the whole mind on the fake environment: a fixed seed must reproduce, step for
 * step, the trajectory recorded in src/test/resources/golden. It pins today's behaviour before a
 * change that is meant to leave it alone at some setting (CRE-01: with the new weights at 0 the
 * agent is the one of 470aef4). A difference fails at the first line that differs, so the step
 * where the behaviour moved is in the message.
 *
 * <p>The fake starts each episode with the gripper over the cube: from its usual start a short run
 * never grasps, and the pin would guard only the reach stage.
 *
 * <p>Each line is one step: the habit sent and the goal, drives, novelty, yield and spread the
 * annotation logged with it, then the fake's reply (holding, success). The file ends with every
 * habit's credit. Doubles are printed by Double.toString, which round-trips: a pinned number is the
 * exact double.
 *
 * <p>To rewrite the files on purpose (a change that is MEANT to alter the trajectory):
 * {@code ./gradlew test --offline -PgoldenUpdate=true --tests agent.GoldenTrajectoryTest}, then
 * read the diff before committing it. A missing file fails rather than being written, so a typo in
 * a name cannot pass by recording itself.
 */
class GoldenTrajectoryTest {

    private static final boolean UPDATE = Boolean.parseBoolean(System.getProperty("golden.update"));

    /**
     * A pin that never grasps guards nothing CRE-01 changes: the Task's stage jumps and the credit
     * of habits run while holding. These floors make a run that stops reaching the cube fail here
     * instead of passing as a pin of the reach stage alone.
     */
    private static final int MIN_GRASPS = 3;
    private static final int MIN_HOLDING_STEPS = 50;

    @ParameterizedTest(name = "{0}")
    @CsvSource({
            // the P1 baseline (bench/P1.json): pool frozen, UCB 0.1, lp
            "c4-ucb0.1-lp, C4, ucb:0.1, lp, 7, 8, 300",
            // macros, Thompson and the count yield: the paths P1 does not take
            "c0-thompson-count, C0, thompson, count:200, 3, 6, 300",
    })
    void theMindReproducesItsRecordedTrajectory(String name, String condition, String selection,
                                                String curiosity, int seed, int episodes,
                                                int stepLimit) throws IOException {
        Config config = Config.forCondition(condition).withSelection(selection).withCuriosity(curiosity);
        config.taskStageWeight = 0.0;           // CRE-01 part 1 off: the agent the files recorded
        FakeEnvironment environment = FakeEnvironment.startingOverTheCube(stepLimit);
        AgentMind mind = new AgentMind(config, environment, seed);
        for (int episode = 0; episode < episodes; episode++) {
            mind.runEpisode(seed, episode);
        }
        List<String> trajectory = trajectoryLines(environment, mind);
        assertTheRunReachesTheCube(environment);

        Path goldenFile = Path.of(System.getProperty("golden.dir"), name + ".txt");
        if (UPDATE) {
            Files.createDirectories(goldenFile.getParent());
            Files.write(goldenFile, trajectory, StandardCharsets.UTF_8);
            return;
        }
        if (!Files.exists(goldenFile)) {
            fail("no golden file " + goldenFile + ": record it with -PgoldenUpdate=true");
        }
        List<String> recorded = Files.readAllLines(goldenFile, StandardCharsets.UTF_8);
        int lines = Math.min(recorded.size(), trajectory.size());
        for (int i = 0; i < lines; i++) {
            if (!recorded.get(i).equals(trajectory.get(i))) {
                fail(name + " moved at line " + (i + 1) + "\n  recorded: " + recorded.get(i)
                        + "\n  now:      " + trajectory.get(i));
            }
        }
        if (recorded.size() != trajectory.size()) {
            fail(name + ": " + recorded.size() + " lines recorded, " + trajectory.size() + " now");
        }
    }

    private static List<String> trajectoryLines(FakeEnvironment environment, AgentMind mind) {
        List<String> lines = new ArrayList<>();
        lines.add("# step: habit goal goalSource task curiosity safety effort novelty yield spread"
                + " | holding success");
        for (int step = 0; step < environment.annotations.size(); step++) {
            JsonObject annotation = environment.annotations.get(step);
            JsonObject reply = environment.stepReplies.get(step);
            StringBuilder line = new StringBuilder();
            line.append(step).append(": ").append(annotation.get("habit_id").getAsString());
            line.append(' ').append(text(annotation, "goal"));
            line.append(' ').append(text(annotation, "goalSource"));
            JsonObject drives = annotation.getAsJsonObject("drives");
            for (String drive : new String[]{"task", "curiosity", "safety", "effort"}) {
                line.append(' ').append(drives == null ? "-" : drives.get(drive).getAsDouble());
            }
            for (String field : new String[]{"novelty", "yield", "spread"}) {
                line.append(' ').append(annotation.has(field)
                        ? annotation.get(field).getAsDouble() : "-");
            }
            line.append(" | ").append(holding(reply)).append(' ')
                    .append(reply.get("success").getAsBoolean());
            lines.add(line.toString());
        }
        lines.add("# credit: habit executions samples contexts total(MEAN) per drive");
        Map<String, Idea> habitsByName = new TreeMap<>(mind.learner.habits());
        for (Map.Entry<String, Idea> habit : habitsByName.entrySet()) {
            CreditSnapshot credit = HabitIdeas.credit(habit.getValue());
            StringBuilder line = new StringBuilder(habit.getKey());
            line.append(' ').append(credit.executions()).append(' ').append(credit.samples())
                    .append(' ').append(credit.contexts());
            for (double value : credit.total(CreditSnapshot.Read.MEAN)) {
                line.append(' ').append(value);
            }
            lines.add(line.toString());
        }
        return lines;
    }

    private static void assertTheRunReachesTheCube(FakeEnvironment environment) {
        int grasps = 0;
        int holdingSteps = 0;
        boolean wasHolding = false;
        for (JsonObject reply : environment.stepReplies) {
            boolean holding = holding(reply);
            if (holding && !wasHolding) {
                grasps++;
            }
            if (holding) {
                holdingSteps++;
            }
            wasHolding = holding;
        }
        assertTrue(grasps >= MIN_GRASPS, "the pinned run grasps " + grasps + " times");
        assertTrue(holdingSteps >= MIN_HOLDING_STEPS, "the pinned run holds " + holdingSteps + " steps");
    }

    private static boolean holding(JsonObject reply) {
        return reply.getAsJsonObject("obs").getAsJsonObject("innerSense")
                .getAsJsonObject("gripper").get("isHolding").getAsBoolean();
    }

    private static String text(JsonObject annotation, String field) {
        return annotation.has(field) && !annotation.get(field).isJsonNull()
                ? annotation.get(field).getAsString() : "-";
    }
}
