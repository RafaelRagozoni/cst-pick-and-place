"""BAS-01: the strict success test (goals.SUCCESS_TEST), on synthetic observation sequences.

Offline, no CoppeliaSim. Each case is a sequence the agent produced or could produce; the cases that
are not successes are the ones an earlier rule counted (code_notes 20-22, and the log analysis of
2026-10-20): pushed in, dropped beside the pad and nudged in, bounced off, still falling (S1); held
but never lifted onto the pad (S2, and two of the six logged first successes).

    python3 test_success.py
"""
from goals import GoalTracker, SETTLE_STEPS, SUCCESS_TEST

PAD_REST = 0.031     # m, cube centre above the table when it rests on the pad (traj.jsonl's end)
TABLE_REST = 0.025   # m, the same on the bare table


def obs(held, xy, h, speed=0.0, eef=0.01):
    return {'t': 0.0,
            'innerSense': {'gripper': {'isHolding': held}},
            'vision': {'cube': {'vel': [speed, 0.0, 0.0]}},
            'derived': {'eefToCube': eef, 'cubeToPadXY': xy, 'cubeHeightAboveTable': h}}


def carry(to_xy=0.01, at_h=0.07):
    """Reach, grasp, lift and carry the cube over the pad: reach, grasp and transport fire."""
    seq = [obs(False, 0.46, TABLE_REST, eef=0.30), obs(False, 0.46, TABLE_REST),
           obs(True, 0.46, TABLE_REST), obs(True, 0.46, at_h)]
    seq += [obs(True, x, at_h) for x in (0.30, 0.15, 0.05)]
    seq += [obs(True, to_xy, at_h)]
    return seq


def still(n, xy=0.01, h=PAD_REST):
    return [obs(False, xy, h) for _ in range(n)]


def first_success(seq):
    """Index of the observation on which the tracker reached `done`, or None."""
    tracker = GoalTracker()
    for i, o in enumerate(seq):
        tracker.update(o)
        if tracker.success:
            return i
    return None


def cases():
    lowered = carry() + [obs(True, 0.01, PAD_REST)]
    yield ('lowered onto the pad, then let go, then still', lowered + still(SETTLE_STEPS),
           len(lowered) + SETTLE_STEPS - 1)

    dropped = carry() + [obs(False, 0.01, h, speed=0.5) for h in (0.06, 0.045, 0.035)]
    yield ('let go 4 cm above the pad, falls onto it, then still', dropped + still(SETTLE_STEPS),
           len(dropped) + SETTLE_STEPS - 1)

    yield ('one observation short of settled', carry() + still(SETTLE_STEPS - 1), None)

    jolt = carry() + still(5) + [obs(False, 0.01, PAD_REST, speed=0.05)]
    yield ('a jolt restarts the count', jolt + still(SETTLE_STEPS), len(jolt) + SETTLE_STEPS - 1)

    pushed = [obs(False, 0.46, TABLE_REST, eef=0.30), obs(False, 0.46, TABLE_REST)]
    pushed += [obs(False, x, TABLE_REST, speed=0.05) for x in (0.30, 0.15, 0.04)]
    yield ('pushed onto the pad, never held', pushed + still(3 * SETTLE_STEPS, xy=0.04), None)

    beside = carry() + [obs(True, 0.08, 0.07), obs(False, 0.08, 0.07, speed=0.5)]
    beside += [obs(False, x, TABLE_REST, speed=0.05) for x in (0.08, 0.06)]
    yield ('carried, let go 8 cm off, nudged in', beside + still(3 * SETTLE_STEPS, xy=0.04), None)

    edge = carry() + [obs(True, 0.055, 0.07), obs(False, 0.055, 0.06, speed=0.5)]
    yield ('let go just outside the 5 cm', edge + still(3 * SETTLE_STEPS, xy=0.045), None)

    bounce = carry() + [obs(False, 0.03, 0.05, speed=0.5), obs(False, 0.06, 0.035, speed=0.3)]
    yield ('let go over the pad, bounces off, rolls back', bounce + still(3 * SETTLE_STEPS, xy=0.04),
           None)

    falling = carry(at_h=0.097) + [obs(False, 0.042, 0.09, speed=0.6), obs(False, 0.07, 0.05, speed=0.6)]
    yield ('still falling past the pad (counted mid-air before)', falling + still(3 * SETTLE_STEPS, xy=0.07),
           None)

    regrasp = carry() + still(5) + [obs(True, 0.01, PAD_REST)]
    yield ('grasped again before settled: not yet', regrasp + still(5), None)
    yield ('grasped again in place, let go: a new carry, unlifted', regrasp + still(SETTLE_STEPS),
           None)
    relifted = regrasp + [obs(True, 0.01, 0.06)]
    yield ('grasped again, lifted, let go over the pad', relifted + still(SETTLE_STEPS),
           len(relifted) + SETTLE_STEPS - 1)

    dragged = [obs(False, 0.46, TABLE_REST, eef=0.30), obs(False, 0.46, TABLE_REST)]
    dragged += [obs(True, x, TABLE_REST) for x in (0.46, 0.30, 0.15, 0.01)]
    yield ('held but dragged at table height, never lifted', dragged + still(3 * SETTLE_STEPS), None)

    onto = dragged[:-1] + [obs(True, 0.03, PAD_REST), obs(True, 0.01, PAD_REST)]
    yield ('held, dragged up onto the pad, let go', onto + still(3 * SETTLE_STEPS), None)

    pushed_in = pushed + [obs(False, 0.01, PAD_REST, eef=0.01)]
    pushed_in += [obs(True, 0.01, PAD_REST) for _ in range(3)]
    yield ('pushed in, grasped where it lies, let go', pushed_in + still(3 * SETTLE_STEPS), None)

    low = carry(at_h=0.045)
    yield ('carried over the pad 2 cm up, under the lift', low + still(3 * SETTLE_STEPS), None)


def main():
    ok = SUCCESS_TEST == 'S3'
    print('  success test is S3         : %s' % ('PASS' if ok else 'FAIL (%s)' % SUCCESS_TEST))
    for name, seq, want in cases():
        got = first_success(seq)
        good = got == want
        ok &= good
        print('  %-52s: %s' % (name, 'PASS' if good else 'FAIL (success at %s, want %s)' % (got, want)))

    tracker = GoalTracker()
    for o in carry() + still(SETTLE_STEPS):
        tracker.update(o)
    tracker.reset()
    cleared = not tracker.success and tracker.current == 'reach'
    for o in still(SETTLE_STEPS):
        tracker.update(o)
    cleared &= not tracker.success
    ok &= cleared
    print('  %-52s: %s' % ('reset clears the carry and the placing', 'PASS' if cleared else 'FAIL'))

    print('\nBAS-01 %s: %s' % (SUCCESS_TEST, 'PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
