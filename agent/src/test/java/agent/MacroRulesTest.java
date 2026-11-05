package agent;

import agent.habit.Command;
import agent.habit.CopyRule;
import agent.habit.MacroRule;
import agent.habit.SumRule;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** The macro rules of vault spec MAC-01, on hand-made steps. */
class MacroRulesTest {

    private static final double DEGREE = Math.toRadians(1.0);

    private static Command move(int joint, double degrees) {
        return new Command(Command.MOVE, joint, degrees * DEGREE, 0.4, 20.0, 0);
    }

    private static Command grab(boolean opening) {
        return new Command(Command.GRAB, -1, 0.0, 0.0, opening ? -20.0 : 20.0, 0);
    }

    @Test
    void copyKeepsEveryStepInOrderAndFlattensAMacroStep() {
        Command first = move(0, 1);
        Command parallelA = move(1, 5).withStep(3);     // a macro's step: its own step index
        Command parallelB = move(2, -2).withStep(3);
        List<Command> macro = new CopyRule().build(List.of(List.of(first),
                List.of(parallelA, parallelB), List.of(grab(false))));
        assertEquals(List.of(first.withStep(0), parallelA.withStep(1), parallelB.withStep(1),
                grab(false).withStep(2)), macro);
    }

    @Test
    void sumCancelsOppositeTurnsAndMakesOneParallelStep() {
        List<Command> macro = new SumRule().build(List.of(List.of(move(0, 1)), List.of(move(1, 1)),
                List.of(move(0, 1)), List.of(move(0, -1)), List.of(move(2, -1)), List.of(move(0, 1))));
        assertEquals(3, macro.size(), macro.toString());
        for (Command command : macro) {
            assertEquals(0, command.step());
        }
        assertEquals(2 * DEGREE, angleOf(macro, 0), 1e-12);
        assertEquals(DEGREE, angleOf(macro, 1), 1e-12);
        assertEquals(-DEGREE, angleOf(macro, 2), 1e-12);
    }

    @Test
    void sumSpeedsMakeEveryJointFinishTogether() {
        List<Command> macro = new SumRule().build(List.of(List.of(move(0, 10)),
                List.of(move(2, 20)), List.of(move(2, 20)), List.of(move(1, -10))));
        assertEquals(0.4, speedOf(macro, 2), 1e-12, "the joint that turns most at full speed");
        assertEquals(0.1, speedOf(macro, 0), 1e-12);
        assertEquals(0.1, speedOf(macro, 1), 1e-12);
        for (Command command : macro) {
            assertEquals(Math.abs(command.angle()) / command.speed(), 40 * DEGREE / 0.4, 1e-12,
                    "joint " + command.joint() + " ends with the others");
        }
    }

    @Test
    void aTinyTurnGetsTheFloorSpeedNotOneTheTrackerWouldCallBlocked() {
        List<Command> macro = new SumRule().build(List.of(List.of(move(0, 40)), List.of(move(1, 0.3))));
        assertEquals(SumRule.MINIMUM_JOINT_SPEED, speedOf(macro, 1), 1e-12);
        assertTrue(0.4 * 0.3 / 40 < SumRule.MINIMUM_JOINT_SPEED, "the proportional speed was below it");
    }

    @Test
    void sumCutsAtTheGripperAndDropsAGripperCommandThatRepeatsTheLastOne() {
        List<Command> macro = new SumRule().build(List.of(List.of(move(0, 1)), List.of(move(0, 1)),
                List.of(grab(false)), List.of(move(1, 2)), List.of(grab(false)), List.of(move(1, 1)),
                List.of(grab(true))));
        assertEquals(List.of(
                move(0, 2).withStep(0),
                grab(false).withStep(1),
                move(1, 3).withStep(2),
                grab(true).withStep(3)), rounded(macro));
    }

    @Test
    void aStretchThatCancelsOutBuildsNothing() {
        assertEquals(List.of(), new SumRule().build(List.of(List.of(move(3, 1)), List.of(move(3, -1)))));
        assertEquals(List.of(), new SumRule().build(List.of()));
    }

    @Test
    void rulesByName() {
        assertTrue(MacroRule.byName("copy") instanceof CopyRule);
        assertTrue(MacroRule.byName("sum") instanceof SumRule);
        assertThrows(IllegalArgumentException.class, () -> MacroRule.byName("none"));
        assertThrows(IllegalArgumentException.class, () -> new Config().withMacroRule("summ"));
        assertEquals("none", new Config().withMacroRule("none").macroRule);
    }

    @Test
    void aConditionWithoutGenerationOrFusionRefusesAMacroRule() {
        for (String condition : new String[]{"C2", "C4", "C6"}) {
            Config config = Config.forCondition(condition).withMacroRule("sum");
            assertThrows(IllegalArgumentException.class, config::validate, condition);
        }
        Config.forCondition("C0").withMacroRule("sum").validate();
        Config.forCondition("C4").withMacroRule("none").validate();
    }

    private static double angleOf(List<Command> macro, int joint) {
        return macro.stream().filter(c -> c.joint() == joint).findFirst().orElseThrow().angle();
    }

    private static double speedOf(List<Command> macro, int joint) {
        return macro.stream().filter(c -> c.joint() == joint).findFirst().orElseThrow().speed();
    }

    /** Angles summed in floating point, rounded to the degree's double, so equals can compare. */
    private static List<Command> rounded(List<Command> macro) {
        return macro.stream().map(c -> c.isMove()
                ? c.withAngle(Math.round(c.angle() / DEGREE) * DEGREE) : c).toList();
    }
}
