"""Review, build, capture, send and archive the weekly slides (vault spec APR-01).

    python3 tools/slides.py review slides/mudancas/<data>-<id> [--no-open]
    python3 tools/slides.py build slides/reunioes/<data>.qmd
    python3 tools/slides.py capture <deck.html> <folder>
    python3 tools/slides.py send slides/reunioes/<data>.qmd [--max-video-mb N]
    python3 tools/slides.py archive slides/reunioes/<data>.qmd

review renders one change's slides alone (slides/revisao/<id>.qmd (no leading _: Quarto leaves _ folders out of the project, and their decks lose the fato extension) includes them) and opens them in
Firefox; build renders a meeting. send zips the meeting for the advisor without the presenter notes
(they are rehearsal) and, past --max-video-mb, without the heavy videos; archive zips it with the
notes into the vault's Meetings folder. Both zips hold only what the deck references, not the whole
output folder, which also keeps the reviews and the other meetings.

Firefox is a snap here: it reads only $HOME, and not the hidden folders at its top (~/.cache), so
everything Rafael opens stays where it can (assert_openable).
"""
import argparse
import html.parser
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SLIDES = os.path.join(REPO, 'slides')
OUTPUT = os.path.join(SLIDES, '_saida')
VAULT_MEETINGS = os.path.expanduser('~/Documentos/Obsidian/Mestrado/Rafael/Meetings')
CAPTURE_PROFILE = os.path.expanduser('~/snap/firefox/common/slides-capture')
VIDEO_EXTENSIONS = ('.mp4', '.webm', '.mov')


def review_wrapper(change_dir):
    """The text of slides/revisao/<id>.qmd (no leading _: Quarto leaves _ folders out of the project, and their decks lose the fato extension): one change's slides and facts, alone. pagetitle, not
    title, so Quarto makes no title slide."""
    change_id = os.path.basename(os.path.normpath(change_dir))
    return ('---\n'
            'pagetitle: "Revisão: %s"\n'
            'fatos: [../mudancas/%s/fatos.json]\n'
            '---\n\n'
            '{{< include ../mudancas/%s/slides.qmd >}}\n') % (change_id, change_id, change_id)


def render(qmd_path):
    """quarto render, from the project root; the HTML path. RuntimeError with Quarto's stderr if it
    fails (a missing or repeated fact key fails here, naming the key)."""
    relative = os.path.relpath(os.path.abspath(qmd_path), SLIDES)
    process = subprocess.run(['quarto', 'render', relative], cwd=SLIDES, capture_output=True,
                             text=True)
    if process.returncode != 0:
        raise RuntimeError('quarto render %s failed:\n%s' % (relative, process.stderr[-4000:]))
    for line in process.stderr.splitlines():
        if 'WARN' in line:
            print(line, file=sys.stderr)
    html_path = os.path.join(OUTPUT, os.path.splitext(relative)[0] + '.html')
    if not os.path.isfile(html_path):
        raise RuntimeError('quarto render %s wrote no %s' % (relative, html_path))
    return html_path


def assert_openable(path):
    """ValueError unless the snap Firefox can open path: inside $HOME, not under /tmp, not in a
    hidden folder at the top of $HOME."""
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser('~'))
    if real == '/tmp' or real.startswith('/tmp/'):
        raise ValueError('%s is under /tmp, which the snap Firefox cannot read' % path)
    if not real.startswith(home + os.sep):
        raise ValueError('%s is outside $HOME, which the snap Firefox cannot read' % path)
    if os.path.relpath(real, home).split(os.sep)[0].startswith('.'):
        raise ValueError('%s is in a hidden folder at the top of $HOME, which the snap Firefox '
                         'cannot read' % path)


# --- the deck's structure --------------------------------------------------------------------
class SlideFinder(html.parser.HTMLParser):
    """The reveal.js hash of every slide: '#/h' for a top-level section, '#/h/v' for the sections
    of a vertical stack; and which slides have fragments. Only div and section are tracked for
    nesting, as Quarto always closes them."""

    def __init__(self):
        super().__init__()
        self.stack = []                         # 'div', 'section', 'slides' (the div.slides)
        self.hashes = []
        self.with_fragments = set()             # indices into hashes
        self.top_index = -1
        self.nested_index = -1

    def depth_in_slides(self):
        return len(self.stack) - self.stack.index('slides') if 'slides' in self.stack else None

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get('class') or '').split()
        if 'fragment' in classes and self.hashes and self.depth_in_slides():
            self.with_fragments.add(len(self.hashes) - 1)
        if tag not in ('div', 'section'):
            return
        if tag == 'div' and 'slides' in classes and 'slides' not in self.stack:
            self.stack.append('slides')
            return
        depth = self.depth_in_slides()
        if tag == 'section' and depth == 1:
            self.top_index += 1
            self.nested_index = -1
            self.hashes.append('#/%d' % self.top_index)
        elif tag == 'section' and depth == 2 and self.stack[-1] == 'section':
            if self.nested_index == -1:
                self.hashes.pop()               # a stack: its slides are the nested sections
            self.nested_index += 1
            self.hashes.append('#/%d/%d' % (self.top_index, self.nested_index))
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ('div', 'section') and self.stack:
            self.stack.pop()


def slide_hashes(html_text):
    finder = SlideFinder()
    finder.feed(html_text)
    return finder.hashes


def slide_count(html_text):
    return len(slide_hashes(html_text))


def slides_with_fragments(html_text):
    """The hashes of the slides that have fragments (clicks)."""
    finder = SlideFinder()
    finder.feed(html_text)
    return [finder.hashes[i] for i in sorted(finder.with_fragments)]


def all_fragments_hash(slide_hash):
    """The hash that opens a slide with every fragment shown (needs fragment-in-url)."""
    return slide_hash + ('/99' if slide_hash.count('/') == 2 else '/0/99')


def capture(html_path, out_dir):
    """One 1280×720 PNG per slide (slideNN.png), from a headless Firefox with its own profile; a
    slide with fragments also gets slideNN_cliques.png, every fragment shown."""
    assert_openable(html_path)
    assert_openable(out_dir)
    os.makedirs(CAPTURE_PROFILE, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(html_path, encoding='utf-8') as deck:
        text = deck.read()
    shots = []
    with_fragments = set(slides_with_fragments(text))
    for number, slide_hash in enumerate(slide_hashes(text), 1):
        shots.append(('slide%02d.png' % number, slide_hash))
        if slide_hash in with_fragments:
            shots.append(('slide%02d_cliques.png' % number, all_fragments_hash(slide_hash)))
    uri = pathlib.Path(os.path.abspath(html_path)).as_uri()
    written = []
    for name, slide_hash in shots:
        png = os.path.join(out_dir, name)
        if os.path.exists(png):
            os.remove(png)
        subprocess.run(['firefox', '--headless', '--no-remote', '--profile', CAPTURE_PROFILE,
                        '--screenshot', png, '--window-size=1280,720', uri + slide_hash],
                       capture_output=True, timeout=120)
        if not os.path.isfile(png):
            raise RuntimeError('Firefox wrote no screenshot of %s%s' % (html_path, slide_hash))
        written.append(png)
    return written


# --- notes and what a deck needs -------------------------------------------------------------
NOTES_OPEN = re.compile(r'<aside\b[^>]*\bclass="(?:[^"]*\s)?notes(?:\s[^"]*)?"[^>]*>')
ASIDE_TAG = re.compile(r'<aside\b[^>]*>|</aside\s*>')


def strip_notes(html_text):
    """The HTML without any <aside class="notes">…</aside>, nested asides included."""
    kept, position = [], 0
    while True:
        opening = NOTES_OPEN.search(html_text, position)
        if opening is None:
            kept.append(html_text[position:])
            return ''.join(kept)
        kept.append(html_text[position:opening.start()])
        depth, scan = 1, opening.end()
        while depth:
            tag = ASIDE_TAG.search(html_text, scan)
            if tag is None:
                raise ValueError('a notes aside opened at %d never closes' % opening.start())
            depth += -1 if tag.group().startswith('</') else 1
            scan = tag.end()
        position = scan


REFERENCE = re.compile(r'''(?:\b(?:src|href|data-src|poster)\s*=\s*"([^"]+)")'''
                       r'''|(?:url\(\s*['"]?([^'")]+)['"]?\s*\))''')


def local_references(text, base_dir, root):
    """Files under root that text references (src, href, data-src, poster, url()), resolved from
    base_dir; links to the web, data URIs and anchors are skipped."""
    found = set()
    for match in REFERENCE.finditer(text):
        reference = match.group(1) or match.group(2)
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', reference) or reference.startswith(('#', '//')):
            continue
        reference = urllib.parse.unquote(reference.split('#')[0].split('?')[0])
        if not reference:
            continue
        path = os.path.normpath(os.path.join(base_dir, reference))
        if os.path.isfile(path) and path.startswith(os.path.abspath(root) + os.sep):
            found.add(os.path.relpath(path, root))
    return found


def deck_files(html_path, root=OUTPUT):
    """Every file one deck needs, relative to the output root: the HTML, its <name>_files folder,
    and what the HTML and the CSS in that folder reference (media, fonts)."""
    html_path = os.path.abspath(html_path)
    root = os.path.abspath(root)
    files = {os.path.relpath(html_path, root)}
    with open(html_path, encoding='utf-8') as deck:
        files |= local_references(deck.read(), os.path.dirname(html_path), root)
    support = os.path.splitext(html_path)[0] + '_files'
    for folder, _, names in os.walk(support):
        for name in names:
            path = os.path.join(folder, name)
            files.add(os.path.relpath(path, root))
            if name.endswith('.css'):
                with open(path, encoding='utf-8', errors='replace') as sheet:
                    files |= local_references(sheet.read(), folder, root)
    return sorted(files)


def all_files(root):
    return sorted(os.path.relpath(os.path.join(folder, name), root)
                  for folder, _, names in os.walk(root) for name in names)


VIDEO_ELEMENT = re.compile(r'<video\b.*?</video\s*>', re.DOTALL)


def without_videos(html_text, dropped):
    """Each <video> that plays a dropped file becomes a line saying it was left out, and why."""
    def replace(match):
        for name, megabytes in dropped.items():
            if os.path.basename(name) in match.group(0):
                return ('<p class="hint">vídeo fora desta versão, por tamanho (%.0f MB): %s</p>'
                        % (megabytes, os.path.basename(name)))
        return match.group(0)
    return VIDEO_ELEMENT.sub(replace, html_text)


def write_zip(root, zip_path, files, html_transform=None):
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    partial = zip_path + '.part'
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            path = os.path.join(root, name)
            if name.endswith('.html') and html_transform is not None:
                with open(path, encoding='utf-8') as page:
                    archive.writestr(name, html_transform(page.read()))
            else:
                archive.write(path, name)
    os.replace(partial, zip_path)
    return zip_path


def send_version(out_dir, zip_path, max_video_mb=None, files=None):
    """The zip for the advisor: files (default: all of out_dir) with every notes aside stripped
    and, past max_video_mb, the heavier videos left out and their slides saying so."""
    files = all_files(out_dir) if files is None else list(files)
    dropped = {}
    if max_video_mb is not None:
        for name in files:
            size_mb = os.path.getsize(os.path.join(out_dir, name)) / 1e6
            if name.lower().endswith(VIDEO_EXTENSIONS) and size_mb > max_video_mb:
                dropped[name] = size_mb
    kept = [name for name in files if name not in dropped]
    for name, size_mb in dropped.items():
        print('left out (%.0f MB > %s MB): %s' % (size_mb, max_video_mb, name))
    return write_zip(out_dir, zip_path, kept,
                     lambda text: without_videos(strip_notes(text), dropped))


def archive(out_dir, meeting_date, meetings_dir=VAULT_MEETINGS, files=None):
    """The meeting as presented, notes included, zipped into the vault: '<date> apresentação.zip'."""
    files = all_files(out_dir) if files is None else list(files)
    return write_zip(out_dir, os.path.join(meetings_dir, '%s apresentação.zip' % meeting_date), files)


# --- commands ---------------------------------------------------------------------------------
def review(change_dir, open_browser=True):
    change_id = os.path.basename(os.path.normpath(change_dir))
    wrapper = os.path.join(SLIDES, 'revisao', change_id + '.qmd')
    os.makedirs(os.path.dirname(wrapper), exist_ok=True)
    with open(wrapper, 'w', encoding='utf-8') as out:
        out.write(review_wrapper(change_dir))
    html_path = render(wrapper)
    assert_openable(html_path)
    with open(html_path, encoding='utf-8') as deck:
        print('%s: %d slides' % (html_path, slide_count(deck.read())))
    if open_browser:
        subprocess.Popen(['firefox', html_path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    return html_path


def meeting_date(meeting_qmd):
    return os.path.splitext(os.path.basename(meeting_qmd))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('review', help="render one change's slides alone and open them")
    one.add_argument('change_dir')
    one.add_argument('--no-open', action='store_true')
    commands.add_parser('build', help='render a meeting').add_argument('meeting')
    shot = commands.add_parser('capture', help='one PNG per slide')
    shot.add_argument('html')
    shot.add_argument('out_dir')
    send = commands.add_parser('send', help='zip without notes for the advisor')
    send.add_argument('meeting')
    send.add_argument('--max-video-mb', type=float)
    commands.add_parser('archive', help='zip with notes into the vault').add_argument('meeting')
    args = parser.parse_args()

    if args.command == 'review':
        review(args.change_dir, open_browser=not args.no_open)
    elif args.command == 'capture':
        for png in capture(args.html, args.out_dir):
            print(png)
    else:
        html_path = render(args.meeting)
        files = deck_files(html_path)
        with open(html_path, encoding='utf-8') as deck:
            print('%s: %d slides, %d files' % (html_path, slide_count(deck.read()), len(files)))
        if args.command == 'send':
            print(send_version(OUTPUT, os.path.join(VAULT_MEETINGS, '%s para enviar.zip'
                                                    % meeting_date(args.meeting)),
                               args.max_video_mb, files))
        elif args.command == 'archive':
            print(archive(OUTPUT, meeting_date(args.meeting), files=files))


if __name__ == '__main__':
    main()
