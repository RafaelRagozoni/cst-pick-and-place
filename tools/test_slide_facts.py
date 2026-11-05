"""Offline checks of slide_facts.py: pt-BR formatting, the fact sheet, the ledger reader and the
collectors on fake logs whose answers are known (vault spec APR-01).

    python3 tools/test_slide_facts.py
"""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slide_facts as sf                            # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def raises(exc, f, *args, **kw):
    try:
        f(*args, **kw)
    except exc:
        return True
    return False


def obs(held, to_pad=0.2):
    return {'innerSense': {'gripper': {'isHolding': held, 'inContact': held},
                           'eef': {'pos': [0.0, 0.0, 0.3]}},
            'vision': {'cube': {'pos': [0.1, 0.1, 0.02]}},
            'derived': {'cubeToPadXY': to_pad, 'cubeDisplacement': 0.0}}


def episode(ep, held_then_dropped, reached):
    """Records of one episode: grasped at the 2nd observation and, if asked, let go far from the
    pad at the 3rd; then the terminal record."""
    held = {True: [False, True, False], False: [False, False, False],
            'keep': [False, True, True]}[held_then_dropped]
    recs = [{'episode': ep, 'obs': obs(h), 'habit_id': 'h%d' % i, 'plan': 'p%d_%d' % (ep, i),
             'goal': 'reach'} for i, h in enumerate(held)]
    recs.append({'episode': ep, 'done': True, 'episode_summary': {'goalsReached': reached,
                                                                  'success': 'release' in reached}})
    return recs


def write_log(path, eps):
    os.makedirs(os.path.dirname(path))
    with gzip.open(path, 'wt') as f:
        for recs in eps:
            for r in recs:
                f.write(json.dumps(r) + '\n')


def main():
    print('formatting')
    check('fmt_percent(0.011, 1)', sf.fmt_percent(0.011, 1) == '1,1%')
    check('fmt_percent(0.0022, 1)', sf.fmt_percent(0.0022, 1) == '0,2%')
    check('fmt_percent(0.93)', sf.fmt_percent(0.93) == '93%')
    check('fmt_number(6900)', sf.fmt_number(6900) == '6.900')
    check('fmt_number(0.27, 2)', sf.fmt_number(0.27, 2) == '0,27')
    check('fmt_number(-0.06, 2) uses U+2212', sf.fmt_number(-0.06, 2) == '−0,06')
    check('fmt_percent_range', sf.fmt_percent_range(0.93, 0.97) == '93–97%')
    check('fmt_number_range', sf.fmt_number_range(8, 32) == '8–32')
    check('a range with equal ends is one number', sf.fmt_percent_range(1.0, 0.9999) == '100%')
    check('fmt_number(1234567.5, 1)', sf.fmt_number(1234567.5, 1) == '1.234.567,5')
    check('negative that rounds to zero has no sign', sf.fmt_number(-0.001, 2) == '0,00')

    print('fact sheet')
    tmp = tempfile.mkdtemp(prefix='slide_facts_')
    try:
        fs = sf.FactSheet()
        fs.add('a', 1.5, '1,5', 'ledger')
        fs.add_manual('b', 'texto', 'a mao')
        check('repeated key -> ValueError', raises(ValueError, fs.add, 'a', 2, '2', 'x'))
        check('repeated key (manual) -> ValueError', raises(ValueError, fs.add_manual, 'a', 't', 'x'))
        check('empty fonte -> ValueError', raises(ValueError, fs.add, 'c', 1, '1', ''))
        check('empty fonte (manual) -> ValueError', raises(ValueError, fs.add_manual, 'c', 't', ''))
        out = os.path.join(tmp, 'sub', 'fatos.json')
        fs.write(out, 'cmd x')
        with open(out) as f:
            data = json.load(f)
        check('write: shape', data == {'gerado_por': 'cmd x', 'fatos': {
            'a': {'valor': 1.5, 'texto': '1,5', 'fonte': 'ledger', 'manual': False},
            'b': {'valor': None, 'texto': 'texto', 'fonte': 'a mao', 'manual': True}}})

        print('ledger and scorecards')
        row = sf.ledger_row('2026-10-21_0842_C4_ucb-0.1_lp_P1')
        check('ledger m2_final', row['m2_final'] == 0.011)
        check('ledger m1_median', row['m1_median'] == 727.0)
        check('ledger text stays text', row['condition'] == 'C4')
        check('unknown batch -> KeyError', raises(KeyError, sf.ledger_row, 'nao-existe'))
        card = {'seeds': [{'first': 3, 'p2': [True, False, True]},
                          {'first': None, 'p2': []},
                          {'first': 0, 'p2': [False, False]}]}
        check('first_success_seeds', sf.first_success_seeds(card) == 2)
        check('phase2_successes', sf.phase2_successes(card) == (2, 5))
        check('run_path', sf.run_path('x') == os.path.join(sf.RUNS, 'x'))

        print('carry_ranges')
        batch = os.path.join(tmp, 'batch')

        def seed(n, blocks):
            eps, ep = [], 0
            for dropped, reached in blocks:
                for d, r in zip(dropped, reached):
                    eps.append(episode(ep, d, r))
                    ep += 1
            write_log(os.path.join(batch, 's%d' % n, 'log.jsonl.gz'), eps)
        T = ['reach', 'grasp', 'transport']
        R = ['reach']
        # blocks of 2 episodes, seeds summed per block like carry_report's **all** rows: block A
        # 3 grasps, 3 dropped, 1 transport in 4 episodes; block B 3 grasps, 1 dropped, none; the
        # last row, only in seed 1, 1 grasp dropped and 1 transport in 1 episode. Per seed, drops
        # would reach 0% and transports 50 in block A, so a per-seed reading fails these checks.
        seed(1, [([True, True], [T, R]), ([True, False], [R, R]), ([True], [T])])
        seed(2, [([True, False], [R, R]), (['keep', 'keep'], [R, R])])
        r = sf.carry_ranges(batch, block=2)
        check('drop_share over the all rows', r['drop_share'] == (1 / 3, 1.0))
        check('transports_per_100 over the all rows, last row included',
              r['transports_per_100'] == (0.0, 100.0))
        check('grasps of every row', r['grasps'] == 7)
        check('drops by grab_open: none in the fake log', r['by_open_share'] == (0.0, 0.0))
        allrows = [l.split(' | ') for l in sf.carry_report.report([batch], 2).splitlines()
                   if l.startswith('| **all**')]
        check('same rows as carry_report prints',
              [int(l[2]) for l in allrows] == [3, 3, 1]
              and [float(l[-1].rstrip(' |')) for l in allrows] == [25.0, 0.0, 100.0])

        print('success_after_first')
        log = os.path.join(tmp, 'late', 'log.jsonl.gz')
        write_log(log, [episode(i, False, ['reach', 'grasp', 'transport', 'release'] if i in (3, 5, 6)
                                else R) for i in range(8)])
        check('success_after_first (3, 2, 4)', sf.success_after_first(log) == (3, 2, 4))
        nolog = os.path.join(tmp, 'never', 'log.jsonl.gz')
        write_log(nolog, [episode(i, False, R) for i in range(3)])
        check('no success -> ValueError', raises(ValueError, sf.success_after_first, nolog))
    finally:
        shutil.rmtree(tmp)
    if FAILS:
        print('\n%d FAILED' % len(FAILS))
        sys.exit(1)
    print('\nall passed')


if __name__ == '__main__':
    main()
