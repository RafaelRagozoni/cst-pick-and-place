"""SIM-08 acceptance: the same seed must reproduce the same run.

The paired comparisons in cap4's protocol rest on this. If it fails, the statistics are testing
noise, so this is checked over the whole stack at once -- reset, policy, actuator, physics -- not on
the physics alone.

    python3 test_determinism.py
"""
import math
import os
import tempfile

import metrics
import simconfig


def joint_trace(records):
    """Joint positions for every acting record, in order."""
    return [[j['pos'] for j in r['obs']['innerSense']['joints']]
            for r in records if not r.get('done')]


def cube_trace(records):
    return [r['obs']['vision']['cube']['pos'] for r in records if not r.get('done')]


def max_dev(a, b):
    if len(a) != len(b):
        return float('inf')
    return max((max(abs(x - y) for x, y in zip(ra, rb)) for ra, rb in zip(a, b)), default=0.0)


def main():
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from grasp_rule import GraspRule
    from observations import Observer
    from runner import run, RandomPolicy

    sim = RemoteAPIClient().require('sim')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))

    sig = simconfig.pin_physics(sim)
    print('physics pinned: %s' % sig)

    sim.setStepping(True)
    sim.startSimulation()
    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=False)

    def do(seed, tag):
        path = os.path.join(tempfile.gettempdir(), 'det_%s.jsonl.gz' % tag)
        run(sim, rule, obs, RandomPolicy(), seed=seed, episodes=2, out_path=path,
            condition='C6', mode='annulus', step_limit=250, verbose=False)
        return metrics.load(path)

    a = do(5, 'a')
    b = do(5, 'b')
    c = do(6, 'c')
    sim.stopSimulation()

    jd = max_dev(joint_trace(a), joint_trace(b))
    cd = max_dev(cube_trace(a), cube_trace(b))
    steps = len(joint_trace(a))
    print('  steps compared            : %d' % steps)
    print('  max joint deviation       : %.3e rad' % jd)
    print('  max cube deviation        : %.3e m' % cd)

    other = max_dev(joint_trace(a), joint_trace(c))
    print('  different seed deviates by: %.3e rad' % other)

    checks = [
        ('at least 500 steps compared', steps >= 500),
        ('joint traces reproduce', jd <= 1e-9),
        ('cube traces reproduce', cd <= 1e-9),
        ('different seed actually differs', other > 1e-6),
        ('summaries identical', [r.get('episode_summary') for r in a if r.get('done')]
         == [r.get('episode_summary') for r in b if r.get('done')]),
    ]
    ok = True
    for name, good in checks:
        print('  %-34s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= good
    print('\nSIM-08 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
