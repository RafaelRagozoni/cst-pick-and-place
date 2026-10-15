package agent;

import agent.credit.CreditSnapshot;
import agent.credit.CreditTable;
import agent.habit.Command;
import agent.habit.HabitIdeas;
import agent.memory.ExecutionBuffer;
import agent.motivation.NoveltyArchive;
import agent.selection.Selector;
import agent.selection.Selector.Candidate;
import agent.selection.Selectors;
import br.unicamp.cst.representation.idea.Idea;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The plain data structures under the codelets. */
class UnitsTest {

    // --- habits ------------------------------------------------------------------
    @Test
    void habitIdeaKeepsCommandOrderPastTenRecords() {
        List<Command> cmds = new ArrayList<>();
        for (int i = 0; i < 12; i++) {
            cmds.add(new Command(Command.MOVE, i % 6, 0.01 * (i + 1), 0.4, 20.0, i));
        }
        Idea h = HabitIdeas.create("h1", HabitIdeas.MACRO, List.of("a", "b"), cmds);
        assertEquals(cmds, HabitIdeas.commands(h));
        assertEquals(12, HabitIdeas.steps(h).size());
        assertEquals("macro", HabitIdeas.origin(h));
    }

    @Test
    void stepsGroupParallelRecords() {
        List<Command> cmds = List.of(
                new Command(Command.MOVE, 0, 0.1, 0.4, 20, 1),
                new Command(Command.MOVE, 1, 0.1, 0.4, 20, 0),
                new Command(Command.MOVE, 2, 0.1, 0.4, 20, 1));
        List<List<Command>> steps = HabitIdeas.steps(HabitIdeas.create("p", "parallel", List.of(), cmds));
        assertEquals(2, steps.size());
        assertEquals(1, steps.get(0).size());
        assertEquals(2, steps.get(1).size());
        assertEquals(1, steps.get(0).get(0).joint());
    }

    @Test
    void recordIdsMatchActionsPy() {
        assertEquals("move_j3_neg", new Command(Command.MOVE, 3, -0.01, 0.4, 20, 0).recordId());
        assertEquals("grab_open", new Command(Command.GRAB, -1, 0, 0, -20, 0).recordId());
        assertEquals("grab_close", new Command(Command.GRAB, -1, 0, 0, 20, 0).recordId());
    }

    // --- novelty ------------------------------------------------------------------
    @Test
    void noveltyFallsWithRevisitsAndRecoversWithTime() {
        NoveltyArchive a = new NoveltyArchive(3, 1.0, 100, 0.99);
        assertEquals(NoveltyArchive.EMPTY_SPARSENESS, a.sparseness(new double[]{0, 0}));
        double[] far = {10, 10};
        a.visit(new double[]{0, 0}, "origin", 0);
        double first = a.visit(far, "far", 1);
        double second = a.visit(far, "far", 2);
        assertTrue(second < first, "a revisited bin pays less");
        double later = a.visit(far, "far", 2000);
        assertTrue(later > second, "a bin left alone pays again");
        assertEquals(1.0, a.count("never", 5) + 1.0);
    }

    @Test
    void archiveAdmitsOnlyNovelPointsOnceSeeded() {
        NoveltyArchive a = new NoveltyArchive(2, 1.0, 100, 1.0);
        a.visit(new double[]{0}, "a", 0);
        a.visit(new double[]{0}, "a", 1);      // seeding: the first k always enter
        a.visit(new double[]{0.1}, "b", 2);    // too close
        assertEquals(2, a.size());
        a.visit(new double[]{5}, "c", 3);
        assertEquals(3, a.size());
    }

    @Test
    void fullArchiveReplacesItsOldest() {
        NoveltyArchive a = new NoveltyArchive(1, 0.5, 2, 1.0);
        a.visit(new double[]{0}, "a", 0);
        a.visit(new double[]{10}, "b", 1);
        a.visit(new double[]{20}, "c", 2);     // replaces {0}
        assertEquals(2, a.size());
        assertEquals(10.0, a.sparseness(new double[]{0}), 1e-12);
    }

    // --- credit -------------------------------------------------------------------
    @Test
    void creditReadsPerExecutionOrSummedAndFallsBackToTotal() {
        CreditTable t = new CreditTable();
        t.add("h", "reach|s1", new double[]{1, 0, 0, 0}, 1.0, true);
        t.add("h", "reach|s1", new double[]{3, 0, 0, 0}, 1.0, true);
        t.add("h", "reach|s2", new double[]{0, 2, 0, 0}, 0.5, false);
        CreditSnapshot s = t.snapshot("h");
        assertArrayEquals(new double[]{2, 0, 0, 0}, s.value("reach|s1", CreditSnapshot.Read.MEAN));
        assertArrayEquals(new double[]{4, 0, 0, 0}, s.value("reach|s1", CreditSnapshot.Read.SUM));
        assertArrayEquals(new double[]{2, 0.5, 0, 0}, s.value("grasp|s9", CreditSnapshot.Read.MEAN));
        assertEquals(2, s.executions());
        assertEquals(List.of("h"), new ArrayList<>(t.drainDirty()));
        assertTrue(t.drainDirty().isEmpty());
        assertArrayEquals(new double[4], CreditSnapshot.EMPTY.value("x", CreditSnapshot.Read.MEAN));
    }

    @Test
    void snapshotsDoNotChangeWhenTheTableDoes() {
        CreditTable t = new CreditTable();
        t.add("h", "c", new double[]{1, 0, 0, 0}, 1.0, true);
        CreditSnapshot s = t.snapshot("h");
        t.add("h", "c", new double[]{5, 0, 0, 0}, 1.0, false);
        assertEquals(1.0, s.value("c", CreditSnapshot.Read.SUM)[0]);
    }

    // --- execution buffer ---------------------------------------------------------------
    @Test
    void executionBufferServesWhatIsNewAndRefusesGaps() {
        ExecutionBuffer b = new ExecutionBuffer(3);
        b.addGoalMark("reach", 1, "task", 5, 0);
        long seen = b.nextSeq();
        b.addStep("h", 1, 0, 1, List.of(), 5, 7, "done", "reach", 1, "c", 0);
        assertEquals(1, b.since(seen).size());
        b.addGoalMark("grasp", 2, "task", 8, 0);
        b.addGoalMark("transport", 3, "task", 9, 0);
        assertThrows(IllegalStateException.class, () -> b.since(0));
    }

    // --- selection ---------------------------------------------------------------
    @Test
    void selectorsReturnNullToKeepThePlanInExecution() {
        Candidate a = new Candidate(new Idea("a"), 0.2, 1, 0.0);
        Candidate b = new Candidate(new Idea("b"), 0.5, 1, 0.0);
        List<Candidate> pool = List.of(a, b);
        Random rng = new Random(0);
        assertSame(b, Selectors.GREEDY.select(pool, null, rng));
        assertSame(b, Selectors.GREEDY.select(pool, a, rng), "a strictly better habit preempts");
        assertNull(Selectors.GREEDY.select(pool, b, rng), "the best one running is kept");
        assertNull(Selectors.RANDOM.select(pool, a, rng), "C6 never preempts");
        assertTrue(pool.contains(Selectors.RANDOM.select(pool, null, rng)));
    }

    @Test
    void anExecutionIsOneSampleOnceItsCreditStopsArriving() {
        CreditTable t = new CreditTable();
        t.add("a", "ctx", new double[]{1, 0, 0, 0}, 1.0, true);
        t.add("a", "ctx", new double[]{1, 0, 0, 0}, 0.5, false);   // later credit, same execution
        assertEquals(0, t.snapshot("a").samples(), "still receiving credit: not a sample yet");
        t.add("a", "ctx", new double[]{2, 0, 0, 0}, 1.0, true);    // runs again: 1.5 is closed
        assertEquals(1, t.snapshot("a").samples());
        t.closeExecutions();                                        // episode ends: 2.0 is closed
        CreditSnapshot s = t.snapshot("a");
        assertEquals(2, s.samples());
        // samples 1.5 and 2.0: variance 0.125
        assertEquals(Math.sqrt(0.125), CreditSnapshot.spread(List.of(s), new double[]{1, 0, 0, 0}),
                1e-12);
        assertEquals(0.0, CreditSnapshot.spread(List.of(s), new double[]{0, 1, 1, 1}), 1e-12);
        assertEquals(2, s.count("ctx"));
        assertEquals(2, s.count("elsewhere"), "no record here: the total's count, as value() reads");
    }

    @Test
    void selectionByNameAndC6StaysRandom() {
        Candidate a = new Candidate(new Idea("a"), -0.1, 1, 0.1);
        Candidate b = new Candidate(new Idea("b"), 0.0, 50, 0.1);
        assertSame(a, Selectors.byName("ucb").select(List.of(a, b), null, new Random(0)));
        assertSame(b, Selectors.byName("ucb:0").select(List.of(a, b), null, new Random(0)),
                "c = 0 is greedy");
        assertSame(Selectors.GREEDY, Selectors.byName("greedy"));
        assertSame(Selectors.RANDOM, Selectors.byName("random"));
        assertTrue(Selectors.byName("thompson") != Selectors.byName("thompson"), "one per mind");
        for (String bad : new String[]{"UCB", "ucb:", "ucb:-1", "ucb:x", "softmax"}) {
            assertThrows(IllegalArgumentException.class, () -> Selectors.byName(bad), bad);
        }
        assertEquals("thompson", Config.forCondition("C0").withSelection("thompson").selection);
        assertEquals("random", Config.forCondition("C6").selection);
        assertThrows(IllegalArgumentException.class,
                () -> Config.forCondition("C6").withSelection("ucb"));
        assertThrows(IllegalArgumentException.class,
                () -> Config.forCondition("C0").withSelection("nope"));
    }

    @Test
    void ucbRetriesAHabitWithOneUnluckyResult() {
        Candidate unlucky = new Candidate(new Idea("a"), -0.1, 1, 0.1);
        Candidate tried = new Candidate(new Idea("b"), 0.0, 50, 0.1);
        Candidate untried = new Candidate(new Idea("c"), -5.0, 0, 0.1);
        Random rng = new Random(0);
        assertSame(tried, Selectors.GREEDY.select(List.of(unlucky, tried), null, rng));
        assertSame(unlucky, Selectors.ucb(1.0).select(List.of(unlucky, tried), null, rng));
        assertSame(untried, Selectors.ucb(1.0).select(List.of(unlucky, tried, untried), null, rng),
                "never executed comes first");
    }

    @Test
    void thompsonDrawsOncePerDecision() {
        List<Candidate> pool = new ArrayList<>();
        for (int i = 0; i < 14; i++) {
            pool.add(new Candidate(new Idea("h" + i), 0.0, 1, 1.0));
        }
        Selector ts = Selectors.thompson();
        Random rng = new Random(3);
        Candidate first = ts.select(pool, null, rng);
        for (int i = 0; i < 50; i++) {
            assertNull(ts.select(pool, first, rng), "held draws: no preemption while scores stay");
        }
        List<String> a = new ArrayList<>();
        List<String> b = new ArrayList<>();
        Selector s1 = Selectors.thompson();
        Selector s2 = Selectors.thompson();
        Random r1 = new Random(9);
        Random r2 = new Random(9);
        for (int i = 0; i < 20; i++) {
            a.add(HabitIdeas.id(s1.select(pool, null, r1).habit()));
            b.add(HabitIdeas.id(s2.select(pool, null, r2).habit()));
        }
        assertEquals(a, b, "a seed reproduces the draws");
        assertTrue(new java.util.HashSet<>(a).size() > 3, "equal scores: the choice varies");
    }
}
