"""What the Python environment layer computes on the recorded trajectory, for the Java parity tests.

The agent ports four pieces of coppelia_environment to Java: the step-completion rule
(actions.StepCompletion), the task predicates (goals.py), the carry the success test S2 follows
(goals.GoalTracker, as agent.task.Carry) and the behaviour characterisation (metrics.characterise).
Each pair must agree, or the agent and the experiment disagree about when a step ends, when the task
is done, or what "a visited region" is. The carry is compared on the expert trajectory and on
test_success.py's cases, the sequences S2 exists to tell apart. ParityTest runs this script and
compares, so the comparison is always against the current Python, never a stale fixture.

    python3 agent/tools/parity_dump.py > parity.json
"""
import copy
import json
import math
import os
import sys

SIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'coppelia_environment')
sys.path.insert(0, SIM)

from actions import HOLD, StepCompletion, grab, move  # noqa: E402
from goals import GoalTracker, grasped, on_pad, placed, reached, transported  # noqa: E402
from metrics import characterise  # noqa: E402
import test_success  # noqa: E402


def joint(traj, i, j):
    return traj[i]['innerSense']['joints'][j]['pos']


def moving(traj, j):
    """Indices where joint j turned noticeably since the previous observation."""
    return [i for i in range(1, len(traj))
            if abs(joint(traj, i, j) - joint(traj, i - 1, j)) > math.radians(0.05)]


def scenarios(traj):
    out = []
    for j in (0, 1, 2, 3, 5):
        mv = moving(traj, j)
        s = mv[0]
        # Arrives: ask for 60% of what the joint turns over the next 15 observations.
        out.append(('arrive_j%d' % j, s, [dict(move(j, 1), angle=0.6 * (joint(traj, s + 15, j)
                                                                          - joint(traj, s, j)))]))
        # Stalls: ask for far more than the joint turns before it stops for good.
        e = mv[-1] - 3
        sign = 1.0 if joint(traj, mv[-1], j) >= joint(traj, e, j) else -1.0
        out.append(('stall_j%d' % j, e, [move(j, sign, angle=1.0)]))
    # Two joints in one step (parallel composition).
    s = moving(traj, 0)[0]
    out.append(('parallel_j0_j5', s, [
        dict(move(0, 1), angle=0.5 * (joint(traj, s + 10, 0) - joint(traj, s, 0))),
        dict(move(5, 1), angle=0.5 * (joint(traj, s + 10, 5) - joint(traj, s, 5)))]))
    # The gripper closing on the cube.
    w = [o['innerSense']['gripper']['width'] for o in traj]
    close = next(i for i in range(101, len(w)) if w[i - 1] - w[i] > 0.0005)
    out.append(('grab_close', close - 1, [grab(False)]))
    # Starting earlier, the fingers sit still for two ticks first: only GRIP_MIN_TICKS keeps the
    # step from being judged finished before they move.
    out.append(('grab_close_early', close - 3, [grab(False)]))
    # A joint that never moves stalls on the second tick; HOLD lasts one tick.
    out.append(('still_j4', 10, [move(4, 1, angle=0.5)]))
    out.append(('hold', 10, [dict(move(0, 1), action=HOLD)]))
    return out


def carries(seq):
    """The tracker's carry after each observation: [carried, placing, still, success]."""
    tracker = GoalTracker()
    out = []
    for o in seq:
        tracker.update(o)
        out.append([tracker._carried, tracker._placing, tracker._still, tracker.success])
    return out


def full(template, partial):
    """test_success.py's observation, with the fields it leaves out taken from `template`."""
    o = copy.deepcopy(template)
    o['innerSense']['gripper']['isHolding'] = partial['innerSense']['gripper']['isHolding']
    o['vision']['cube']['vel'] = partial['vision']['cube']['vel']
    o['derived'].update(partial['derived'])
    return o


def main():
    traj = [json.loads(l) for l in open(os.path.join(SIM, 'traj.jsonl'))]
    dump = {'predicates': [], 'bins': [], 'completion': [], 'carry': carries(traj), 'cases': []}
    for o in traj:
        dump['predicates'].append([reached(o), grasped(o), transported(o), on_pad(o), placed(o)])
        e, c, h, k, d = characterise(o)
        dump['bins'].append(list(e) + list(c) + [int(h), int(k), d])
    for name, start, records in scenarios(traj):
        sc = StepCompletion(records, traj[start])
        ticks = [{'result': None, 'commands': sc.commands(traj[start])}]
        for o in traj[start + 1:]:
            r = sc.update(o)
            ticks.append({'result': r, 'commands': sc.commands(o)})
            if r is not None:
                break
        dump['completion'].append({'name': name, 'start': start, 'records': records, 'ticks': ticks})
    for name, seq, _ in test_success.cases():
        obs = [full(traj[0], o) for o in seq]
        dump['cases'].append({'name': name, 'obs': obs, 'carry': carries(obs)})
    json.dump(dump, sys.stdout)


if __name__ == '__main__':
    main()
