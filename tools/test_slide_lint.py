"""Offline checks of slide_lint.py: numbers typed into slides are found, identifiers are not
(vault spec APR-01, rule 4: no typed number).

    python3 tools/test_slide_lint.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slide_lint                                   # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def found(text):
    return [snippet for _, snippet in slide_lint.find_typed_numbers(text)]


def main():
    print('typed numbers')
    check('"0,011 de M2" is flagged', found('a M2 foi 0,011 de M2') == ['0,011'])
    check('a number through fato is not', found('a M2 foi {{< fato cre01.m2_base >}}') == [])
    check('identifiers, hashes and dates are not',
          found('seed 1, ep. 1998, CRE-01, WP2, commit 2ac8e29, 03/11') == [])
    check('a number in the notes is flagged', found('::: notes\nCaiu 87% das vezes.\n:::') == ['87%'])
    check('a range is flagged once', found('quedas de 93–97%') == ['93–97%'])
    check('the line number is reported', slide_lint.find_typed_numbers('x\n\ny 12 z')[0][0] == 3)

    print('what is skipped')
    check('front matter, header attributes and image targets',
          found('---\nfatos: [a1/f.json]\n---\n## Título {.prob fonte="entrada 34 · ep. 400"}\n'
                '![legenda](/m/base_1.jpg){fig-alt="x 3"}') == [])
    check('SVG and HTML attributes', found('<svg viewBox="0 0 200 64"><text x="7">v1</text></svg>\n'
                                           '<div style="height:18%">texto</div>') == [])
    check('component numbering', found('<b class="k">1</b> e ![[2]{.n}pega](a.jpg)') == [])
    check('citations, chapters, entries, units',
          found('DrS (ICLR 2024) · Konidaris & Barto 2009 · cap. 4 · entradas 40 a 42 · '
                'entrada 31 · 8 vezes a cada 100 episódios · seeds 1 e 3 · passos de 1° · PR #2')
          == ['8'])
    check('a line marked as typed on purpose is skipped',
          found('fila de 4 etapas <!-- número digitado: a tarefa tem 4 etapas -->') == [])
    check('code blocks are skipped', found('```\nx = 42\n```') == [])
    check('names with numbers: Fase 2, Fila 7', found('a Fase 2 esquece · Fila 7') == [])

    print('includes')
    temporary = tempfile.mkdtemp(prefix='slide_lint_')
    try:
        os.makedirs(os.path.join(temporary, 'mudancas', 'x'))
        os.makedirs(os.path.join(temporary, 'reunioes'))
        with open(os.path.join(temporary, 'mudancas', 'x', '_01-a.qmd'), 'w') as part:
            part.write('## A\n\nsubiu 5%\n')
        with open(os.path.join(temporary, 'mudancas', 'x', 'slides.qmd'), 'w') as part:
            part.write('{{< include /mudancas/x/_01-a.qmd >}}\n')
        meeting = os.path.join(temporary, 'reunioes', 'r.qmd')
        with open(meeting, 'w') as part:
            part.write('## R\n\n{{< include /mudancas/x/slides.qmd >}}\n')
        warnings = slide_lint.lint(meeting, root=temporary)
        check('follows includes from the project root', [(os.path.basename(p), n, s)
                                                          for p, n, s in warnings]
              == [('_01-a.qmd', 3, '5%')])
    finally:
        shutil.rmtree(temporary)
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
