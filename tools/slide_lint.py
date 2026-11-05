"""Warn about numbers typed into slides (vault spec APR-01, rule 4: a number reaches a slide only
through {{< fato key >}}, which reads the change's fatos.json).

    python3 tools/slide_lint.py slides/reunioes/<data>.qmd | slides/mudancas/<id>/slides.qmd

Follows {{< include >}} (paths from the project root, slides/). Not flagged: identifiers (CRE-01,
WP2, s1, j0, macro_reach_8, M2), seeds, episodes and entries named by number, commit hashes,
dates, years in citations, chapter and part numbers, "a cada 100" as a unit, the 1° primitive,
the numbering of components, front matter, header attributes ({.prob fonte="..."}), image
targets, HTML attributes, SVG and code blocks. A line with "<!-- número digitado: <reason> -->"
is skipped: the reason stays in the source, where a reviewer sees it.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDES = os.path.join(os.path.dirname(HERE), 'slides')
ON_PURPOSE = 'número digitado:'

REMOVE_FIRST = [
    re.compile(r'\{\{<.*?>\}\}'),                       # shortcodes (fato, include)
    re.compile(r'<!--.*?-->'),
    re.compile(r'<b class="k">\s*\d+\s*</b>'),          # numbered cause badges
    re.compile(r'\[\d+\]\{\.n\}'),                      # numbered strip captions
    re.compile(r'<[^>]+>'),                             # HTML tags and their attributes
    re.compile(r'\]\([^)]*\)'),                         # image and link targets
    re.compile(r'\{[^{}]*\}'),                          # pandoc attributes
]
IDENTIFIERS = [
    re.compile(r'\b[A-Z]{2,4}-\d+\b'),                  # CRE-01, MAC-01, APR-01
    re.compile(r'\bseeds? \d+(?:\s*(?:,|e)\s*\d+)*\b'),
    re.compile(r'\beps?\. \d+(?:\s*(?:,|e)\s*\d+)*\b'),
    re.compile(r'\bepisódios? \d+\b'),
    re.compile(r'\bentradas? \d+(?:\s*(?:,|e|a)\s*\d+)*\b'),
    re.compile(r'\b[0-9a-f]*[a-f][0-9a-f]*\b'),         # filtered by length below
    re.compile(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b'),    # dates
    re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
    re.compile(r'(?<=[A-Za-z.)&] )(?:19|20)\d{2}\b'),   # years in citations: ICLR 2024, al. 1997
    re.compile(r'\bcap\. \d+(?:\.\d+)*\b'),
    re.compile(r'\b[Pp]artes? \d+\b'),
    re.compile(r'\bslides? \d+\b'),
    re.compile(r'\bcausa \d+\b'),
    re.compile(r'\bFases? \d+\b'),                     # Fase 1, Fase 2: names, not measures
    re.compile(r'\bFila \d+\b'),
    re.compile(r'\bblocos? de 100\b'),
    re.compile(r'\b(?:por|a cada) 100\b'),
    re.compile(r'\b1°'),
    re.compile(r'\bPR #\d+\b'),
]
NUMBER = re.compile(r'(?<![\w])[−-]?\d+(?:[.,]\d+)*(?:\s*[–-]\s*\d+(?:[.,]\d+)*)?%?(?![\w])')


def strip_line(text):
    for pattern in REMOVE_FIRST:
        text = pattern.sub(' ', text)
    for pattern in IDENTIFIERS:
        if pattern.pattern.startswith(r'\b[0-9a-f]'):
            text = pattern.sub(lambda m: ' ' if len(m.group()) >= 7 and re.search(r'\d', m.group())
                               else m.group(), text)
        else:
            text = pattern.sub(' ', text)
    return text


def find_typed_numbers(qmd_text):
    """[(line number, the number as typed)] in the slide text and the notes."""
    found = []
    in_front_matter = in_code = in_svg = False
    for number, line in enumerate(qmd_text.split('\n'), 1):
        stripped = line.strip()
        if number == 1 and stripped == '---':
            in_front_matter = True
            continue
        if in_front_matter:
            in_front_matter = stripped != '---'
            continue
        if stripped.startswith('```'):
            in_code = not in_code
            continue
        if in_code or ON_PURPOSE in line:
            continue
        text = line
        if in_svg:
            if '</svg>' not in text:
                continue
            text = text.split('</svg>', 1)[1]
            in_svg = False
        text = re.sub(r'<svg\b.*?</svg>', ' ', text)
        if '<svg' in text:
            text = text.split('<svg', 1)[0]
            in_svg = True
        for match in NUMBER.finditer(strip_line(text)):
            found.append((number, match.group().strip()))
    return found


INCLUDE = re.compile(r'\{\{<\s*include\s+(\S+)\s*>\}\}')


def lint(qmd_path, root=SLIDES, seen=None):
    """[(file, line number, number)] for qmd_path and every file it includes."""
    seen = set() if seen is None else seen
    path = os.path.abspath(qmd_path)
    if path in seen:
        return []
    seen.add(path)
    with open(path, encoding='utf-8') as source:
        text = source.read()
    warnings = [(path, line, snippet) for line, snippet in find_typed_numbers(text)]
    for target in INCLUDE.findall(text):
        included = (os.path.join(root, target.lstrip('/')) if target.startswith('/')
                    else os.path.join(os.path.dirname(path), target))
        warnings += lint(included, root, seen)
    return warnings


def format_warnings(warnings, root=SLIDES):
    return ['%s:%d: número digitado: %s' % (os.path.relpath(path, root), line, snippet)
            for path, line, snippet in warnings]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('qmd', nargs='+')
    args = parser.parse_args()
    seen = set()
    warnings = [w for qmd in args.qmd for w in lint(qmd, seen=seen)]
    for line in format_warnings(warnings):
        print(line)
    print('%d warning(s)' % len(warnings), file=sys.stderr)


if __name__ == '__main__':
    main()
