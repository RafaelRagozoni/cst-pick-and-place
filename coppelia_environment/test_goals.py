"""SIM-06 acceptance: replay a recorded trajectory through the goal tracker.

Runs **offline** -- no CoppeliaSim needed. That is the point of keeping every predicate in goals.py
a pure function of one observation dict: the goal layer can be tested, and re-tested after any
threshold change, without standing up a simulator.

    python3 record_trajectory.py     # needs CoppeliaSim; writes traj.jsonl
    python3 test_goals.py traj.jsonl # pure replay
"""
import json
import sys

from goals import GoalTracker, STEPS, placed


def main(path):
    obs = [json.loads(l) for l in open(path)]
    print('replaying %d observations from %s' % (len(obs), path))

    tracker = GoalTracker()
    fired = []
    for o in obs:
        step = tracker.update(o)
        if step:
            fired.append((step, round(o['t'], 2)))

    for name, t in fired:
        print('  step %-10s fired at t=%.2f s' % (name, t))

    order_ok = [f[0] for f in fired] == list(STEPS)
    once_ok = len(fired) == len(set(f[0] for f in fired))
    success_ok = tracker.success
    never_early = not placed(obs[0])

    print('  all four steps, in order : %s' % ('PASS' if order_ok else
          'FAIL (got %s)' % [f[0] for f in fired]))
    print('  each fired exactly once  : %s' % ('PASS' if once_ok else 'FAIL'))
    print('  success at end of episode: %s' % ('PASS' if success_ok else 'FAIL'))
    print('  not already successful   : %s' % ('PASS' if never_early else 'FAIL'))

    ok = order_ok and once_ok and success_ok and never_early
    print('\nSIM-06 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else 'traj.jsonl'))
