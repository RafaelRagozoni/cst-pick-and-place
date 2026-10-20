"""Offline checks of bench.py on fake batches whose answers are known (vault spec BAS-01).

Each fake seed is a run.json and a log of one step and one terminal record per episode: enough for
every metric but coverage, which needs observations and is summarize_run's code anyway. The ledger
written is a temporary one, never bench/ledger.csv.

    python3 tools/test_bench.py
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench                                        # noqa: E402
import protocol                                     # noqa: E402

FAILS = []
FP = {'commit': 'a' * 40, 'dirty': [], 'cst': 'c' * 40, 'scene': 's' * 64,
      'protocol': {'name': 'PT', 'sha256': 'p' * 64}, 'successTest': 'S3',
      'coppeliaSim': {'root': '/x', 'libs': {}}, 'java': 'j', 'python': '3'}


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def fake_seed(batch, seed, first, emax=10, eref=4, p2=None, condition='C4', fp=FP,
              p2_effort=0.5, grow=False, bad_success=False, episodes=None):
    """A seed whose first success is at episode `first` (None: never, so it runs `emax`), then
    `eref` Phase 2 episodes succeeding as `p2` says (default every other one)."""
    d = os.path.join(batch, 's%d' % seed)
    os.makedirs(d)
    total = emax if first is None else first + eref + 1
    n = total if episodes is None else episodes
    with gzip.open(os.path.join(d, 'log.jsonl.gz'), 'wt') as f:
        for ep in range(n):
            phase = 'refinement' if first is not None and ep > first else 'bootstrap'
            if phase == 'refinement':
                k = ep - first - 1
                ok = (p2[k] if p2 is not None else k % 2 == 0)
            else:
                ok = ep == first
            reached = ['reach', 'grasp', 'transport', 'release'] if ok else ['reach']
            if ok and bad_success:
                reached = ['reach', 'grasp', 'release']
            f.write(json.dumps({'episode': ep, 'step': 0, 'done': False, 'phase': phase,
                                'drives': {'effort': p2_effort if phase == 'refinement' else 0.0},
                                'repertoire': {'size': 14 + (ep if grow else 0),
                                               'primitive': 14}}) + '\n')
            f.write(json.dumps({'episode': ep, 'step': 1, 'done': True, 'episode_summary': {
                'steps': 200 + ep, 'success': ok, 'jointEnergy': 1.5, 'goalsReached': reached}})
                    + '\n')
    meta = {'seed': seed, 'condition': condition, 'emax': emax, 'eref': eref, 'commit': fp['commit'][:7],
            'protocol': fp['protocol'] and fp['protocol']['name'], 'fingerprint': fp,
            'start': '2026-10-20T10:00:00', 'end': '2026-10-20T11:00:00', 'agentExit': 0,
            'bridgeExit': 0}
    with open(os.path.join(d, 'run.json'), 'w') as f:
        json.dump(meta, f)


def batch(tmp, name, seeds, **kw):
    b = os.path.join(tmp, name)
    os.makedirs(b)
    for seed, first in seeds:
        fake_seed(b, seed, first, **kw)
    return b


def failed(card):
    return [c['name'] for c in card['checks'] if c['ok'] is False]


START = time.time()


def main():
    tmp = tempfile.mkdtemp()
    ledger = os.path.join(tmp, 'ledger.csv')
    try:
        # Firsts at episodes 1, 3, 5, 7 (2, 4, 6, 8 episodes), two seeds censored at 10: S falls by
        # 1/6 at 2, 4 and 6, so the KM median is 6.
        b = batch(tmp, 'known', [(1, 1), (2, 3), (3, 5), (4, 7), (5, None), (6, None)])
        card = bench.score(b, jobs=2, ledger=ledger)
        m1 = card['m1']
        check('M1: KM median 6 with 2 of 6 censored', m1['median'] == 6 and m1['censored'] == 2)
        check('M1: the CI holds the median', m1['low'] <= 6 and (m1['high'] is None or m1['high'] >= 6))
        check('M1b: reach first at episode 0 everywhere, median 1', card['m1b']['reach']['median'] == 1)
        check('M1b: release as M1', card['m1b']['release']['median'] == 6)
        check('M2: jumpstart and final 0.5 (every other Phase 2 episode succeeds)',
              card['m2']['jumpstart']['mean'] == 0.5 and card['m2']['final']['mean'] == 0.5)
        check('M3: steps per Phase 2 success are each seed\'s, not Phase 1\'s',
              card['m3']['steps']['n'] == 4)
        check('a clean fake batch is valid', card['valid'] and not failed(card))
        check('scorecard.md and scorecard.json are written',
              all(os.path.isfile(os.path.join(b, f)) for f in ('scorecard.md', 'scorecard.json')))
        check('a finished protocol batch gets its ledger line', open(ledger).read().count('known') == 1)
        bench.score(b, jobs=2, ledger=ledger)
        check('  ... replaced, not added, when scored again', open(ledger).read().count('known') == 1)
        check('the track prints it', 'PT' in bench.table(ledger) and '| C4 |' in bench.table(ledger))

        card = bench.score(batch(tmp, 'grows', [(1, 1), (2, None)], grow=True), jobs=2, ledger=ledger)
        check('C4 with a growing repertoire is invalid',
              not card['valid'] and any('14 primitives' in n for n in failed(card)))
        card = bench.score(batch(tmp, 'lazy', [(1, 1), (2, 2)], p2_effort=0.0), jobs=2, ledger=ledger)
        check('Effort 0 in Phase 2 is invalid', not card['valid'] and any('Effort' in n for n in failed(card)))
        card = bench.score(batch(tmp, 'skips', [(1, 2)], bad_success=True), jobs=1, ledger=ledger)
        check('a success without the four stages in order is invalid',
              not card['valid'] and any('four stages' in n for n in failed(card)))
        card = bench.score(batch(tmp, 'short', [(1, None)], episodes=7), jobs=1, ledger=ledger)
        check('a seed that stopped before E_max is invalid',
              not card['valid'] and any('exit 0' in n for n in failed(card)))
        run = os.path.join(tmp, 'short', 's1', 'run.json')
        meta = json.load(open(run))
        meta.pop('end')
        json.dump(meta, open(run, 'w'))
        before = open(ledger).read().count('short')
        bench.score(os.path.join(tmp, 'short'), jobs=1, ledger=ledger)
        check('a protocol batch still running gets no ledger line yet',
              open(ledger).read().count('short') == before)

        # Phase 2 that learns: first 50 fail, last 100 succeed.
        learn = [False] * 50 + [True] * 150
        card = bench.score(batch(tmp, 'learns', [(1, 0), (2, 0), (3, 0)], eref=200, p2=learn),
                           jobs=3, ledger=ledger, theta=0.5)
        check('M2: jumpstart 0, final 1', card['m2']['jumpstart']['mean'] == 0.0
              and card['m2']['final']['mean'] == 1.0)
        check('M2: the running mean of 50 reaches 0.5 after 75 Phase 2 episodes',
              card['m2']['timeToTheta']['0.5']['median'] == 75)
        check('M2b: the 100 before the last hold the 50 failures: still moving',
              card['m2b']['plateau'] is False and card['m2b']['mean'] == 0.5)
        flat = [False] * 50 + [True] * 350
        card = bench.score(batch(tmp, 'flat', [(1, 0), (2, 0)], eref=400, p2=flat), jobs=2,
                           ledger=ledger, theta=0.5)
        check('M2b: the last 200 all succeed: a plateau', card['m2b']['plateau'] is True)

        # compare and its refusals.
        a = batch(tmp, 'A', [(1, 1), (2, 3), (3, None)])
        c0 = batch(tmp, 'C0same', [(1, 0), (2, 1), (3, 2)], condition='C0')
        out = bench.compare(a, c0, ledger=ledger)
        check('C0 against C4 on one fingerprint is compared', '| M1' in out and 'Log-rank' in out)
        other = dict(FP, commit='b' * 40)
        c0b = batch(tmp, 'C0other', [(1, 0)], condition='C0', fp=other)
        check('C0 against C4 on different fingerprints is refused (rule 5)',
              refused(bench.compare, a, c0b, False, ledger, says='commit'))
        p2 = dict(FP, protocol={'name': 'PU', 'sha256': 'q' * 64})
        check('two protocol versions are refused (rule 6)',
              refused(bench.compare, a, batch(tmp, 'Pother', [(1, 0)], fp=p2), False, ledger, says='protocol'))
        later = batch(tmp, 'Alater', [(1, 0)], fp=dict(other, java='k'))
        out = bench.compare(a, later, ledger=ledger)
        check('C4 against C4 on another commit is the track, with git log',
              'git log A..B' in out)
        check('  ... and warns that the environment changed too', 'environment changed' in out)
        smoke = batch(tmp, 'smoke', [(1, 0)], fp=dict(FP, protocol=None))
        check('a smoke is refused without --exploratory',
              refused(bench.compare, a, smoke, False, ledger, says='--exploratory'))
        out = bench.compare(a, smoke, exploratory=True, ledger=ledger)
        check('  ... and with it, says EXPLORATORY at the top and the bottom',
              out.count('EXPLORATORY') == 2)
    finally:
        shutil.rmtree(tmp)
    check('the real bench/ledger.csv was never touched', not os.path.exists(bench.LEDGER) or
          os.path.getmtime(bench.LEDGER) < START)

    check('Holm: 0.01 0.04 0.03 -> 0.03 0.06 0.06',
          [round(x, 3) for x in bench.holm([0.01, 0.04, 0.03])] == [0.03, 0.06, 0.06])
    check('rank-biserial > 0 when A is larger', bench.mw([5, 6, 7], [1, 2, 3])['rb'] == 1.0)
    check('time to threshold: never is None', bench.time_to([False] * 60, 0.5) is None)
    print('\nbench: %s' % ('PASS' if not FAILS else 'FAIL (%d)' % len(FAILS)))
    return 1 if FAILS else 0


def refused(fn, *args, says=''):
    try:
        fn(*args)
    except protocol.Refused as e:
        return says in str(e)
    return False


if __name__ == '__main__':
    raise SystemExit(main())
