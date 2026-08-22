"""SIM-07: the episode runner and the transition log.

This is the loop WP4 runs and the data WP2's learning consumes. It owns no policy: a policy is any
callable `policy(obs, rng) -> [record, ...]`. The CST agent will be one; `RandomPolicy` is another,
and is not a placeholder -- uniform-random selection over the primitives *is* condition C6, the
random baseline every motivated condition must beat.

Log format: one JSON object per line.

    {episode, step, t, seed, condition, obs, action, habit_id, goal_step, goal_fired,
     success, done, rewards}

The observation logged in a record is the one the agent saw **before** acting, and the action is
what it did about it. The next record's `obs` is therefore the resulting state, so `(s, a, s')`
triples read off unambiguously -- except across an episode boundary, which is why every episode ends
with a terminal record carrying `action: null` and `done: true`. Merging observation and outcome
into one record is what makes those triples ambiguous, so it is deliberately not done.

`rewards` is left empty here. Intrinsic rewards are computed by CST codelets (WP2), and the field
exists so the schema does not change when they arrive.

One logger, three consumers: the ablation metrics (metrics.py), credit-assignment debugging, and
the behaviour-cloning dataset of nn_slots_spec.md 4.3.

Logs are gzipped when the path ends in `.gz`, which is the default and strongly recommended: a full
observation is ~1.5 kB of the ~1.8 kB record, and the projected ablation grid (1e6 steps x 35 runs)
comes to ~63 GB uncompressed. The JSON is highly repetitive, so gzip costs little CPU and takes a
large bite out of that.
"""
import gzip
import json
import math
import os
import time

import numpy as np

from actions import Actuator, primitive_repertoire, record_id
from episode import EpisodeReset
from goals import GoalTracker, succeeded

DEFAULT_STEP_LIMIT = 500     # DEC-04: provisional, to be replaced by a pilot-derived value


class RandomPolicy:
    """Uniform-random over the primitive repertoire: condition C6."""

    name = 'random'

    def __init__(self):
        self.repertoire = primitive_repertoire()

    def __call__(self, obs, rng):
        return self.repertoire[int(rng.integers(len(self.repertoire)))]


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
        tracker = GoalTracker()
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), int(index), 0xA]))

        obs = self.obs.read()
        energy = 0.0
        prev_q = [j['pos'] for j in obs['innerSense']['joints']]
        success = False

        for k in range(self.step_limit):
            records = policy(obs, rng)
            self.actuator.apply(records)
            self.sim.step()
            nxt = self.obs.read()

            q = [j['pos'] for j in nxt['innerSense']['joints']]
            energy += sum(abs(a - b) for a, b in zip(q, prev_q))   # E_joint, cap4 metric 3
            prev_q = q

            fired = tracker.update(nxt)
            success = succeeded(nxt)
            done = success or k == self.step_limit - 1

            sink.write(json.dumps({
                'episode': index, 'step': k, 't': obs['t'], 'seed': seed,
                'condition': condition, 'obs': obs, 'action': records,
                'habit_id': [record_id(r) for r in records],
                'goal_step': tracker.current, 'goal_fired': fired,
                'success': success, 'done': False, 'rewards': {},
            }) + '\n')
            obs = nxt
            if done:
                break

        # Terminal record: the final state, no action. Keeps (s, a, s') unambiguous at the boundary.
        sink.write(json.dumps({
            'episode': index, 'step': k + 1, 't': obs['t'], 'seed': seed,
            'condition': condition, 'obs': obs, 'action': None, 'habit_id': None,
            'goal_step': tracker.current, 'goal_fired': None,
            'success': success, 'done': True, 'rewards': {},
            'episode_summary': {
                'steps': k + 1, 'success': success, 'jointEnergy': energy,
                'goalsReached': [t[0] for t in tracker.transitions],
                'cube_start': info['cube'],
            },
        }) + '\n')
        return {'success': success, 'steps': k + 1, 'energy': energy}


def open_log(path, mode='wt'):
    """Transparently gzip when the path ends in .gz. Shared by the runner and metrics.load()."""
    return gzip.open(path, mode) if str(path).endswith('.gz') else open(path, mode.replace('t', ''))


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
