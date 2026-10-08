"""SIM-03 acceptance: check the observation schema and the salient-event transitions.

Offline, over a recorded trajectory:  python3 test_observations.py traj.jsonl
"""
import json
import sys

FAR_FROM_CUBE = 0.10     # m, end-effector to cube; nothing of the robot can touch the cube from here


def edges(vals):
    """(rising, falling) counts of a boolean sequence."""
    r = f = 0
    for a, b in zip(vals, vals[1:]):
        if b and not a:
            r += 1
        elif a and not b:
            f += 1
    return r, f


def main(path):
    obs = [json.loads(l) for l in open(path)]
    print('checking %d observations' % len(obs))
    o = obs[0]

    required = [
        ('innerSense.joints', lambda x: len(x['innerSense']['joints']) == 6),
        ('joint pos/vel/torque', lambda x: all(k in x['innerSense']['joints'][0]
                                               for k in ('pos', 'vel', 'torque'))),
        ('innerSense.eef', lambda x: len(x['innerSense']['eef']['pos']) == 3),
        ('gripper.width', lambda x: isinstance(x['innerSense']['gripper']['width'], float)),
        ('gripper.isHolding', lambda x: 'isHolding' in x['innerSense']['gripper']),
        ('gripper.inContact', lambda x: 'inContact' in x['innerSense']['gripper']),
        ('jointLimitProximity', lambda x: len(x['innerSense']['jointLimitProximity']) == 6),
        ('selfCollision', lambda x: isinstance(x['innerSense']['selfCollision'], bool)),
        ('manipulability', lambda x: x['innerSense']['manipulability'] is not None),
        ('vision.cube', lambda x: len(x['vision']['cube']['pos']) == 3),
        ('vision.pad', lambda x: len(x['vision']['pad']['pos']) == 3),
        ('derived.eefToCube', lambda x: 'eefToCube' in x['derived']),
        ('derived.cubeDisplacement', lambda x: 'cubeDisplacement' in x['derived']),
    ]
    schema_ok = True
    for name, check in required:
        try:
            good = check(o)
        except Exception:
            good = False
        if not good:
            print('  MISSING/BAD: %s' % name)
            schema_ok = False
    print('  schema complete            : %s' % ('PASS' if schema_ok else 'FAIL'))

    hold = [x['innerSense']['gripper']['isHolding'] for x in obs]
    r, f = edges(hold)
    hold_ok = (r == 1 and f == 1)
    print('  isHolding edges (want 1,1) : %d rising, %d falling -> %s'
          % (r, f, 'PASS' if hold_ok else 'FAIL'))

    # Contact means the robot touches the cube. It must hold whenever the cube is held, and it must
    # NOT follow the gripper: closing on empty air, far from the cube, is not contact. The second
    # check is only meaningful if the trajectory closes on air somewhere, so that is checked too.
    g = [x['innerSense']['gripper'] for x in obs]
    far = [x['derived']['eefToCube'] > FAR_FROM_CUBE for x in obs]
    held_contact = all(gi['inContact'] for gi in g if gi['isHolding'])
    closed_far = sum(1 for gi, f in zip(g, far) if f and not gi['commanded_open'])
    false_contact = sum(1 for gi, f in zip(g, far) if f and gi['inContact'])
    contact_ok = held_contact and closed_far > 0 and false_contact == 0
    print('  inContact while holding    : %s' % ('PASS' if held_contact else 'FAIL'))
    print('  closed on air, far (steps) : %d -> %s' % (closed_far, 'PASS' if closed_far else 'FAIL'))
    print('  inContact far from cube    : %d steps -> %s'
          % (false_contact, 'PASS' if false_contact == 0 else 'FAIL'))

    moved = max(x['derived']['cubeDisplacement'] for x in obs)
    print('  cube displacement observed : %.4f m -> %s' % (moved, 'PASS' if moved > 0 else 'FAIL'))

    jlp = max(max(x['innerSense']['jointLimitProximity']) for x in obs)
    print('  NOTE jointLimitProximity max = %.3f — this UR5 model reports (-360, 720) deg on every'
          % jlp)
    print('       joint, so the field is uninformative until real limits are imposed.')

    ok = schema_ok and hold_ok and contact_ok and moved > 0
    print('\nSIM-03 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else 'traj.jsonl'))
