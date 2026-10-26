"""SIM-07 acceptance: the runner produces a log that reduces to every reported metric.

Part 1 is exact and offline: a synthetic log with known successes must reduce to known numbers.
Part 2 runs real episodes (condition C6, the random baseline) and checks the log's shape.

    python3 test_runner.py
"""
import json
import math
import os
import sys
import tempfile

import metrics


def synthetic_log():
    """Three episodes: fail(100), succeed(40, 3.0 rad), succeed(60, 5.0 rad)."""
    recs = []
    for ep, (steps, ok, energy) in enumerate([(100, False, 9.0), (40, True, 3.0), (60, True, 5.0)]):
        for k in range(steps):
            recs.append({'episode': ep, 'step': k, 'done': False,
                         'obs': _obs(k * 0.01, ok and k > steps - 5),
                         'action': [{'action': 'MOVE', 'joint': 0, 'speed': 0.4}]})
        recs.append({'episode': ep, 'step': steps, 'done': True,
                     'obs': _obs(steps * 0.01, ok),
                     'episode_summary': {'steps': steps, 'success': ok, 'jointEnergy': energy,
                                         'goalsReached': ['reach', 'grasp'] if ok else ['reach'],
                                         'cube_start': (0.22, -0.22, 0.0)}})
    return recs


def _obs(x, holding):
    return {'innerSense': {'eef': {'pos': [x, 0.0, 1.0]},
                           'gripper': {'isHolding': holding, 'inContact': holding}},
            'vision': {'cube': {'pos': [0.22, -0.22, 0.745]}},
            'derived': {'cubeDisplacement': 0.0}}


def part1():
    print('--- part 1: metric reduction (offline, exact) ---')
    m = metrics.reduce_log(synthetic_log())
    checks = [
        ('episodes == 3', m['episodes'] == 3),
        ('success rate == 2/3', abs(m['successRate'] - 2 / 3) < 1e-9),
        ('first success at episode 1', m['episodesToFirstSuccess'] == 1),
        ('steps/success == 50', abs(m['stepsPerSuccess'] - 50.0) < 1e-9),
        ('energy/success == 4.0', abs(m['jointEnergyPerSuccess'] - 4.0) < 1e-9),
        ('repertoire reported unavailable', m['repertoire'] is None),
        ('coverage counted', m['coverageBins'] > 1),
        ('goal steps tallied', m['goalStepsReached'].get('reach') == 3),
        ('selection reported not logged', m['selection'] == []),
        ('selection read from the log',
         metrics.reduce_log([dict(r, selection='ucb') for r in synthetic_log()])['selection']
         == ['ucb']),
    ]
    ok = True
    for name, good in checks:
        print('  %-34s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= good
    return ok


def part2():
    print('\n--- part 2: real run, condition C6 (needs CoppeliaSim) ---')
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from grasp_rule import GraspRule
    from observations import Observer
    from runner import run, RandomPolicy

    sim = RemoteAPIClient().require('sim')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))
    sim.setStepping(True)
    sim.startSimulation()
    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=False)

    out = os.path.join(tempfile.gettempdir(), 'sim07_run.jsonl.gz')
    run(sim, rule, obs, RandomPolicy(), seed=3, episodes=3, out_path=out,
        condition='C6', mode='fixed', step_limit=60)
    sim.stopSimulation()

    recs = metrics.load(out)
    eps = sorted(set(r['episode'] for r in recs))
    terminals = [r for r in recs if r['done']]
    acting = [r for r in recs if not r['done']]
    checks = [
        ('3 episodes logged', eps == [0, 1, 2]),
        ('one terminal record each', len(terminals) == 3),
        ('terminal has no action', all(r['action'] is None for r in terminals)),
        ('acting records carry an action', all(r['action'] for r in acting)),
        ('acting records carry a habit id', all(r['habit_id'] for r in acting)),
        ('every record has an observation', all(r.get('obs') for r in recs)),
        ('goal_step present', all('goal_step' in r for r in recs)),
        ('rewards field reserved', all('rewards' in r for r in recs)),
        ('episode_summary on terminals', all('episode_summary' in r for r in terminals)),
    ]
    ok = True
    for name, good in checks:
        print('  %-34s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= good

    print('\n  reduced from the real log:')
    metrics.report(metrics.reduce_log(recs))
    return ok


if __name__ == '__main__':
    a = part1()
    b = part2()
    print('\nSIM-07 ACCEPTANCE: %s' % ('PASS' if (a and b) else 'FAIL'))
    raise SystemExit(0 if (a and b) else 1)
