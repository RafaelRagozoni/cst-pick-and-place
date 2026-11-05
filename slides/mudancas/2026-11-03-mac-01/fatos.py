"""Facts of the MAC-01 slides (vault spec APR-01): every number the slides show, with its source.

    bash slides/mudancas/2026-11-03-mac-01/midia.sh          # first: the captions read its sidecar
    python3 slides/mudancas/2026-11-03-mac-01/fatos.py       # -> fatos.json beside this file

The exploratory runs (3 seeds × 500 episodes, out of protocol) against seeds 1–3 of the amended P1
(C4), episodes 400–499, as macro_report.py --window 400 499 --seeds 1 2 3 reads them, and the pass
test fixed in spec MAC-01 (Testing 3) before running. What entry 42 measured with one-off scripts
is typed by hand, marked manual, citing it.
"""
import concurrent.futures
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'tools'))
import episode_pick                             # noqa: E402
import macro_report                             # noqa: E402
import slide_facts as sf                        # noqa: E402

SUM = '2026-11-03_1242_C0_ucb-0.1_lp_macro-sum'
COPY = '2026-11-03_1242_C0_ucb-0.1_lp_macro-copy'
C4 = '2026-10-28_1803_C4_ucb-0.1_lp_P1'
SEEDS = (1, 2, 3)
WINDOW = (400, 499)
SEED_VIDEO = os.path.join(HERE, 'media', 'soma_s1.mp4.json')
# the predictions in spec MAC-01, Testing 2, as numbers for the chart's dashed lines
PREDICTED_SUM_TICKS = (20, 30)
PREDICTED_COPY_TICKS = 90


def log_of(batch, seed):
    return os.path.join(sf.run_path(batch), 's%d' % seed, 'log.jsonl.gz')


def window_row(job):
    """macro_report's pass columns for one seed: reach ticks (median), grasps, transports and
    collision onsets per 100 episodes, over WINDOW."""
    batch, seed = job
    scanned = macro_report.scan('s%d' % seed, log_of(batch, seed))
    rows = macro_report.last_rows(scanned, 100, WINDOW)
    reach = [r['reach'] for r in rows if r['reach'] is not None]
    per_100 = lambda key: 100.0 * sum(r[key] for r in rows) / len(rows)
    return {'reach': statistics.median(reach) if reach else None, 'grasps': per_100('grasp'),
            'transports': per_100('transport'), 'collisions': per_100('onsets'),
            'macro_reach_runs': scanned.runs > 0 and any(m.startswith('macro_reach_')
                                                         for m in scanned.chosen)}


def css_percent(value, top):
    """A height or width for CSS: a share of top, with a decimal point (CSS does not read commas)."""
    return '%.1f%%' % (100.0 * value / top) if value else '0%'


def ticks_list(values):
    return ' / '.join(sf.fmt_number(v) if v is not None else '—' for v in values)


def main():
    facts = sf.FactSheet()
    jobs = [(batch, seed) for batch in (SUM, COPY, C4) for seed in SEEDS]
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        rows = dict(zip(jobs, pool.map(window_row, jobs)))
    report = 'macro_report.py --window %d %d --seeds 1 2 3, runs/%%s' % WINDOW

    facts.add('mac01.n_seeds', len(SEEDS), str(len(SEEDS)), 'spec MAC-01, Testing 1 (seeds 1–3)')
    with open(os.path.join(sf.run_path(SUM), 's1', 'run.json')) as run_file:
        episodes = json.load(run_file)['emax']
    facts.add('mac01.n_episodios', episodes, str(episodes), 'runs/%s/s1/run.json, emax' % SUM)
    facts.add('mac01.janela', list(WINDOW), '%d–%d' % WINDOW, 'spec MAC-01, Testing 1')

    reach = {batch: [rows[(batch, s)]['reach'] for s in SEEDS] for batch in (SUM, COPY, C4)}
    for key, batch in (('soma', SUM), ('copia', COPY), ('c4', C4)):
        known = [v for v in reach[batch] if v is not None]
        facts.add('mac01.reach_' + key, known, sf.fmt_number_range(min(known), max(known)),
                  report % batch + ', coluna reach ticks')
        facts.add('mac01.reach_%s_seeds' % key, reach[batch], ticks_list(reach[batch]),
                  report % batch + ', coluna reach ticks, seeds 1 / 2 / 3')
    tallest = max(v for values in reach.values() for v in values if v is not None)
    for key, batch in (('soma', SUM), ('copia', COPY), ('c4', C4)):
        for seed, value in zip(SEEDS, reach[batch]):
            facts.add('mac01.reach_%s_s%d' % (key, seed), value,
                      sf.fmt_number(value) if value is not None else 'travou',
                      report % batch + ', coluna reach ticks, s%d' % seed)
            facts.add('mac01.h_reach_%s_s%d' % (key, seed), None, css_percent(value, tallest),
                      'altura da barra: mac01.reach_%s_s%d sobre a maior' % (key, seed))
    facts.add('mac01.h_prev_soma', None, css_percent(PREDICTED_SUM_TICKS[1], tallest),
              'altura da linha: o topo do previsto para a soma (spec MAC-01, Testing 2) sobre a maior barra')
    facts.add('mac01.h_prev_copia', None, css_percent(PREDICTED_COPY_TICKS, tallest),
              'altura da linha: o previsto para a cópia (spec MAC-01, Testing 2) sobre a maior barra')
    never = [s for s, v in zip(SEEDS, reach[COPY]) if v is None]
    facts.add('mac01.copia_sem_reach', never, ', '.join('s%d' % s for s in never),
              report % COPY + ': seeds sem reach nos episódios %d–%d' % WINDOW)

    c4_rows = [rows[(C4, s)] for s in SEEDS]
    least_grasps = min(r['grasps'] for r in c4_rows)
    least_transports = min(r['transports'] for r in c4_rows)
    most_collisions = max(r['collisions'] for r in c4_rows)
    facts.add('mac01.limite_grasps', least_grasps, sf.fmt_number(least_grasps),
              report % C4 + ': o pior dos 3 seeds (spec MAC-01, Testing 3)')
    facts.add('mac01.limite_transp', least_transports, sf.fmt_number(least_transports),
              report % C4 + ': o pior dos 3 seeds (spec MAC-01, Testing 3)')
    facts.add('mac01.limite_colisoes', most_collisions, sf.fmt_number(most_collisions),
              report % C4 + ': o pior dos 3 seeds (spec MAC-01, Testing 3)')
    passing = 0
    for seed in SEEDS:
        row = rows[(SUM, seed)]
        copy_reach = rows[(COPY, seed)]['reach']
        faster = (row['reach'] is not None and row['reach'] < rows[(C4, seed)]['reach']
                  and (copy_reach is None or row['reach'] < copy_reach))
        passing += (row['macro_reach_runs'] and faster and row['grasps'] >= least_grasps
                    and row['transports'] >= least_transports
                    and row['collisions'] <= most_collisions)
    facts.add('mac01.passam', passing, str(passing),
              'spec MAC-01, Testing 3, aplicado a ' + report % SUM)

    seed_video = json.load(open(SEED_VIDEO)) if os.path.isfile(SEED_VIDEO) else None
    if seed_video is None:
        raise SystemExit('%s missing: run midia.sh first' % SEED_VIDEO)
    first, wins, after = sf.success_after_first(log_of(SUM, 1))
    if first != seed_video['episode']:
        raise SystemExit('the video shows episode %d, the first success is %d'
                         % (seed_video['episode'], first))
    facts.add('mac01.primeiro_soma_s1', first, str(first), 'runs/%s/s1, 1º sucesso' % SUM)
    facts.add('mac01.depois_soma_s1', [wins, after], '%d de %d' % (wins, after),
              'runs/%s/s1, sucessos depois do 1º (slide_facts.success_after_first)' % SUM)
    facts.add('mac01.depois_soma_s1_pct', wins / after, sf.fmt_percent(wins / after),
              'runs/%s/s1, sucessos depois do 1º' % SUM)
    without = []
    for seed in SEEDS[1:]:
        try:
            sf.success_after_first(log_of(SUM, seed))
        except ValueError:
            without.append(seed)
    facts.add('mac01.soma_sem_acerto', without, ' e '.join('s%d' % s for s in without),
              'runs/%s: seeds sem sucesso nenhum' % SUM)
    for seed in SEEDS:
        try:
            _, c4_wins, c4_after = sf.success_after_first(log_of(C4, seed))
            text = sf.fmt_percent(c4_wins / c4_after, 1 if c4_wins / c4_after < 0.01 else 0)
            value = [c4_wins, c4_after]
        except ValueError:
            summaries = episode_pick.episode_summaries(log_of(C4, seed))
            text, value = 'nenhum acerto em %s episódios' % sf.fmt_number(len(summaries)), None
        facts.add('mac01.c4_depois_s%d' % seed, value, text,
                  'runs/%s/s%d, sucessos depois do 1º' % (C4, seed))
    for key, batch in (('soma', SUM), ('c4', C4)):
        for seed in SEEDS:
            try:
                _, seed_wins, seed_after = sf.success_after_first(log_of(batch, seed))
                share = seed_wins / seed_after
                label = sf.fmt_percent(share, 1 if share < 0.01 else 0)
            except ValueError:
                share = None
                episodes_run = len(episode_pick.episode_summaries(log_of(batch, seed)))
                label = 'nunca acertou em %s ep.' % sf.fmt_number(episodes_run)
            facts.add('mac01.taxa_depois_%s_s%d' % (key, seed), share, label,
                      'runs/%s/s%d, sucessos depois do 1º / episódios depois do 1º' % (batch, seed))
            facts.add('mac01.h_taxa_depois_%s_s%d' % (key, seed), None, css_percent(share or 0, 1.0),
                      'altura da barra: mac01.taxa_depois_%s_s%d, eixo 0–100%%' % (key, seed))
    card = sf.bench.scored(sf.run_path(C4))
    firsts = [s['first'] for s in card['seeds'] if s['first'] is not None]
    facts.add('mac01.c4_n_seeds', len(card['seeds']), str(len(card['seeds'])),
              'scorecard de runs/%s: seeds' % C4)
    facts.add('mac01.c4_primeiros', firsts, sf.fmt_number_range(min(firsts), max(firsts)),
              'scorecard de runs/%s: 1º sucesso dos seeds que acertaram' % C4)

    fired = seed_video['fired']
    end = seed_video['stills'][-1]['step']
    stages = [('reach', 0, fired['reach']), ('grasp', fired['reach'], fired['grasp']),
              ('transport', fired['grasp'], fired['transport']),
              ('release', fired['transport'], fired['release'])]
    for stage, start, stop in stages:
        facts.add('mac01.ep_ticks_' + stage, stop - start, sf.fmt_number(stop - start),
                  'media/soma_s1.mp4.json (midia.sh): passos entre as etapas')
        facts.add('mac01.ep_largura_' + stage, None, '%.1f%%' % (100.0 * (stop - start) / end),
                  'largura da barra: mac01.ep_ticks_%s sobre o episódio' % stage)
    records = episode_pick.extract_episodes(log_of(SUM, 1), {first})[first]
    toggles, moving, previous_open, previous_width = 0, 0, None, None
    for record in records:
        if record.get('done') or record['step'] >= fired['reach']:
            break
        gripper = record['obs']['innerSense']['gripper']
        toggles += previous_open is not None and gripper['commanded_open'] != previous_open
        moving += previous_width is not None and abs(gripper['width'] - previous_width) > 1e-4
        previous_open, previous_width = gripper['commanded_open'], gripper['width']
    facts.add('mac01.ep_garra_trocas', toggles, sf.fmt_number(toggles),
              'runs/%s/s1, ep. %d: trocas do comando da garra antes do reach' % (SUM, first))
    facts.add('mac01.ep_garra_ticks', moving, sf.fmt_number(moving),
              'runs/%s/s1, ep. %d: ticks antes do reach com a abertura da garra mudando' % (SUM, first))
    facts.add('mac01.ep_total', end, sf.fmt_number(end), 'media/soma_s1.mp4.json: o último passo')
    facts.add('mac01.ep_marca_base', None, css_percent(rows[(C4, 1)]['reach'], end),
              'posição da marca: mac01.reach_c4_s1 sobre o episódio')
    facts.add('mac01.video_ep', first, 'ep. %d' % first, 'media/soma_s1.mp4.json (midia.sh)')
    facts.add('mac01.video_regra', seed_video['rule'], seed_video['rule'],
              'media/soma_s1.mp4.json (midia.sh)')
    facts.add('mac01.video_vel', seed_video['stride'], '%d×' % seed_video['stride'],
              'media/soma_s1.mp4.json (midia.sh), stride')

    spec = 'spec MAC-01 (vault Rafael/Specs)'
    entry = 'code_notes entrada 42'
    facts.add_manual('mac01.reach_passos', '96', spec + ', medição de partida: reach, mediana dos '
                     'trechos do P1 da emenda')
    facts.add_manual('mac01.reach_liquido', '~20', spec + ', medição de partida (seed 4, ep. 242)')
    facts.add_manual('mac01.vel_max', '0,4 rad/s', spec + ', As regras (soma)')
    facts.add_manual('mac01.tick', '50 ms', 'tools/replay.py: 1× = 20 passos/s')
    facts.add_manual('mac01.prev_ep', '30', spec + ', Testing 2')
    facts.add_manual('mac01.prev_ticks_soma', '~20–30', spec + ', Testing 2')
    facts.add_manual('mac01.prev_ticks_copia', '~90', spec + ', Testing 2')
    facts.add_manual('mac01.reach_eps', '21, 16 e 15', entry + ', previsões')
    facts.add_manual('mac01.ticks_em_macro', '35–100%', entry + ', previsões')
    facts.add_manual('mac01.grasp_cumpre', '84–100%', entry + ', previsões')
    facts.add_manual('mac01.garra_ticks', '74–80%', entry + ', "Em 30 segundos"')
    facts.add_manual('mac01.troca_garra', '~43', entry + ', "Em 30 segundos"')
    facts.add_manual('mac01.credito_macro', '0,112', entry + ', "Crédito no contexto inicial"')
    facts.add_manual('mac01.credito_primitivo', '0,003', entry + ', "Crédito no contexto inicial"')
    facts.add_manual('mac01.travou_eps', '478', entry + ', "Em 30 segundos" (cópia s1)')
    facts.add_manual('mac01.exemplo_giro', 'j0 −25° · j1 −9° · j2 −31° · j3 +17°',
                     entry + ', macro_reach_8 da soma s1')
    facts.write(os.path.join(HERE, 'fatos.json'), 'python3 slides/mudancas/2026-11-03-mac-01/fatos.py')
    for key, fact in facts.facts.items():
        print('%-30s %s' % (key, fact['texto']))


if __name__ == '__main__':
    main()
