"""Acceptance for the record schema and step completion (actions.py).

Part 1 is offline: StepCompletion and tick_velocity against synthetic observations.
Part 2 needs CoppeliaSim: primitives run to completion on the real arm and land on their angle.

    python3 test_actions.py
"""
import math
import os

from actions import (ANGLE_TOL, GRIP_MIN_TICKS, PRIMITIVE_ANGLE, StepCompletion, grab,
                     joint_positions, limit_velocity, move, primitive_repertoire, record_id,
                     tick_velocity)
from simconfig import JOINT_LIMIT


def _obs(q, width=0.1054):
    return {'innerSense': {'joints': [{'pos': v} for v in q], 'gripper': {'width': width}}}


def part1():
    print('--- part 1: schema and step completion (offline) ---')
    checks = []
    rep = primitive_repertoire()
    ids = [record_id(h[0]) for h in rep]
    checks.append(('14 primitives, all distinct', len(rep) == 14 and len(set(ids)) == 14))
    checks.append(('MOVE angle is relative and signed',
                   move(2, -1)['angle'] == -PRIMITIVE_ANGLE and move(2, -1)['speed'] > 0))
    checks.append(('direction comes from the angle', record_id(move(3, -1)) == 'move_j3_neg'))

    # Velocity never covers more than the remaining angle in one tick.
    dt = 0.05
    v_small = tick_velocity(move(0, 1), dt)
    v_big = tick_velocity(move(0, -1, angle=math.radians(30)), dt)
    checks.append(('1 deg in one tick, not 1.15', abs(v_small * dt - PRIMITIVE_ANGLE) < 1e-12))
    checks.append(('large angle runs at full speed', abs(v_big + 0.4) < 1e-12))

    # Joint limit: a tick lands on the limit, never passes it, never moves a joint uncommanded.
    L = JOINT_LIMIT
    checks.append(('limit: last tick lands on it', abs(limit_velocity(0.4, L - 0.01, dt) - 0.2) < 1e-12))
    checks.append(('limit: no further at the limit', limit_velocity(0.4, L, dt) == 0.0
                   and limit_velocity(-0.4, -L, dt) == 0.0))
    checks.append(('limit: outside, only back in', limit_velocity(0.4, L + 0.1, dt) == 0.0
                   and limit_velocity(-0.4, L + 0.1, dt) == -0.4))
    checks.append(('limit: nothing moves uncommanded', limit_velocity(0.0, L + 0.1, dt) == 0.0))

    # A MOVE ends on arrival, and the commands carry the angle still to go.
    q = [0.0] * 6
    s = StepCompletion([move(1, 1, angle=math.radians(3))], _obs(q))
    first = s.commands(_obs(q))[0]['angle']
    q1 = [0, math.radians(1.1), 0, 0, 0, 0]
    r1 = s.update(_obs(q1))
    left = s.commands(_obs(q1))[0]['angle']
    q2 = [0, math.radians(2.95), 0, 0, 0, 0]
    r2 = s.update(_obs(q2))
    checks.append(('commands carry the remaining angle',
                   abs(first - math.radians(3)) < 1e-12 and abs(left - math.radians(1.9)) < 1e-9))
    checks.append(('runs until within tolerance, then done', r1 is None and r2 == 'done'))

    # A blocked joint ends the step instead of hanging it.
    s = StepCompletion([move(4, 1, angle=math.radians(5))], _obs(q))
    res = [s.update(_obs([0, 0, 0, 0, 0.001, 0])) for _ in range(3)]
    checks.append(('blocked joint -> stalled, not stuck', res[:1] == [None] and 'stalled' in res))

    # Parallel step: the joint that arrives drops out, the other keeps going.
    s = StepCompletion([move(0, 1), move(1, 1, angle=math.radians(4))], _obs(q))
    s.update(_obs([PRIMITIVE_ANGLE, math.radians(1.1), 0, 0, 0, 0]))
    left = s.commands(_obs([PRIMITIVE_ANGLE, math.radians(1.1), 0, 0, 0, 0]))
    checks.append(('parallel: arrived joint dropped', [r['joint'] for r in left] == [1]))

    # GRAB: not judged on the first, lagging tick; done once the fingers stop.
    s = StepCompletion([grab(False)], _obs(q, 0.1054))
    widths = [0.1053, 0.1027, 0.1001, 0.0975, 0.0549, 0.0546, 0.0546]
    res = [s.update(_obs(q, w)) for w in widths]
    checks.append(('grab not done during the lag tick', res[0] is None))
    checks.append(('grab done when fingers stop', res[-1] == 'done' and res[3] is None))
    s = StepCompletion([grab(True)], _obs(q, 0.1054))
    res = [s.update(_obs(q, 0.1054)) for _ in range(GRIP_MIN_TICKS)]
    checks.append(('open when already open: done in %d ticks' % GRIP_MIN_TICKS, res[-1] == 'done'))

    ok = True
    for name, good in checks:
        print('  %-42s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= bool(good)
    return ok


def part2():
    print('\n--- part 2: primitives on the real arm (needs CoppeliaSim) ---')
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from actions import Actuator
    from episode import EpisodeReset
    from grasp_rule import GraspRule
    from observations import Observer

    sim = RemoteAPIClient().require('sim')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))
    sim.setStepping(True)
    sim.startSimulation()
    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=False)
    reset = EpisodeReset(sim, rule, obs)
    act = Actuator(sim, reset.arm)
    reset.on_start = act.use_velocity_control
    reset.reset(0, 0)
    reset.reset(0, 0)

    def run(habit):
        o = obs.read()
        q0 = [j['pos'] for j in o['innerSense']['joints']]
        step = StepCompletion(habit, o)
        while True:
            act.apply(step.commands(o), joint_positions(o))
            sim.step()
            o = obs.read()
            res = step.update(o)
            if res is not None:
                q = [j['pos'] for j in o['innerSense']['joints']]
                return res, step.ticks, [b - a for a, b in zip(q0, q)], o

    checks = []
    res, ticks, dq, _ = run([move(0, 1)])
    print('  1 deg primitive: %s in %d tick(s), turned %.3f deg' % (res, ticks, math.degrees(dq[0])))
    checks.append(('1 deg primitive lands on its angle',
                   res == 'done' and abs(dq[0] - PRIMITIVE_ANGLE) <= ANGLE_TOL))
    res, ticks, dq, _ = run([move(1, -1, angle=math.radians(10))])
    print('  10 deg move on the shoulder: %s in %d ticks, turned %.3f deg'
          % (res, ticks, math.degrees(dq[1])))
    checks.append(('10 deg lands without overshoot',
                   res == 'done' and abs(dq[1] + math.radians(10)) <= ANGLE_TOL))
    res, ticks, dq, _ = run([move(3, 1, angle=math.radians(6)), move(5, -1, angle=math.radians(2))])
    print('  parallel 6 deg + 2 deg: %s in %d ticks, turned %.3f / %.3f deg'
          % (res, ticks, math.degrees(dq[3]), math.degrees(dq[5])))
    checks.append(('parallel step lands both joints',
                   res == 'done' and abs(dq[3] - math.radians(6)) <= ANGLE_TOL
                   and abs(dq[5] + math.radians(2)) <= ANGLE_TOL))
    res, ticks, _, o = run([grab(False)])
    print('  close on air: %s in %d ticks, width %.4f m' % (res, ticks, o['innerSense']['gripper']['width']))
    checks.append(('close on air completes', res == 'done' and o['innerSense']['gripper']['width'] < 0.01))
    res, ticks, _, o = run([grab(True)])
    print('  open: %s in %d ticks, width %.4f m' % (res, ticks, o['innerSense']['gripper']['width']))
    checks.append(('open completes', res == 'done' and o['innerSense']['gripper']['width'] > 0.1))
    sim.stopSimulation()

    ok = True
    for name, good in checks:
        print('  %-42s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= bool(good)
    return ok


if __name__ == '__main__':
    a = part1()
    b = part2()
    print('\nACTIONS ACCEPTANCE: %s' % ('PASS' if (a and b) else 'FAIL'))
    raise SystemExit(0 if (a and b) else 1)
