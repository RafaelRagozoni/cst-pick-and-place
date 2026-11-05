"""Facts of the 2026-11-11 meeting's own slides (vault spec APR-01): headline, starting point,
closing. The change slides bring their own (mudancas/*/fatos.json).

    bash slides/reunioes/2026-11-11/midia.sh       # first: the captions read the videos' sidecars
    python3 slides/reunioes/2026-11-11/fatos.py    # -> fatos.json beside this file
"""
import concurrent.futures
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'tools'))
import runlog                                   # noqa: E402
import slide_facts as sf                        # noqa: E402

BASE = '2026-10-21_0842_C4_ucb-0.1_lp_P1'
VIDEO_SEED = 's1'                               # the seed midia.sh replays; checked against its rule


def sidecar(name):
    path = os.path.join(HERE, 'media', name + '.json')
    if not os.path.isfile(path):
        raise SystemExit('%s missing: run midia.sh first' % path)
    with open(path) as sidecar_file:
        return json.load(sidecar_file)


def after_first(job):
    label, log = job
    try:
        return label, sf.success_after_first(log)
    except ValueError:
        return label, None


def sampled(episodes):
    return ', '.join(str(e) for e in episodes[:2]) + ', …, %d' % episodes[-1]


def main():
    facts = sf.FactSheet()
    row = sf.ledger_row(BASE)
    ledger = 'bench/ledger.csv, %s (commit %s)' % (BASE, row['commit'])
    facts.add('reuniao.n_seeds', int(row['n']), str(int(row['n'])), ledger + ', coluna n')
    facts.add('reuniao.m1_mediana', row['m1_median'], sf.fmt_number(row['m1_median']),
              ledger + ', coluna m1_median')
    facts.add('reuniao.m1_faixa', [row['m1_low'], row['m1_high']],
              '%s e %s' % (sf.fmt_number(row['m1_low']), sf.fmt_number(row['m1_high'])),
              ledger + ', colunas m1_low e m1_high')
    wins, episodes = sf.phase2_successes(sf.bench.scored(sf.run_path(BASE)))
    facts.add('reuniao.fase2_acertos', [wins, episodes], '%d em %s' % (wins, sf.fmt_number(episodes)),
              'scorecard de runs/%s: sucessos e episódios da Fase 2, somados nos seeds' % BASE)
    facts.add('reuniao.fase2_pct', wins / episodes, sf.fmt_percent(wins / episodes),
              'scorecard de runs/%s: sucessos da Fase 2 / episódios da Fase 2' % BASE)

    logs = [(label, log) for label, log, _ in runlog.find_logs([sf.run_path(BASE)])]
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(logs)) as pool:
        results = dict(pool.map(after_first, logs))
    best = max((r[1], label) for label, r in results.items() if r is not None)[1]
    if best != VIDEO_SEED:
        raise SystemExit('the seed with most successes after the first is %s, but midia.sh '
                         'replays %s' % (best, VIDEO_SEED))
    _, best_wins, best_after = results[best]
    facts.add('reuniao.video_seed', best, 'seed ' + best.lstrip('s'),
              'runs/%s: o seed com mais acertos depois do 1º' % BASE)
    facts.add('reuniao.video_seed_acertos', [best_wins, best_after],
              '%d de %d' % (best_wins, best_after),
              'runs/%s/%s, sucessos depois do 1º (slide_facts.success_after_first)' % (BASE, best))

    for key, name in (('curto', 'aprendizado_curto.mp4'), ('longo', 'aprendizado_longo.mp4')):
        video = sidecar(name)
        facts.add('reuniao.video_%s_regra' % key, video['rule'], video['rule'],
                  'media/%s.json (midia.sh)' % name)
        facts.add('reuniao.video_%s_eps' % key, video['episodes'], sampled(video['episodes']),
                  'media/%s.json (midia.sh)' % name)
        facts.add('reuniao.video_%s_vel' % key, video['stride'], '%d×' % video['stride'],
                  'media/%s.json (midia.sh), stride' % name)
        facts.add('reuniao.video_%s_seg' % key, video['seconds'],
                  sf.fmt_number(video['seconds']) + ' s', 'media/%s.json (midia.sh)' % name)
    facts.write(os.path.join(HERE, 'fatos.json'), 'python3 slides/reunioes/2026-11-11/fatos.py')
    for key, fact in facts.facts.items():
        print('%-30s %s' % (key, fact['texto']))


if __name__ == '__main__':
    main()
