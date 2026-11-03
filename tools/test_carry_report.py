"""Offline checks of carry_report.py on a small hand-made log.

    python3 tools/test_carry_report.py
"""
import gzip
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_report                                 # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-58s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def obs(held, pad_xy=0.3, eef=(0.5, 0.0, 0.8)):
    return {'innerSense': {'gripper': {'isHolding': held, 'inContact': held},
                           'eef': {'pos': list(eef)}},
            'vision': {'cube': {'pos': [0.5, 0.0, 0.75]}},
            'derived': {'cubeDisplacement': 0.0, 'cubeToPadXY': pad_xy}}


def write(path, episodes):
    """`episodes`: [(steps, goalsReached)], a step (habit, plan, held, pad_xy, choice or None)."""
    with gzip.open(path, 'wt') as f:
        for ep, (steps, reached) in enumerate(episodes):
            for i, (habit, plan, held, pad_xy, choice) in enumerate(steps):
                r = {'episode': ep, 'step': i, 'done': False, 'obs': obs(held, pad_xy),
                     'habit_id': habit, 'plan': plan, 'goal': 'transport'}
                if choice is not None:
                    r['choice'] = choice
                f.write(json.dumps(r) + '\n')
            f.write(json.dumps({'episode': ep, 'step': len(steps), 'done': True,
                                'obs': obs(False), 'habit_id': None,
                                'episode_summary': {'goalsReached': reached}}) + '\n')


def main():
    forced = {'executionsHere': 0, 'priorCount': 0.0, 'untried': 3, 'candidates': 14}
    known = {'executionsHere': 2, 'priorCount': 2.0, 'untried': 0, 'candidates': 14}
    episodes = [
        # a log from before the choice field: grasp, a held move, let go mid-way, then the cube
        # on the table. The release shows in the observation of plan 5's record, which is what
        # plan 4's grab_open did: charged to grab_open, not to move_j0_neg.
        ([('move_j0_pos', 1, False, 0.3, None),
          ('grab_close', 2, False, 0.3, None),
          ('grab_close', 2, True, 0.3, None),       # grasped: seen at this record's observation
          ('move_j1_pos', 3, True, 0.3, None),
          ('grab_open', 4, True, 0.3, None),
          ('move_j0_neg', 5, False, 0.3, None)], ['reach', 'grasp']),
        # with the field: the same held move again (not new to its bin), a forced grab_open, and
        # a release near the pad, which is not a drop
        ([('grab_close', 6, True, 0.3, known),
          ('move_j1_pos', 7, True, 0.3, known),
          ('grab_open', 8, True, 0.02, forced),
          ('move_j0_pos', 9, False, 0.02, known)], ['reach', 'grasp', 'transport']),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 's1'))
        log = os.path.join(tmp, 's1', 'log.jsonl.gz')
        write(log, episodes)
        whole, = carry_report.scan(log, 10)
        check('two grasps, one per episode', whole.grasps == 2)
        check('one drop away, by grab_open (the record before it)',
              (whole.dropped_away, whole.dropped_by_open) == (1, 1))
        check('the let-go near the pad is no drop', whole.dropped_away == 1)
        check('held choices: one per plan, judged on its first record',
              whole.held_choices == 5)                # plans 3, 4, 6, 7, 8
        check('grab_open picks while holding', whole.held_open == 2)
        check('new to bin: a habit already started there is not',
              whole.held_new == 3)                    # plans 3, 4 and 6; 7 and 8 repeat 3 and 4
        check('forced read only where logged', (whole.held_logged, whole.held_forced) == (3, 1))
        check('open new and open forced', (whole.open_new, whole.open_logged, whole.open_forced)
              == (1, 1, 1))
        check('transports from the tracker summary', whole.transports == 1)
        first, second = carry_report.scan(log, 1)
        check('blocks: one episode each', (first.first, first.last, second.first) == (0, 0, 1))
        check('a block without the field shows forced as "-"',
              carry_report.row('s1', first).split(' | ')[8] == '-')
        os.makedirs(os.path.join(tmp, 's2'))
        write(os.path.join(tmp, 's2', 'log.jsonl.gz'), episodes)
        text = carry_report.report([tmp], 10)
        allrow = [l for l in text.splitlines() if l.startswith('| **all**')]
        check('every seed together: counts add up', len(allrow) == 1
              and allrow[0].split(' | ')[2] == '4' and allrow[0].split(' | ')[1] == '0-1')
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
