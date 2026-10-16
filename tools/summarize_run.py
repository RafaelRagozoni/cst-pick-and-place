"""A short Markdown summary of one or more run logs: the learning curve in at most ~20 rows, and the
key moments. Fixed size whatever the run length, so it is cheap to read (by a person or by Claude).

    python3 tools/summarize_run.py runs/<batch>            # every seed in the batch
    python3 tools/summarize_run.py runs/<batch>/s1 [--block 100] [-o file.md]

Works on a run still going (up to its last finished episode). Writes summary.md into the folder
given (or next to the log) and prints it.
"""
import argparse
import math
import os
import statistics
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'coppelia_environment'))
import runlog                                   # noqa: E402
from metrics import characterise                # noqa: E402

STAGES = ['reach', 'grasp', 'transport', 'release']
SOURCES = ['curiosity', 'task', 'safety']
DIST_MARKS = [0.20, 0.10, 0.05]                 # m; reach fires at 0.05
MAX_ROWS = 20


class Block:
    """What a block of episodes adds up to. Blocks merge, so rows can be any multiple of --block."""

    def __init__(self):
        self.episodes = self.successes = self.steps = 0
        self.stages = Counter()                 # episodes that reached each stage
        self.best = math.inf
        self.mins = []                          # per-episode closest approach
        self.new_bins = 0
        self.sources = Counter()                # steps by who set the goal
        self.habits = Counter()                 # plans started, by habit
        self.spread = None

    def merge(self, o):
        self.episodes += o.episodes
        self.successes += o.successes
        self.steps += o.steps
        self.stages += o.stages
        self.best = min(self.best, o.best)
        self.mins += o.mins
        self.new_bins += o.new_bins
        self.sources += o.sources
        self.habits += o.habits
        self.spread = o.spread if o.spread is not None else self.spread
        return self


def scan(log, block):
    blocks, cur = [], Block()
    bins, moments, marks = set(), [], list(DIST_MARKS)
    seen_stage, first_success = set(), None
    head, last_rep = {}, None
    energy_ok, steps_ok = [], []
    for ep, recs, summ in runlog.episodes(log):
        if not head:
            head = {k: recs[0].get(k) for k in ('condition', 'seed', 'selection')}
        dmin, plan, nb = math.inf, None, 0
        for r in recs:
            o = r.get('obs')
            if o:
                dmin = min(dmin, o['derived']['eefToCube'])
                b = characterise(o)
                if b not in bins:
                    bins.add(b)
                    nb += 1
            if r.get('done'):
                continue
            cur.steps += 1
            if r.get('goalSource'):
                cur.sources[r['goalSource']] += 1
            if r.get('plan') is not None and r['plan'] != plan:
                plan = r['plan']
                cur.habits[r['habit_id']] += 1
            if r.get('spread') is not None:
                cur.spread = r['spread']
            if r.get('repertoire'):
                last_rep = r['repertoire']
            g = r.get('goal_fired')
            if g and g not in seen_stage:
                seen_stage.add(g)
                moments.append((ep, r['step'], 'first **%s**' % g))
        cur.episodes += 1
        cur.best = min(cur.best, dmin)
        cur.mins.append(dmin)
        cur.new_bins += nb
        while marks and dmin < marks[0]:
            moments.append((ep, None, 'first time within %.2f m of the cube (%.3f m)'
                            % (marks.pop(0), dmin)))
        for s in (summ or {}).get('goalsReached', []):
            cur.stages[s] += 1
        if summ and summ.get('success'):
            cur.successes += 1
            energy_ok.append(summ['jointEnergy'])
            steps_ok.append(summ['steps'])
            if first_success is None:
                first_success = ep
                moments.append((ep, summ['steps'], '**first SUCCESS**'))
        if cur.episodes == block:
            blocks.append(cur)
            cur = Block()
    if cur.episodes:
        blocks.append(cur)
    totals = {'bins': len(bins), 'firstSuccess': first_success, 'repertoire': last_rep,
              'stepsPerSuccess': statistics.mean(steps_ok) if steps_ok else None,
              'energyPerSuccess': statistics.mean(energy_ok) if energy_ok else None}
    return head, blocks, sorted(moments, key=lambda m: (m[0], m[1] or 0)), totals


def pct(c, n):
    return '%.0f%%' % (100.0 * c / n) if n else '–'


def rows(blocks, block):
    per = max(1, math.ceil(len(blocks) / MAX_ROWS))
    out, start = [], 0
    for i in range(0, len(blocks), per):
        b = Block()
        for x in blocks[i:i + per]:
            b.merge(x)
        out.append((start, start + b.episodes - 1, b))
        start += b.episodes
    return out


def render(label, meta, head, blocks, moments, totals, block):
    n = sum(b.episodes for b in blocks)
    steps = sum(b.steps for b in blocks)
    succ = sum(b.successes for b in blocks)
    sel = head.get('selection') or meta.get('selection') or '?'
    status = 'finished' if meta.get('end') else 'in progress or interrupted'
    L = ['## %s — %s, %s, seed %s' % (label, head.get('condition') or meta.get('condition'), sel,
                                       head.get('seed') or meta.get('seed')),
         '',
         '%d episodes, %d steps, %s. Code %s. Success %d (%s); first success: %s.'
         % (n, steps, status, meta.get('commit', '?'), succ, pct(succ, n),
            'episode %d' % totals['firstSuccess'] if totals['firstSuccess'] is not None else 'never'),
         'Coverage %d bins. Repertoire %s.' % (totals['bins'], totals['repertoire'] or 'not logged'),
         '']
    if meta.get('resumes'):
        L.insert(-1, 'Resumed from its checkpoint at episode %s.' % ', '.join(
            str(r['fromEpisode']) for r in meta['resumes']))
    if totals['stepsPerSuccess'] is not None:
        L.insert(-1, 'Per success: %.0f steps, %.2f rad joint energy.'
                 % (totals['stepsPerSuccess'], totals['energyPerSuccess']))
    L += ['| episodes | success | reach / grasp / transp. / release | closest (best · median) '
          '| new bins | goal set by cur / task / safety | most chosen habits | σ |',
          '|---|---|---|---|---|---|---|---|']
    for a, z, b in rows(blocks, block):
        src = sum(b.sources.values())
        hab = sum(b.habits.values())
        top = ', '.join('%s %s' % (h, pct(c, hab)) for h, c in b.habits.most_common(2))
        L.append('| %d–%d | %s | %s | %.2f · %.2f m | %d | %s | %s | %s |' % (
            a, z, pct(b.successes, b.episodes),
            ' / '.join(str(b.stages[s]) for s in STAGES),
            b.best, statistics.median(b.mins), b.new_bins,
            ' / '.join(pct(b.sources[s], src) for s in SOURCES), top,
            '%.3f' % b.spread if b.spread is not None else '–'))
    L += ['', '**Key moments**' if moments else '**Key moments:** none yet (no stage reached, '
          'no approach under %.2f m).' % DIST_MARKS[0]]
    for ep, step, what in moments[:15]:
        L.append('- episode %d%s: %s' % (ep, ', step %d' % step if step is not None else '', what))
    if len(moments) > 15:
        L.append('- … %d more' % (len(moments) - 15))
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='+', help='batch folder, run folder (s1) or log file')
    ap.add_argument('--block', type=int, default=100, help='episodes per base block')
    ap.add_argument('-o', '--out', help='write here (default: summary.md in the first folder)')
    a = ap.parse_args()

    logs = runlog.find_logs(a.paths)
    parts, table = [], []
    for label, log, meta in logs:
        head, blocks, moments, totals = scan(log, a.block)
        if not blocks:
            parts.append('## %s\n\nNo finished episode yet.' % label)
            continue
        parts.append(render(label, meta, head, blocks, moments, totals, a.block))
        n = sum(b.episodes for b in blocks)
        table.append('| %s | %d | %d | %s | %.2f m | %d |' % (
            label, n, sum(b.successes for b in blocks),
            totals['firstSuccess'] if totals['firstSuccess'] is not None else 'never',
            min(b.best for b in blocks), totals['bins']))
    out = ['# Run summary', '']
    if len(table) > 1:
        out += ['| run | episodes | successes | first success | closest | bins |',
                '|---|---|---|---|---|---|'] + table + ['']
    out += ['\n\n'.join(parts), '',
            '_cur / task / safety: share of steps whose goal each drive set. σ: the reference '
            'spread at the block\'s end, what a habit run once is given; in runs before '
            '2026-10-16 17:37, one spread pooled over every execution (0 means UCB/Thompson '
            'act like greedy)._']
    text = '\n'.join(out)
    dest = a.out or os.path.join(a.paths[0] if os.path.isdir(a.paths[0])
                                 else os.path.dirname(a.paths[0]) or '.', 'summary.md')
    with open(dest, 'w') as f:
        f.write(text + '\n')
    print(text)
    print('\n(written to %s)' % dest, file=sys.stderr)


if __name__ == '__main__':
    main()
