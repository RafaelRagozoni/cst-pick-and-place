"""SIM-07: the episode runner and the transition log.

This is the loop WP4 runs and the data WP2's learning consumes. It owns no policy: a policy is any
callable `policy(obs, rng) -> [record, ...]`. The CST agent will be one; `RandomPolicy` is another,
and is not a placeholder -- uniform-random selection over the primitives *is* condition C6, the
random baseline every motivated condition must beat.

The log it writes is defined in translog.py, which bridge.py writes through as well.
"""
import os
import time

import numpy as np

from actions import Actuator, StepCompletion, joint_positions, primitive_repertoire
from episode import EpisodeReset
from goals import GoalTracker, succeeded
from translog import EpisodeLog, open_log

DEFAULT_STEP_LIMIT = 500     # DEC-04: provisional, to be replaced by a pilot-derived value


class RandomPolicy:
    """Uniform-random over the primitive repertoire: condition C6.

    Like the agent, it runs the chosen primitive until its step completes (actions.StepCompletion)
    and only then picks again. Picking afresh every tick would give C6 a finer action grain than
    the agent has, and the C4-vs-C6 contrast is meant to isolate motivated *selection* only.
    """

    name = 'random'

    def __init__(self):
        self.repertoire = primitive_repertoire()
        self.current = None

    def reset(self):
        self.current = None

    def __call__(self, obs, rng):
        if self.current is None or self.current.update(obs) is not None:
            habit = self.repertoire[int(rng.integers(len(self.repertoire)))]
            self.current = StepCompletion(habit, obs)
        return self.current.commands(obs)


class Runner:
    def __init__(self, sim, grasp_rule, observer, mode='fixed', step_limit=DEFAULT_STEP_LIMIT):
        self.sim = sim
        self.obs = observer
        self.reset = EpisodeReset(sim, grasp_rule, observer, mode=mode)
        self.actuator = Actuator(sim, self.reset.arm)
        self.reset.on_start = self.actuator.use_velocity_control
        self.step_limit = step_limit

    def run_episode(self, policy, seed, index, sink, condition):
        info = self.reset.reset(seed, index)   # establishes velocity control before settling
        if hasattr(policy, 'reset'):
            policy.reset()
        tracker = GoalTracker()
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), int(index), 0xA]))

        obs = self.obs.read()
        log = EpisodeLog(sink, seed, index, condition, obs, info['cube'])
        success = False

        for k in range(self.step_limit):
            records = policy(obs, rng)
            self.actuator.apply(records, joint_positions(obs))
            self.sim.step()
            obs = self.obs.read()
            fired = tracker.update(obs)
            success = succeeded(obs)
            log.step(records, obs, tracker.current, fired, success)
            if success:
                break

        s = log.close(tracker.current, success, [t[0] for t in tracker.transitions])
        return {'success': success, 'steps': s['steps'], 'energy': s['jointEnergy']}


def run(sim, grasp_rule, observer, policy, seed, episodes, out_path,
        condition='C6', mode='fixed', step_limit=DEFAULT_STEP_LIMIT, verbose=True, warmup=True):
    """Run `episodes` episodes and write the log to `out_path` (gzipped if it ends in .gz).

    `warmup` performs one discarded reset before episode 0. It costs 0.24 s and it is what makes a
    run bit-reproducible: measured, a reset is history-independent from the *second* reset onward,
    but the first reset after a fresh scene load lands ~1e-5 rad away from the steady-state one.
    Without the warm-up, episode 0 of a run differs between repetitions while every later episode is
    bit-identical -- which would quietly weaken exactly the pairing the protocol depends on.
    """
    runner = Runner(sim, grasp_rule, observer, mode=mode, step_limit=step_limit)
    if warmup:
        runner.reset.reset(seed, 0)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    t0 = time.time()
    results = []
    with open_log(out_path) as sink:
        for i in range(episodes):
            r = runner.run_episode(policy, seed, i, sink, condition)
            results.append(r)
            if verbose:
                print('  ep %3d  steps %4d  success %-5s  energy %7.2f rad'
                      % (i, r['steps'], r['success'], r['energy']))
    if verbose:
        n = sum(r['steps'] for r in results)
        print('%d episodes, %d steps in %.1f s (%.1f steps/s) -> %s'
              % (episodes, n, time.time() - t0, n / max(time.time() - t0, 1e-9), out_path))
    return results
