"""Renders the Quarto test deck and checks the `fato` shortcode (vault spec APR-01).

Each check copies slides/ to a temporary directory and runs `quarto render` there, so the repo's
slides/_saida stays clean. Needs Quarto 1.10.19 on PATH; no Jupyter (the shortcode is pure Lua).

    python3 tools/test_slides_render.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SLIDES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'slides')
FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def render(workdir, qmd):
    """quarto render <qmd> inside workdir (a copy of slides/); returns the CompletedProcess."""
    return subprocess.run(['quarto', 'render', qmd], cwd=workdir, capture_output=True, text=True)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def main():
    if shutil.which('quarto') is None:
        print('FAIL: quarto not on PATH; install Quarto 1.10.19 (https://quarto.org)')
        return 1
    tmp = tempfile.mkdtemp(prefix='slides_render_', dir=os.path.expanduser('~'))
    try:
        work = os.path.join(tmp, 'slides')
        shutil.copytree(SLIDES, work, ignore=shutil.ignore_patterns('_saida', '_cache', '.quarto'))

        r = render(work, 'teste/exemplo.qmd')
        html_path = os.path.join(work, '_saida', 'teste', 'exemplo.html')
        html = read(html_path) if os.path.exists(html_path) else ''
        incluido = read(os.path.join(work, 'teste', '_incluido.qmd'))
        slide_text = re.search(r'^## (.+?)\s*(\{|$)', incluido, re.M)
        check('renders example', r.returncode == 0 and '1,1%' in html
              and bool(slide_text) and slide_text.group(1) in html)

        src = re.search(r'src="([^"]*pixel\.png)"', html)
        ok = False
        if src:
            ok = os.path.exists(os.path.normpath(os.path.join(os.path.dirname(html_path), src.group(1))))
        check('included slide image resolves', ok)

        exemplo = read(os.path.join(work, 'teste', 'exemplo.qmd'))
        with open(os.path.join(work, 'teste', 'exemplo.qmd'), 'w', encoding='utf-8') as f:
            f.write(exemplo + '\n## Falta\n\n{{< fato teste.nao_existe >}}\n')
        r = render(work, 'teste/exemplo.qmd')
        check('missing key fails render', r.returncode != 0 and 'teste.nao_existe' in r.stderr)

        with open(os.path.join(work, 'teste', 'exemplo.qmd'), 'w', encoding='utf-8') as f:
            f.write(exemplo)
        dup = {'gerado_por': 'test', 'fatos': {'teste.m2': {'valor': 0, 'texto': '0%', 'fonte': 'x', 'manual': True}}}
        with open(os.path.join(work, 'teste', 'fatos_duplicado.json'), 'w', encoding='utf-8') as f:
            json.dump(dup, f)
        with open(os.path.join(work, 'teste', 'exemplo.qmd'), 'w', encoding='utf-8') as f:
            f.write(exemplo.replace('  - fatos.json', '  - fatos.json\n  - fatos_duplicado.json', 1))
        r = render(work, 'teste/exemplo.qmd')
        check('duplicate key fails render', r.returncode != 0 and 'teste.m2' in r.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\nslides render: %s' % ('PASS' if not FAILS else 'FAIL (%d)' % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
