"""Facts for the weekly slides (vault spec APR-01): pt-BR number formatting, the fact sheet that
becomes a change's fatos.json, and the collectors that read the ledger, the scorecards and
carry_report. A change's fatos.py uses this module; a slide shows a number only through
`{{< fato key >}}`, which reads the file written here.

    fatos.json = {"gerado_por": "<command>", "fatos": {"<key>": {"valor": ..., "texto": "<pt-BR>",
                  "fonte": "<origin>", "manual": <bool>}}}

Real run data lives where bench and carry_report look for it: SIM_RUNS, by default the main
checkout's runs/ folder.
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench                                    # noqa: E402
import carry_report                             # noqa: E402
import runlog                                   # noqa: E402

RUNS = os.environ.get('SIM_RUNS', os.path.expanduser('~/Mestrado/Simulation/runs'))
MINUS = '−'
EN_DASH = '–'


def run_path(batch_name):
    return os.path.join(RUNS, batch_name)


# --- pt-BR formatting -------------------------------------------------------------------------
def fmt_number(value, decimals=0):
    """6900 -> '6.900', 0.27 -> '0,27', -0.06 -> '−0,06' (U+2212). A negative that rounds to zero
    carries no sign."""
    text = '{:,.{d}f}'.format(round(value, decimals), d=decimals)
    text = text.replace(',', '\0').replace('.', ',').replace('\0', '.')
    if text.startswith('-'):
        text = MINUS + text[1:]
    if text.startswith(MINUS) and not any(c in '123456789' for c in text):
        text = text[1:]
    return text


def fmt_percent(fraction, decimals=0):
    """0.011, 1 -> '1,1%'."""
    return fmt_number(fraction * 100, decimals) + '%'


def fmt_number_range(low, high, decimals=0):
    """8, 32 -> '8–32'; a range whose ends format the same is one number: 1.0, 1.0 -> '1'."""
    low_text, high_text = fmt_number(low, decimals), fmt_number(high, decimals)
    return low_text if low_text == high_text else low_text + EN_DASH + high_text


def fmt_percent_range(low, high, decimals=0):
    """0.93, 0.97 -> '93–97%' (one % sign, at the end)."""
    return fmt_number_range(low * 100, high * 100, decimals) + '%'


# --- the fact sheet ---------------------------------------------------------------------------
class FactSheet:
    def __init__(self):
        self.facts = {}

    def _put(self, key, valor, texto, fonte, manual):
        if key in self.facts:
            raise ValueError('fact key repeated: %s' % key)
        if not fonte:
            raise ValueError('fact %s has no fonte: every fact names where it came from' % key)
        self.facts[key] = {'valor': valor, 'texto': texto, 'fonte': fonte, 'manual': manual}

    def add(self, key, valor, texto, fonte):
        """A fact computed from data: its value, its pt-BR text, and where it came from."""
        self._put(key, valor, texto, fonte, False)

    def add_manual(self, key, texto, fonte, valor=None):
        """A fact typed by hand (marked "manual": true, so a reader can tell)."""
        self._put(key, valor, texto, fonte, True)

    def write(self, path, gerado_por):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'gerado_por': gerado_por, 'fatos': self.facts}, f, ensure_ascii=False,
                      indent=1)
            f.write('\n')


# --- collectors -------------------------------------------------------------------------------
def ledger_row(batch_name, ledger_path=bench.LEDGER):
    """READS (bench.ledger_row writes) the batch's row of the ledger, numbers converted from their
    strings; KeyError if the batch is not there."""
    with open(ledger_path, newline='') as f:
        for row in csv.DictReader(f):
            if row['batch'] == batch_name:
                return {k: _number(v) for k, v in row.items()}
    raise KeyError('batch not in the ledger %s: %s' % (ledger_path, batch_name))


def _number(text):
    try:
        return float(text)
    except ValueError:
        return text


def primary_p(batch_a, batch_b):
    """The Mann-Whitney p of M2 final between two batches (bench.tests), read from their
    scorecards in RUNS (scored again if a log changed)."""
    tests = bench.tests(bench.scored(run_path(batch_a)), bench.scored(run_path(batch_b)))
    for t in tests:
        if t['key'] == 'm2_final':
            return t['test']['p']
    raise KeyError('m2_final test missing')


def first_success_seeds(card):
    """Seeds of the scorecard that had a first success."""
    return sum(1 for s in card['seeds'] if s['first'] is not None)


def phase2_successes(card):
    """(successes, episodes) of Phase 2, summed over the seeds."""
    return (sum(sum(s['p2']) for s in card['seeds']), sum(len(s['p2']) for s in card['seeds']))


def carry_ranges(batch_dir, block=500):
    """Ranges over carry_report's **all** rows (carry_report.pool_by_block: block k of every seed
    that reached it, summed), every row, the last one included, which is how code_notes entry 40
    read its "93–97%", "0–2", "1–22%" and "8–32". {'drop_share': (min, max) of dropped_away /
    grasps as fractions (rows without grasps left out); 'by_open_share': (min, max) of the drops
    whose last action was grab_open, over the rows with drops; 'open_new_share': (min, max) of the
    grab_open picks with the cube held whose habit was new to its bin (UCB's forced draw, before
    borrowing), over the rows with such picks; 'transports_per_100': (min, max);
    'grasps': total grasps}."""
    rows = carry_report.pool_by_block(
        [carry_report.scan(log, block) for _, log, _ in runlog.find_logs([batch_dir])])
    if not rows:
        raise ValueError('no episode in %s' % batch_dir)
    shares = [r.dropped_away / r.grasps for r in rows if r.grasps]
    transports = [100.0 * r.transports / r.episodes for r in rows]
    by_open = [r.dropped_by_open / r.dropped_away for r in rows if r.dropped_away]
    open_new = [r.open_new / r.held_open for r in rows if r.held_open]
    return {'drop_share': (min(shares), max(shares)) if shares else None,
            'by_open_share': (min(by_open), max(by_open)) if by_open else None,
            'open_new_share': (min(open_new), max(open_new)) if open_new else None,
            'transports_per_100': (min(transports), max(transports)),
            'grasps': sum(r.grasps for r in rows)}


def success_after_first(log):
    """(episode of the first success, successes after it, episodes after it) in one log;
    ValueError if the log has no success."""
    first, wins, after = None, 0, 0
    for ep, _, summ in runlog.episodes(log):
        ok = bool((summ or {}).get('success'))
        if first is None:
            if ok:
                first = ep
        else:
            after += 1
            wins += ok
    if first is None:
        raise ValueError('no success in %s' % log)
    return first, wins, after
