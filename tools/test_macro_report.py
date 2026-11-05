"""Offline checks of macro_report.py on a small hand-made log.

    python3 tools/test_macro_report.py
"""
import gzip
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macro_report                                 # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-58s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def obs(collision=False):
    return {'innerSense': {'envCollision': collision, 'selfCollision': False}}


def write(path, episodes):
    """`episodes`: [[(habit, plan, goal_fired, collision, macro events or None)]]."""
    with gzip.open(path, 'wt') as f:
        for ep, steps in enumerate(episodes):
            for i, (habit, plan, fired, collision, events) in enumerate(steps):
                r = {'episode': ep, 'step': i, 'done': False, 'obs': obs(collision),
                     'habit_id': habit, 'plan': plan, 'goal_fired': fired,
                     'repertoire': {'size': 16, 'primitive': 14, 'macro': 2, 'retired': 1}}
                if events:
                    r['macro'] = events
                f.write(json.dumps(r) + '\n')
            f.write(json.dumps({'episode': ep, 'step': len(steps), 'done': True, 'obs': obs(),
                                'habit_id': None, 'episode_summary': {}}) + '\n')


def text_columns(text):
    header, separator = text.splitlines()[:2]
    return header.count('|') == separator.count('|')


def main():
    created_reach = [{'kind': 'created', 'macro': 'macro_reach_1', 'retired': None}]
    created_grasp = [{'kind': 'created', 'macro': 'macro_grasp_1', 'retired': None},
                     {'kind': 'repeated', 'macro': 'macro_reach_1', 'retired': None}]
    replaced = [{'kind': 'replaced', 'macro': 'macro_reach_2', 'retired': 'macro_reach_1'}]
    episodes = [
        [('move_j0_pos', 1, None, False, created_reach),
         ('macro_reach_1', 2, None, False, None),
         ('macro_reach_1', 2, None, False, None),
         ('move_j1_pos', 3, 'reach', False, created_grasp),   # the reach seen right after the run
         ('macro_grasp_1', 4, None, False, None),
         ('grab_close', 5, 'grasp', True, None)],              # a collision after the macro's step
        [('macro_reach_1', 6, None, False, replaced),
         ('macro_reach_1', 6, None, False, None)],              # the episode ends, reach not met
    ]
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 's1'))
        log = os.path.join(tmp, 's1', 'log.jsonl.gz')
        write(log, episodes)
        s = macro_report.scan('s1', log)
        check('events by kind', (s.events['created'], s.events['replaced'], s.events['repeated'])
              == (2, 1, 1))
        check('three macro runs, one per plan', s.runs == 3)
        check('goal met during or right after the run: two of three', s.runs_met == 2)
        check('ticks per run', sorted(s.run_ticks) == [1, 2, 2])
        check('goal met by stage: reach one of two, grasp one of one',
              {g: tuple(v) for g, v in s.runs_by_goal.items()} == {'reach': (2, 1), 'grasp': (1, 1)})
        check('never ran: the active macro never chosen',
              s.built - s.retired - s.chosen == {'macro_reach_2'})
        check('macro goal from the id', macro_report.macro_goal('macro_transport_12') == 'transport')
        rows = macro_report.last_rows(s, 100)
        check('reach step of the episode that had one', [r['reach'] for r in rows] == [3, None])
        check('one collision onset, after a macro step',
              (rows[0]['onsets'], rows[0]['onsets_in_macro']) == (1, 1))
        line = macro_report.row('b', s, 100)
        cells = [c.strip() for c in line.strip('|').split('|')]
        check('row: runs, goal met, by stage, ticks, reach, grasps, collisions, in macro',
              cells[6:] == ['3', '67', 'grasp 100 · reach 50', '2', '3', '50.0', '0.0', '50.0', '100'])
        check('row: last episodes only', macro_report.row('b', s, 1).split('|')[11].strip() == '-')
        check('header and separator have the same columns',
              text_columns(macro_report.report([tmp], 100)))
        check('a window picks episodes by index',
              [r['reach'] for r in macro_report.last_rows(s, 100, (0, 0))] == [3])
        s.events = dict.fromkeys(macro_report.KINDS, 0)          # a batch without macros (the C4)
        check('no macros: the in-macro share is empty, not 0',
              macro_report.row('b', s, 100).strip().strip('|').split('|')[-1].strip() == '-')
        text = macro_report.report([tmp], 100)
        check('report has a header and the seed row', text.count('| s1 |') == 1)
    print('\nmacro report: %s' % ('PASS' if not FAILS else 'FAIL: %s' % FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
