package agent;

import agent.codelets.BehaviorGeneratorCodelet;
import agent.codelets.CreditAssignmentCodelet;
import agent.codelets.DriveGeneratorCodelet;
import agent.codelets.GoalGeneratorCodelet;
import agent.codelets.HabitLearnerCodelet;
import agent.codelets.MotorCodelet;
import agent.codelets.PlanTrackerCodelet;
import agent.codelets.SensoryCodelet;
import agent.habit.HabitIdeas;
import agent.memory.ExecutionBuffer;
import agent.memory.SensoryBuffer;
import agent.motivation.Drives;
import agent.sim.Environment;
import agent.sim.SimLink;
import br.unicamp.cst.core.entities.Codelet;
import br.unicamp.cst.core.entities.MemoryContainer;
import br.unicamp.cst.core.entities.MemoryObject;
import br.unicamp.cst.core.entities.Mind;

import java.util.ArrayList;
import java.util.List;

/**
 * The CST mind of cap4 4.2: eight codelets and the memories between them, and the control cycle.
 *
 * <h2>The cycle</h2>
 * One cycle = one observation in, one simulation step out. The codelets run in this order, each
 * through CST's {@code notifyCodelet} (accessMemoryObjects, calculateActivation, proc):
 * <pre>
 *   Sensory -> DriveGenerator -> GoalGenerator -> PlanTracker(track) -> CreditAssignment
 *     -> HabitLearner -> BehaviorGenerator -> PlanTracker(load) -> Motor
 * </pre>
 * The Motor's step returns the next observation, which the Sensory reads on the next cycle.
 *
 * <h2>Why a fixed schedule</h2>
 * The BRG-03 benchmark (README, "Why a fixed schedule") found that free-running timers drop four
 * out of five actions, and that publish-subscribe wiring (a codelet observes its input memory) fixes
 * it. In this CST, publish-subscribe is synchronous: {@code MemoryObject.setI} runs each observer's {@code proc()}
 * inline, on the writer's thread. That is what this schedule keeps -- one thread, codelets run when
 * their inputs are fresh -- while making the order explicit, for three reasons:
 * <ol>
 *   <li>A loop of observers recurses. Motor's step feeds Sensory, so Sensory -> ... -> Motor -> Sensory
 *       would nest one cycle deeper on the stack per step, and an experiment runs ~10^6 steps.</li>
 *   <li>Behavior Generator and PlanTracker read each other's output. The PlanTracker must run on both
 *       sides of the Behavior Generator (see PlanTrackerCodelet), which an observer chain can only
 *       express by having one codelet trigger itself twice through different memories.</li>
 *   <li>Observers of one memory run in registration order, so the order would be correct only by
 *       accident of wiring. Reproducibility per seed is what makes cap4's comparisons paired; it
 *       should not hang on that.</li>
 * </ol>
 * Codelets are registered with the Mind, so CST's inspection tools see them, but the Mind is never
 * started: started codelets would also run on their own timers.
 */
public final class AgentMind {

    public final Config cfg;
    public final Mind mind = new Mind();
    public final SimLink link;
    public final Telemetry telemetry;

    public final MemoryObject sensoryMO;
    public final MemoryObject sensoryBufferMO;
    public final MemoryObject driveMO;
    public final MemoryObject goalMO;
    public final MemoryObject planMO;
    public final MemoryObject trackerMO;
    public final MemoryObject executionMO;
    public final MemoryObject creditMO;
    public final MemoryContainer pool;

    public final SensoryCodelet sensory;
    public final DriveGeneratorCodelet drive;
    public final GoalGeneratorCodelet goal;
    public final PlanTrackerCodelet tracker;
    public final CreditAssignmentCodelet credit;
    public final HabitLearnerCodelet learner;
    public final BehaviorGeneratorCodelet behavior;
    public final MotorCodelet motor;

    private final List<Codelet> schedule;

    public AgentMind(Config cfg, Environment env, long seed) {
        this.cfg = cfg;
        this.link = new SimLink(env);

        sensoryMO = mind.createMemoryObject("SensoryMO");
        sensoryBufferMO = mind.createMemoryObject("SensoryBuffer",
                new SensoryBuffer(cfg.sensoryBufferSize));
        driveMO = mind.createMemoryObject("DriveMO");
        goalMO = mind.createMemoryObject("GoalMO");
        planMO = mind.createMemoryObject("PlanMO");
        trackerMO = mind.createMemoryObject("PlanTrackerMO");
        executionMO = mind.createMemoryObject("ExecutionBuffer",
                new ExecutionBuffer(cfg.executionBufferSize));
        creditMO = mind.createMemoryObject("CreditMO");
        pool = mind.createMemoryContainer("HabitPoolMC");
        telemetry = new Telemetry(trackerMO, goalMO, driveMO, pool);

        sensory = new SensoryCodelet(link);
        sensory.addOutput(sensoryMO);
        sensory.addOutput(sensoryBufferMO);

        drive = new DriveGeneratorCodelet(cfg);
        drive.addInput(sensoryMO);
        drive.addInput(goalMO);
        drive.addOutput(driveMO);

        goal = new GoalGeneratorCodelet(cfg);
        goal.addInput(sensoryMO);
        goal.addInput(driveMO);
        goal.addOutput(goalMO);

        tracker = new PlanTrackerCodelet(cfg);
        tracker.addInput(sensoryMO);
        tracker.addInput(goalMO);
        tracker.addInput(driveMO);
        tracker.addInput(planMO);
        tracker.addOutput(trackerMO);
        tracker.addOutput(executionMO);

        credit = new CreditAssignmentCodelet(cfg);
        credit.addInput(executionMO);
        credit.addInput(sensoryBufferMO);
        credit.addInput(driveMO);
        credit.addInput(sensoryMO);
        credit.addOutput(creditMO);

        learner = new HabitLearnerCodelet(cfg, mind);
        learner.addInput(creditMO);
        learner.addInput(executionMO);
        learner.addOutput(pool);

        behavior = new BehaviorGeneratorCodelet(cfg, seed);
        behavior.addInput(pool);
        behavior.addInput(goalMO);
        behavior.addInput(sensoryMO);
        behavior.addInput(driveMO);
        behavior.addInput(trackerMO);
        behavior.addOutput(planMO);

        motor = new MotorCodelet(link, telemetry);
        motor.addInput(trackerMO);
        motor.addInput(sensoryMO);

        for (Codelet c : List.of(sensory, drive, goal, tracker, credit, learner, behavior, motor)) {
            mind.insertCodelet(c);
        }
        schedule = List.of(sensory, drive, goal, tracker, credit, learner, behavior, tracker, motor);

        learner.seed(HabitIdeas.fromBridgeInfo(link.info()));
    }

    /** One control cycle. */
    public void cycle() {
        for (Codelet c : schedule) {
            c.notifyCodelet();
        }
    }

    /** The Effort gain switch between the two phases of cap4 4.6.2. */
    public void enterRefinement() {
        drive.setGain(Drives.EFFORT, cfg.effortRefineGain);
        telemetry.setPhase("refinement");
    }

    public record EpisodeResult(int episode, int steps, boolean success, List<String> goalsMet,
                                int poolSize) {
    }

    /**
     * Run one episode: reset, cycle until the bridge reports it done, then one last cycle on the
     * terminal observation, which the agent perceives and learns from but does not act on.
     */
    public EpisodeResult runEpisode(int seed, int episode) {
        link.reset(seed, episode);
        long fromSeq = ((ExecutionBuffer) executionMO.getI()).nextSeq();
        boolean terminal;
        do {
            terminal = link.done();
            cycle();
        } while (!terminal);
        List<String> met = new ArrayList<>();
        for (ExecutionBuffer.Entry e : ((ExecutionBuffer) executionMO.getI()).since(fromSeq)) {
            if (e instanceof ExecutionBuffer.GoalMark g) {
                met.add(g.goal());
            }
        }
        return new EpisodeResult(episode, link.latest().get("step").getAsInt(), link.success(), met,
                pool.getAllMemories().size());
    }
}
