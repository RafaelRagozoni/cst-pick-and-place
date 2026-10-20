"""The scorecard of a batch and the quality track of the code (vault spec BAS-01).

    python3 tools/bench.py score runs/<batch> [--theta 0.5]   # scorecard.md and .json in the batch
    python3 tools/bench.py table                              # the track, bench/ledger.csv, as Markdown
    python3 tools/bench.py compare runs/<A> runs/<B>          # Mann-Whitney, rank-biserial, Holm

`score` reads every seed's log once (in parallel) and writes the batch's scorecard: M1 episodes to
the first success, Kaplan-Meier with the seeds that never succeeded censored at E_max, not dropped;
M1b the same for the first time each task stage fired; M2 Phase 2's success rate -- jumpstart (first
50 episodes), time to threshold (the running mean of 50 reaching theta), final (last 100); M2b
whether it has stopped improving; M3 steps and joint energy per Phase 2 success; M4 coverage bins at
the end of each phase; M5 the repertoire's size. Then sanity checks: any failing one makes the batch
invalid. A protocol batch (run_live.py --protocol) also gets its line in bench/ledger.csv, replaced
when scored again; a smoke never does.

`compare` puts two scored batches side by side and tests them, refusing what BAS-01's rules 5 and 6
refuse: two protocol versions, or C0 against C4 on different fingerprints. Two batches of one
condition on different commits are the track; it prints what changed between them (git log) and
warns if the environment changed too. --exploratory compares batches that are not protocol batches
(a pilot, count against lp), and says so at the top and the bottom of what it prints.

Censored seeds tie at the top in Mann-Whitney, which holds because both batches share E_max (one
protocol); the log-rank test is printed beside it as a check. Confidence intervals are 95%, the
median's by percentile bootstrap over seeds with a fixed generator, so a scorecard is reproducible.
"""
import argparse
import csv
import json
import math
import os
import subprocess
import sys
import warnings
from multiprocessing import Pool

import numpy as np
from scipy.stats import CensoredData, bootstrap, ecdf, logrank, mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'coppelia_environment'))
import protocol                                 # noqa: E402
import runlog                                   # noqa: E402
from metrics import characterise                # noqa: E402

STAGES = ['reach', 'grasp', 'transport', 'release']
LEDGER = os.path.join(protocol.ROOT, 'bench', 'ledger.csv')
COLUMNS = ['batch', 'date', 'protocol', 'condition', 'commit', 'cst', 'n', 'm1_median', 'm1_low',
           'm1_high', 'censored', 'm2_jumpstart', 'm2_time_to_theta', 'm2_final', 'm2_plateau',
           'm3_steps', 'm3_energy', 'm4_bins_p1', 'm4_bins_p2', 'valid']
BLOCK = 50                      # M2's blocks and its running mean
FINAL = 100                     # M2's final window, and M2b's two windows
THETAS = (0.25, 0.5, 0.75)      # time to threshold when the protocol fixes none (the pilot)
ENV_KEYS = ('coppeliaSim', 'java', 'python')


# --- one seed ---------------------------------------------------------------------------------
def scan_seed(d):
    """Everything the scorecard needs from one seed's log and run.json, in one pass."""
    with open(os.path.join(d, 'run.json')) as f:
        meta = json.load(f)
    out = {'seed': meta['seed'], 'episodes': 0, 'first': None, 'stageFirst': {},
           'p2': [], 'p2steps': [], 'p2energy': [], 'bins': {}, 'effort': {}, 'repertoire': None,
           'badSuccess': [], 'phaseOrder': True}
    bins, rep = set(), [math.inf, -math.inf]
    for ep, recs, summ in runlog.episodes(os.path.join(d, 'log.jsonl.gz')):
        phase = next((r['phase'] for r in recs if r.get('phase')), None)
        for r in recs:
            o = r.get('obs')
            if o:
                bins.add(characterise(o))
            if r.get('done'):
                continue
            if r.get('drives') and phase:
                out['effort'][phase] = max(out['effort'].get(phase, 0.0), r['drives']['effort'])
            if r.get('repertoire'):
                rep = [min(rep[0], r['repertoire']['size']), max(rep[1], r['repertoire']['size'])]
        summ = summ or {}
        out['episodes'] += 1
        for s in summ.get('goalsReached', []):
            out['stageFirst'].setdefault(s, ep)
        if phase:
            out['bins'][phase] = len(bins)
        success = bool(summ.get('success'))
        if success and summ.get('goalsReached') != STAGES:
            out['badSuccess'].append(ep)
        if phase == 'refinement':
            if out['first'] is None:
                out['phaseOrder'] = False           # refinement before any success
            out['p2'].append(success)
            if success:
                out['p2steps'].append(summ['steps'])
                out['p2energy'].append(summ['jointEnergy'])
        elif success and out['first'] is None:
            out['first'] = ep
        elif out['first'] is not None:
            out['phaseOrder'] = False               # bootstrap after the first success
    out['repertoire'] = rep if rep[0] <= rep[1] else None
    return out


# --- statistics -------------------------------------------------------------------------------
def km(times, caps):
    """Kaplan-Meier median of episodes-to-event, one seed each: its time, or None if the event
    never came and it is censored at its cap. The 95% CI is read off the log-log band; None where
    the curve does not reach 0.5."""
    events = [t for t in times if t is not None]
    right = [c for t, c in zip(times, caps) if t is None]
    out = {'n': len(times), 'events': len(events), 'censored': len(right),
           'median': None, 'low': None, 'high': None}
    if not events:
        return out
    sf = ecdf(CensoredData(uncensored=events, right=right)).sf
    with warnings.catch_warnings():         # undefined where S is 0 or 1: those S themselves
        warnings.simplefilter('ignore', RuntimeWarning)
        band = sf.confidence_interval(0.95, method='log-log')
    low = np.where(np.isnan(band.low.probabilities), sf.probabilities, band.low.probabilities)
    high = np.where(np.isnan(band.high.probabilities), sf.probabilities, band.high.probabilities)

    def first_at_half(q, p):
        hit = [t for t, v in zip(q, p) if v <= 0.5 and t in events]
        return float(min(hit)) if hit else None
    out['median'] = first_at_half(sf.quantiles, sf.probabilities)
    out['low'] = first_at_half(sf.quantiles, low)
    out['high'] = first_at_half(sf.quantiles, high)
    return out


def median_ci(values):
    """Median of per-seed values and its 95% percentile-bootstrap CI (None below 2 seeds)."""
    v = [x for x in values if x is not None]
    out = {'n': len(v), 'median': float(np.median(v)) if v else None, 'low': None, 'high': None}
    if len(v) >= 2:
        if min(v) == max(v):
            out['low'] = out['high'] = float(v[0])
        else:
            ci = bootstrap((v,), np.median, method='percentile',
                           rng=np.random.default_rng(0)).confidence_interval
            out['low'], out['high'] = float(ci.low), float(ci.high)
    return out


def mean_ci(values):
    """Mean of per-seed values and its 95% percentile-bootstrap CI (None below 2 seeds)."""
    v = [x for x in values if x is not None]
    out = {'n': len(v), 'mean': float(np.mean(v)) if v else None, 'low': None, 'high': None}
    if len(v) >= 2:
        if min(v) == max(v):
            out['low'] = out['high'] = float(v[0])
        else:
            ci = bootstrap((v,), np.mean, method='percentile',
                           rng=np.random.default_rng(0)).confidence_interval
            out['low'], out['high'] = float(ci.low), float(ci.high)
    return out


def time_to(rates, theta):
    """Phase 2 episodes until the running mean of BLOCK successes reaches theta; None: never."""
    for k in range(BLOCK - 1, len(rates)):
        if np.mean(rates[k - BLOCK + 1:k + 1]) >= theta:
            return k + 1
    return None


def holm(pvalues):
    """Holm-adjusted p-values, in the order given (SciPy has none; statsmodels is not here)."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adj, run = [None] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adj[i] = run
    return adj


# --- one batch --------------------------------------------------------------------------------
def seed_dirs(batch):
    return sorted((os.path.join(batch, d) for d in os.listdir(batch)
                   if d.startswith('s') and d[1:].isdigit()
                   and os.path.isfile(os.path.join(batch, d, 'run.json'))),
                  key=lambda p: int(os.path.basename(p)[1:]))


def metas(batch):
    out = []
    for d in seed_dirs(batch):
        with open(os.path.join(d, 'run.json')) as f:
            out.append(json.load(f))
    return out


def checks(batch, seeds, ms):
    """The sanity checks: (name, True / False / None for not applicable, detail)."""
    out = []
    bad = []
    for m, s in zip(ms, seeds):
        end = m['emax'] if s['first'] is None else s['first'] + m['eref'] + 1
        if 'end' not in m:
            bad.append('s%d still running or killed' % m['seed'])
        elif m.get('agentExit') != 0 or m.get('bridgeExit') != 0:
            bad.append('s%d exits %s/%s' % (m['seed'], m.get('agentExit'), m.get('bridgeExit')))
        elif s['episodes'] != end:
            bad.append('s%d ran %d episodes, expected %d' % (m['seed'], s['episodes'], end))
    out.append(('every seed ended with exit 0 where the protocol ends it', not bad, '; '.join(bad)))

    bad = ['s%d Phase 1 Effort %.3g' % (m['seed'], s['effort']['bootstrap'])
           for m, s in zip(ms, seeds) if s['effort'].get('bootstrap', 0.0) != 0.0]
    bad += ['s%d Phase 2 Effort stays 0' % m['seed'] for m, s in zip(ms, seeds)
            if s['p2'] and s['effort'].get('refinement', 0.0) <= 0.0]
    out.append(('Effort 0 throughout Phase 1, above 0 in Phase 2', not bad, '; '.join(bad)))

    frozen = [m['condition'] in ('C4', 'C6') for m in ms]
    bad = ['s%d repertoire %s' % (m['seed'], s['repertoire']) for m, s, fz in zip(ms, seeds, frozen)
           if fz and s['repertoire'] != [14, 14]]
    out.append(('C4 and C6 keep the 14 primitives', not bad if any(frozen) else None,
                '; '.join(bad)))

    fps = [m.get('fingerprint') for m in ms]
    fps += [r.get('fingerprint') for m in ms for r in m.get('resumes', [])]
    if any(f is None for f in fps):
        out.append(('one fingerprint for every seed and resume', None,
                    'a seed or resume has none (a batch from before 2026-10-20)'))
    else:
        diff = [x for f in fps[1:] for x in protocol.differences(fps[0], f)]
        out.append(('one fingerprint for every seed and resume', not diff, '; '.join(sorted(set(diff)))))

    bad = ['s%d ep %s' % (m['seed'], s['badSuccess']) for m, s in zip(ms, seeds) if s['badSuccess']]
    bad += ['s%d phases out of order' % m['seed'] for m, s in zip(ms, seeds) if not s['phaseOrder']]
    out.append(('every success has the four stages in order, after its own Phase 1', not bad,
                '; '.join(bad)))
    return out


def theta_of(batch):
    f = os.path.join(batch, 'protocol.json')
    return protocol.read_protocol(f).get('theta') if os.path.isfile(f) else None


def score(batch, theta=None, jobs=None, ledger=LEDGER):
    """The batch's scorecard as a dict; writes scorecard.json and scorecard.md into it, and a
    finished protocol batch's line into `ledger`."""
    batch = os.path.abspath(batch)
    ms = metas(batch)
    if not ms:
        raise SystemExit('no s<seed>/run.json in %s' % batch)
    with Pool(jobs or len(ms)) as pool:
        seeds = pool.map(scan_seed, seed_dirs(batch))
    theta = theta if theta is not None else theta_of(batch)
    thetas = (theta,) if theta is not None else THETAS
    emax = {m['emax'] for m in ms}
    # Censored where the seed stands: at E_max once it has ended, at its last episode while it runs.
    caps = [m['emax'] if 'end' in m else s['episodes'] for m, s in zip(ms, seeds)]
    m1 = km([None if s['first'] is None else s['first'] + 1 for s in seeds], caps)
    m1b = {st: km([None if st not in s['stageFirst'] else s['stageFirst'][st] + 1 for s in seeds],
                  caps) for st in STAGES}
    with_p2 = [s for s in seeds if s['p2']]
    eref = max(m['eref'] for m in ms)
    m2 = {'n': len(with_p2),
          'jumpstart': mean_ci([float(np.mean(s['p2'][:BLOCK])) for s in with_p2]),
          'final': mean_ci([float(np.mean(s['p2'][-FINAL:])) for s in with_p2]),
          'timeToTheta': {str(t): km([time_to(s['p2'], t) for s in with_p2],
                                     [len(s['p2']) for s in with_p2]) for t in thetas},
          'blocks': [[float(np.mean(s['p2'][i:i + BLOCK])) for i in range(0, len(s['p2']), BLOCK)]
                     for s in with_p2]}
    long = [s for s in with_p2 if len(s['p2']) >= 2 * FINAL]
    gain = mean_ci([float(np.mean(s['p2'][-FINAL:]) - np.mean(s['p2'][-2 * FINAL:-FINAL]))
                    for s in long])
    gain['plateau'] = (None if gain['low'] is None else gain['low'] <= 0.0 <= gain['high'])
    m3 = {'steps': median_ci([float(np.median(s['p2steps'])) if s['p2steps'] else None
                              for s in seeds]),
          'energy': median_ci([float(np.median(s['p2energy'])) if s['p2energy'] else None
                               for s in seeds])}
    m4 = {p: median_ci([s['bins'].get(p) for s in seeds]) for p in ('bootstrap', 'refinement')}
    cs = checks(batch, seeds, ms)
    card = {'batch': os.path.basename(batch), 'condition': ms[0]['condition'],
            'protocol': ms[0].get('protocol'), 'commit': ms[0]['commit'],
            'fingerprint': ms[0].get('fingerprint'), 'emax': sorted(emax), 'eref': eref,
            'theta': theta, 'finished': all('end' in m for m in ms), 'caps': caps,
            'seeds': seeds, 'm1': m1, 'm1b': m1b, 'm2': m2, 'm2b': gain, 'm3': m3,
            'm4': m4, 'checks': [{'name': n, 'ok': ok, 'detail': d} for n, ok, d in cs],
            'valid': all(ok is not False for _, ok, _ in cs),
            'logs': {str(s['seed']): log_stamp(d) for s, d in zip(seeds, seed_dirs(batch))}}
    with open(os.path.join(batch, 'scorecard.json'), 'w') as f:
        json.dump(card, f, indent=1)
    with open(os.path.join(batch, 'scorecard.md'), 'w') as f:
        f.write(render(card))
    if card['protocol'] and card['finished']:
        write_ledger(card, ms[0]['start'][:10], ledger)
    return card


def log_stamp(d):
    st = os.stat(os.path.join(d, 'log.jsonl.gz'))
    return [st.st_size, int(st.st_mtime)]


def scored(batch, ledger=LEDGER):
    """The batch's scorecard, scored again if a log changed since (or it never was)."""
    f = os.path.join(batch, 'scorecard.json')
    if os.path.isfile(f):
        with open(f) as fh:
            card = json.load(fh)
        if card['logs'] == {str(m['seed']): log_stamp(d)
                            for m, d in zip(metas(batch), seed_dirs(batch))}:
            return card
    return score(batch, ledger=ledger)


# --- rendering --------------------------------------------------------------------------------
def fmt(x, digits=0):
    if x is None:
        return '–'
    return ('%.' + str(digits) + 'f') % x


def km_cell(k, cap):
    if k['n'] == 0:
        return '–'
    if k['median'] is None:
        return 'not reached (> %d)' % cap
    return '%s [%s, %s]' % (fmt(k['median']), fmt(k['low']),
                            fmt(k['high']) if k['high'] is not None else '> %d' % cap)


def ci_cell(c, digits=2, key='median'):
    if c[key] is None:
        return '–'
    if c['low'] is None:
        return fmt(c[key], digits)
    return '%s [%s, %s]' % (fmt(c[key], digits), fmt(c['low'], digits), fmt(c['high'], digits))


def render(card):
    cap, n = max(card['caps']), len(card['seeds'])
    lines = ['# Scorecard: %s' % card['batch'], '',
             '%s · protocol %s · commit %s · %d seeds · E_max %s · E_ref %d · %s' % (
                 card['condition'], card['protocol'] or 'none (not a protocol batch: never in the '
                 'track)', card['commit'], n, '/'.join(map(str, card['emax'])), card['eref'],
                 '**valid**' if card['valid'] else '**INVALID**' if card['finished']
                 else '**in progress** (censored at the episodes run so far)'), '',
             '## Per seed', '',
             '| seed | episodes | 1st success | ' + ' | '.join(STAGES)
             + ' | Phase 2 eps | jumpstart | final | bins P1 / P2 |',
             '|---' * (7 + len(STAGES)) + '|']
    for s in card['seeds']:
        p2 = s['p2']
        lines.append('| %d | %d | %s | %s | %d | %s | %s | %s / %s |' % (
            s['seed'], s['episodes'], fmt(s['first']) if s['first'] is not None else 'none yet'
            if not card['finished'] else 'censored',
            ' | '.join(fmt(s['stageFirst'].get(st)) for st in STAGES), len(p2),
            fmt(np.mean(p2[:BLOCK]), 2) if p2 else '–', fmt(np.mean(p2[-FINAL:]), 2) if p2 else '–',
            s['bins'].get('bootstrap', '–'), s['bins'].get('refinement', '–')))
    lines += ['', 'Episodes are 0-based; "1st success" is its episode index. The M1 times below count '
              'episodes, so they are that index + 1.', '',
              '## Batch', '', '| metric | value [95% CI] | n |', '|---|---|---|',
              '| M1 episodes to 1st success (KM median) | %s | %d (%d censored) |' % (
                  km_cell(card['m1'], cap), n, card['m1']['censored'])]
    for st in STAGES:
        k = card['m1b'][st]
        lines.append('| M1b episodes to 1st %s | %s | %d censored |' % (st, km_cell(k, cap),
                                                                      k['censored']))
    m2 = card['m2']
    lines += ['| M2 jumpstart (Phase 2, first %d) | %s | %d |' % (BLOCK, ci_cell(m2['jumpstart'],
                                                                                 key='mean'), m2['n']),
              '| M2 final (Phase 2, last %d) | %s | %d |' % (FINAL, ci_cell(m2['final'], key='mean'),
                                                            m2['n'])]
    for t, k in m2['timeToTheta'].items():
        lines.append('| M2 Phase 2 episodes until the running mean of %d reaches %s | %s | %d '
                     'censored |' % (BLOCK, t, km_cell(k, card['eref']), k['censored']))
    g = card['m2b']
    lines += ['| M2b last %d minus the %d before (mean) | %s | %d · %s |' % (
                  FINAL, FINAL, ci_cell(g, key='mean'), g['n'],
                  {None: '–', True: 'plateau', False: 'still moving'}[g['plateau']]),
              '| M3 steps per Phase 2 success (median of seeds) | %s | %d |' % (
                  ci_cell(card['m3']['steps'], 0), card['m3']['steps']['n']),
              '| M3 joint energy per Phase 2 success | %s | %d |' % (
                  ci_cell(card['m3']['energy'], 2), card['m3']['energy']['n']),
              '| M4 coverage bins, end of Phase 1 | %s | %d |' % (
                  ci_cell(card['m4']['bootstrap'], 0), card['m4']['bootstrap']['n']),
              '| M4 coverage bins, end of Phase 2 | %s | %d |' % (
                  ci_cell(card['m4']['refinement'], 0), card['m4']['refinement']['n']),
              '| M5 repertoire (min–max over seeds) | %s | %d |' % (
                  '–'.join(map(str, sorted({x for s in card['seeds'] if s['repertoire']
                                            for x in s['repertoire']}))) or '–', n),
              '', '## Sanity checks', '']
    for c in card['checks']:
        mark = {True: 'pass', False: '**FAIL**', None: 'n/a'}[c['ok']]
        lines.append('- %s: %s%s' % (c['name'], mark, ' — ' + c['detail'] if c['detail'] else ''))
    if m2['blocks']:
        lines += ['', '## Phase 2 success rate per %d episodes' % BLOCK, '']
        for s, b in zip([s for s in card['seeds'] if s['p2']], m2['blocks']):
            lines.append('- s%d: %s' % (s['seed'], ' '.join(fmt(x, 2) for x in b)))
    return '\n'.join(lines) + '\n'


# --- the track --------------------------------------------------------------------------------
def ledger_row(card, date):
    m1, m2, g = card['m1'], card['m2'], card['m2b']
    t = next(iter(m2['timeToTheta'].values())) if card['theta'] is not None else None
    r = {'batch': card['batch'], 'date': date, 'protocol': card['protocol'],
         'condition': card['condition'], 'commit': card['commit'],
         'cst': ((card['fingerprint'] or {}).get('cst') or '')[:7], 'n': len(card['seeds']),
         'm1_median': m1['median'], 'm1_low': m1['low'], 'm1_high': m1['high'],
         'censored': m1['censored'], 'm2_jumpstart': m2['jumpstart']['mean'],
         'm2_time_to_theta': t and t['median'], 'm2_final': m2['final']['mean'],
         'm2_plateau': g['plateau'], 'm3_steps': card['m3']['steps']['median'],
         'm3_energy': card['m3']['energy']['median'],
         'm4_bins_p1': card['m4']['bootstrap']['median'],
         'm4_bins_p2': card['m4']['refinement']['median'], 'valid': card['valid']}
    return {k: ('' if v is None else round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}


def write_ledger(card, date, path=LEDGER):
    rows = []
    if os.path.isfile(path):
        with open(path) as f:
            rows = [r for r in csv.DictReader(f) if r['batch'] != card['batch']]
    rows.append(ledger_row(card, date))
    rows.sort(key=lambda r: (r['date'], r['batch']))
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def table(path=LEDGER):
    if not os.path.isfile(path):
        return 'No protocol batch scored yet (%s does not exist).\n' % os.path.relpath(path)
    with open(path) as f:
        rows = list(csv.DictReader(f))
    head = ['date', 'protocol', 'condition', 'commit', 'n', 'M1 KM median [CI]', 'censored',
            'M2 jumpstart', 'M2 final', 'M3 steps', 'M4 bins P2', 'valid']
    out = ['| ' + ' | '.join(head) + ' |', '|---' * len(head) + '|']
    for r in rows:
        m1 = '%s [%s, %s]' % (r['m1_median'] or 'not reached', r['m1_low'] or '–', r['m1_high'] or '–')
        out.append('| ' + ' | '.join([r['date'], r['protocol'], r['condition'], r['commit'], r['n'],
                                      m1, r['censored'], r['m2_jumpstart'] or '–',
                                      r['m2_final'] or '–', r['m3_steps'] or '–',
                                      r['m4_bins_p2'] or '–', r['valid']]) + ' |')
    return '\n'.join(out) + '\n'


# --- two batches ------------------------------------------------------------------------------
def check_compare(a, b, exploratory=False):
    """BAS-01 rules 5 and 6. Returns warnings; raises protocol.Refused."""
    warn = []
    if not (a['protocol'] and b['protocol']):
        if not exploratory:
            raise protocol.Refused('%s is not a protocol batch: only protocol batches are compared '
                                   '(--exploratory to look anyway, never for the track)'
                                   % (a['batch'] if not a['protocol'] else b['batch']))
        return ['EXPLORATORY: not a protocol comparison; nothing here goes in the track']
    fa, fb = a['fingerprint'], b['fingerprint']
    if fa['protocol'] != fb['protocol']:
        raise protocol.Refused('two protocol versions (%s, %s): a protocol is compared only with '
                               'itself' % (fa['protocol'], fb['protocol']))
    if a['condition'] != b['condition']:
        diff = protocol.differences(fa, fb)
        if diff:
            raise protocol.Refused('%s against %s needs one fingerprint (rule 5); these differ:\n  %s'
                                   % (a['condition'], b['condition'], '\n  '.join(diff)))
    else:
        env = [k for k in ENV_KEYS if fa.get(k) != fb.get(k)]
        if env:
            warn.append('the environment changed too (%s): a difference is not only the code'
                        % ', '.join(env))
    return warn


def mw(x, y):
    """Mann-Whitney U two-sided, and the rank-biserial correlation (> 0: x tends larger)."""
    if len(x) < 1 or len(y) < 1:
        return None
    r = mannwhitneyu(x, y, alternative='two-sided')
    return {'p': float(r.pvalue), 'rb': float(2.0 * r.statistic / (len(x) * len(y)) - 1.0)}


def compare(a_dir, b_dir, exploratory=False, ledger=LEDGER):
    a = scored(os.path.abspath(a_dir), ledger)
    b = scored(os.path.abspath(b_dir), ledger)
    warn = check_compare(a, b, exploratory)
    cap = max(a['emax'] + b['emax'])
    t1 = [cap if s['first'] is None else s['first'] + 1 for s in a['seeds']]
    t2 = [cap if s['first'] is None else s['first'] + 1 for s in b['seeds']]
    tests = [('M1 episodes to 1st success (censored tie at %d)' % cap, mw(t1, t2))]

    def per_seed(card, f):
        return [f(s) for s in card['seeds'] if f(s) is not None]
    for name, f in (('M2 final (Phase 2, last %d)' % FINAL,
                     lambda s: float(np.mean(s['p2'][-FINAL:])) if s['p2'] else None),
                    ('M3 steps per Phase 2 success',
                     lambda s: float(np.median(s['p2steps'])) if s['p2steps'] else None),
                    ('M4 coverage bins, end of Phase 2', lambda s: s['bins'].get('refinement'))):
        tests.append((name, mw(per_seed(a, f), per_seed(b, f))))
    done = [t for t in tests if t[1] is not None]
    adj = holm([t[1]['p'] for t in done])
    lr = logrank(x=censored(a), y=censored(b)) if a['m1']['events'] + b['m1']['events'] else None
    lines = ['# %s vs %s' % (a['batch'], b['batch']), '']
    lines += ['> %s' % w for w in warn] + ([''] if warn else [])
    lines += ['A: %s, commit %s, %d seeds · B: %s, commit %s, %d seeds' % (
        a['condition'], a['commit'], len(a['seeds']), b['condition'], b['commit'], len(b['seeds'])),
        '', '| metric | A | B | p (Mann–Whitney) | p Holm | rank-biserial (> 0: A larger) |',
        '|---|---|---|---|---|---|']
    cells = {tests[0][0]: (km_cell(a['m1'], cap), km_cell(b['m1'], cap)),
             tests[1][0]: (ci_cell(a['m2']['final'], key='mean'), ci_cell(b['m2']['final'], key='mean')),
             tests[2][0]: (ci_cell(a['m3']['steps'], 0), ci_cell(b['m3']['steps'], 0)),
             tests[3][0]: (ci_cell(a['m4']['refinement'], 0), ci_cell(b['m4']['refinement'], 0))}
    for name, r in tests:
        p_adj = adj[[t[0] for t in done].index(name)] if r else None
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            name, cells[name][0], cells[name][1], fmt(r and r['p'], 3), fmt(p_adj, 3),
            fmt(r and r['rb'], 2)))
    lines += ['', 'Log-rank on M1 (the check on the tie): %s' % (
        'p = %.3f' % lr.pvalue if lr is not None else 'no successes in either batch')]
    if a['condition'] == b['condition'] and a['fingerprint'] and b['fingerprint'] \
            and a['fingerprint']['commit'] != b['fingerprint']['commit']:
        log = subprocess.run(['git', '-C', protocol.ROOT, 'log', '--oneline', '%s..%s' % (
            a['fingerprint']['commit'], b['fingerprint']['commit'])], capture_output=True, text=True)
        lines += ['', 'What changed from A to B (`git log A..B`):', '', '```',
                  log.stdout.strip() or log.stderr.strip(), '```']
    if exploratory and warn:
        lines += ['', '> ' + warn[0]]
    return '\n'.join(lines) + '\n'


def censored(card):
    cap = max(card['emax'])
    ev = [s['first'] + 1 for s in card['seeds'] if s['first'] is not None]
    return CensoredData(uncensored=ev, right=[cap] * (len(card['seeds']) - len(ev)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('score', help='write the batch\'s scorecard (and a protocol batch\'s ledger line)')
    s.add_argument('batch')
    s.add_argument('--theta', type=float,
                   help='M2\'s threshold; default the protocol\'s, else %s' % ', '.join(map(str, THETAS)))
    s.add_argument('--jobs', type=int, help='seeds read at once (default: all)')
    sub.add_parser('table', help='print the track (bench/ledger.csv) as Markdown')
    c = sub.add_parser('compare', help='test two scored batches against each other')
    c.add_argument('a')
    c.add_argument('b')
    c.add_argument('--exploratory', action='store_true',
                   help='compare batches that are not protocol batches; never for the track')
    a = ap.parse_args()
    if a.cmd == 'score':
        card = score(a.batch, a.theta, a.jobs)
        print(render(card), end='')
    elif a.cmd == 'table':
        print(table(), end='')
    else:
        try:
            print(compare(a.a, a.b, a.exploratory), end='')
        except protocol.Refused as e:
            sys.exit('refused: %s' % e)


if __name__ == '__main__':
    main()
