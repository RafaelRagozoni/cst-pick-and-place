"""Facts of the CRE-01 slides (vault spec APR-01): every number the slides show, with its source.

    bash slides/mudancas/2026-10-27-cre-01/midia.sh          # first: the captions read its sidecars
    python3 slides/mudancas/2026-10-27-cre-01/fatos.py       # -> fatos.json beside this file

Computed from the ledger, the scorecards, carry_report's "all" rows (as code_notes entry 40 read
them) and the media's sidecars; the few typed by hand are marked manual and cite where they come
from. Slow part: carry_report over two batches of 9 logs, run in parallel (~10 min).
"""
import concurrent.futures
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'tools'))
import slide_facts as sf                        # noqa: E402

BASE = '2026-10-21_0842_C4_ucb-0.1_lp_P1'
NO_AMENDMENT = '2026-10-27_1851_C4_ucb-0.1_lp_P1'
AMENDED = '2026-10-28_1803_C4_ucb-0.1_lp_P1'
STAGE_VIDEO = os.path.join(HERE, 'media', 'cre01_s1.mp4.json')
STRIP_VIDEO = os.path.join(HERE, 'media', 'base_s1.mp4.json')


def carry(batch):
    return sf.carry_ranges(sf.run_path(batch))


def sidecar(path):
    if not os.path.isfile(path):
        raise SystemExit('%s missing: run midia.sh first' % path)
    with open(path) as sidecar_file:
        return json.load(sidecar_file)


def bar_height(value, top):
    """A bar's CSS height, as a share of the tallest bar (no decimal comma: CSS reads it)."""
    return '%d%%' % round(100.0 * value / top)


def main():
    facts = sf.FactSheet()
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        carry_base, carry_amended = pool.map(carry, [BASE, AMENDED])
    carry_source = 'carry_report, linhas "all" (blocos de 500 episódios), runs/%s'

    facts.add('cre01.quedas_base', carry_base['drop_share'],
              sf.fmt_percent_range(*carry_base['drop_share']), carry_source % BASE)
    facts.add('cre01.quedas_cre', carry_amended['drop_share'],
              sf.fmt_percent_range(*carry_amended['drop_share']), carry_source % AMENDED)
    facts.add('cre01.transp_base', carry_base['transports_per_100'],
              sf.fmt_number_range(*carry_base['transports_per_100']), carry_source % BASE)
    facts.add('cre01.transp_cre', carry_amended['transports_per_100'],
              sf.fmt_number_range(*carry_amended['transports_per_100']), carry_source % AMENDED)
    facts.add('cre01.pegas_base', carry_base['grasps'],
              '~' + sf.fmt_number(round(carry_base['grasps'], -2)), carry_source % BASE)
    facts.add('cre01.quedas_por_abrir_base', carry_base['by_open_share'],
              sf.fmt_percent_range(*carry_base['by_open_share']), carry_source % BASE)
    facts.add('cre01.sorteio_forcado', carry_base['open_new_share'],
              sf.fmt_percent_range(*carry_base['open_new_share']),
              carry_source % BASE + ', coluna "open new"')

    rows = {batch: sf.ledger_row(batch) for batch in (BASE, NO_AMENDMENT, AMENDED)}
    seeds = {int(row['n']) for row in rows.values()}
    if len(seeds) != 1:
        raise SystemExit('the three batches have different seed counts: %s' % seeds)
    facts.add('cre01.n_seeds', seeds.pop(), str(int(rows[BASE]['n'])), 'bench/ledger.csv, coluna n')
    m2 = {}
    first = {}
    for key, batch in (('base', BASE), ('sem_emenda', NO_AMENDMENT), ('cre', AMENDED)):
        row = rows[batch]
        m2[key] = row['m2_final']
        first[key] = int(row['n'] - row['censored'])
        facts.add('cre01.m2_' + key, m2[key], sf.fmt_percent(m2[key], 1),
                  'bench/ledger.csv, %s (commit %s), coluna m2_final' % (batch, row['commit']))
        facts.add('cre01.primeiro_' + key, first[key], str(first[key]),
                  'bench/ledger.csv, %s, n − censored' % batch)
    for key in m2:
        facts.add('cre01.altura_m2_' + key, None, bar_height(m2[key], max(m2.values())),
                  'altura da barra: cre01.m2_%s sobre a maior' % key)
        facts.add('cre01.altura_primeiro_' + key, None,
                  bar_height(first[key], max(first.values())),
                  'altura da barra: cre01.primeiro_%s sobre a maior' % key)
    p = sf.primary_p(BASE, AMENDED)
    facts.add('cre01.p_m2', p, sf.fmt_number(p, 2),
              'bench.py compare %s %s, Mann–Whitney da M2 final' % (BASE, AMENDED))

    with open(os.path.join(sf.run_path(BASE), 's1', 'run.json')) as run_file:
        phase2 = json.load(run_file)['eref']
    facts.add('cre01.fase2', phase2, str(phase2), 'runs/%s/s1/run.json, eref' % BASE)
    facts.add('cre01.janela_m2', sf.bench.FINAL, str(sf.bench.FINAL), 'tools/bench.py, FINAL')

    stage_video = sidecar(STAGE_VIDEO)
    if 'release' in stage_video['fired'] or stage_video['drop'] is not None:
        raise SystemExit('the caption says the cube is held to the end, but episode %d released '
                         'or dropped it' % stage_video['episode'])
    facts.add('cre01.video_ep', stage_video['episode'], 'ep. %d' % stage_video['episode'],
              'media/cre01_s1.mp4.json (midia.sh)')
    facts.add('cre01.video_regra', stage_video['rule'], stage_video['rule'],
              'media/cre01_s1.mp4.json (midia.sh)')
    facts.add('cre01.video_vel', stage_video['stride'], '%d×' % stage_video['stride'],
              'media/cre01_s1.mp4.json (midia.sh), stride')
    facts.add('cre01.video_passo_pad', stage_video['fired']['transport'],
              str(stage_video['fired']['transport']),
              'media/cre01_s1.mp4.json (midia.sh), passo em que a etapa transport disparou')
    strip = sidecar(STRIP_VIDEO)
    facts.add('cre01.tira_ep', strip['episode'], 'ep. %d' % strip['episode'],
              'media/base_s1.mp4.json (midia.sh), regra: %s' % strip['rule'])

    spec = 'spec CRE-01 (vault Rafael/Specs)'
    facts.add_manual('cre01.prev_quedas', '95% → bem menos', spec + ', previsões')
    facts.add_manual('cre01.prev_transp', '2 → mais', spec + ', previsões ("2,2 → mais")')
    facts.add_manual('cre01.prev_m2', '1,1% → maior', spec + ', previsões ("0,011 → maior")')
    facts.add_manual('cre01.n0', '2', 'commit eca83f5, Config.contextPriorWeight (padrão 2)')
    facts.add_manual('cre01.custo_soltar_caminho', '−0,06 a −0,27', spec + ', Parte 1, tabela')
    facts.add_manual('cre01.custo_soltar_pad', '≤ −0,20', spec + ', Parte 1, tabela')
    facts.add_manual('cre01.paga_sucesso', '+0,20', spec + ', Parte 1, tabela')
    facts.add_manual('cre01.carregam_s1_s5', '30–50', 'code_notes entrada 40, "Carregar não basta"')
    facts.add_manual('cre01.fase2_comeca', '6–14%', 'code_notes entrada 40, "A Fase 2 esquece"')
    facts.write(os.path.join(HERE, 'fatos.json'), 'python3 slides/mudancas/2026-10-27-cre-01/fatos.py')
    for key, fact in facts.facts.items():
        print('%-30s %s' % (key, fact['texto']))


if __name__ == '__main__':
    main()
