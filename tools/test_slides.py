"""Offline checks of slides.py: the review wrapper, notes stripping, the $HOME rule, the slide count,
what goes into the zip to send and the vault archive (vault spec APR-01).

    python3 tools/test_slides.py
"""
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slides                                       # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def raises(exception_type, function, *args):
    try:
        function(*args)
    except exception_type:
        return True
    return False


NOTES_HTML = '''<html><body><div class="reveal"><div class="slides">
<section id="a" class="slide level2 ctx"><h2>Um</h2>
<aside class="notes"><p>pergunta: por que <em>isso</em>?</p><ul><li>item</li></ul></aside>
</section>
<section id="b" class="slide level2 sol"><h2>Dois</h2>
<aside class="outro">fica</aside>
<aside class="notes">segunda nota</aside>
<video src="../mudancas/x/media/longo.mp4" controls></video>
<img src="../mudancas/x/media/curta.jpg">
</section>
</div></div>
<style>@font-face { src: url("../tema/fontes/Inter-Regular.otf"); }</style>
<script src="deck_files/libs/reveal.js"></script>
</body></html>'''


def write(path, content, mode='w'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as out:
        out.write(content)


def main():
    print('review wrapper')
    wrapper = slides.review_wrapper('/x/slides/mudancas/2026-10-27-cre-01')
    check('includes the change slides', '{{< include ../mudancas/2026-10-27-cre-01/slides.qmd >}}'
          in wrapper)
    check('reads the change facts', 'fatos: [../mudancas/2026-10-27-cre-01/fatos.json]' in wrapper)
    check('names the change in the page title, without a title slide',
          'pagetitle: "Revisão: 2026-10-27-cre-01"' in wrapper and '\ntitle:' not in wrapper)

    print('notes')
    stripped = slides.strip_notes(NOTES_HTML)
    check('both notes asides removed', 'class="notes"' not in stripped and 'pergunta' not in stripped
          and 'segunda nota' not in stripped)
    check('other asides and the slides kept', '<aside class="outro">fica</aside>' in stripped
          and '<h2>Dois</h2>' in stripped)
    check('notes with a nested aside removed whole', slides.strip_notes(
        'a<aside class="notes">x<aside class="q">y</aside>z</aside>b') == 'ab')

    print('openable')
    check('/tmp refused', raises(ValueError, slides.assert_openable, '/tmp/x.html'))
    check('outside $HOME refused', raises(ValueError, slides.assert_openable, '/srv/x.html'))
    check('hidden folder at the top of $HOME refused (the snap cannot read it)',
          raises(ValueError, slides.assert_openable, os.path.expanduser('~/.cache/x.html')))
    check('inside $HOME accepted', not raises(ValueError, slides.assert_openable,
                                              os.path.expanduser('~/x.html')))

    print('slide count')
    check('two top-level slides', slides.slide_count(NOTES_HTML) == 2)

    temporary = tempfile.mkdtemp(prefix='slides_', dir=os.path.expanduser('~'))
    try:
        out = os.path.join(temporary, '_saida')
        deck = os.path.join(out, 'reunioes', '2026-11-11.html')
        write(deck, NOTES_HTML.replace('deck_files', '2026-11-11_files'))
        write(os.path.join(out, 'reunioes', '2026-11-11_files', 'libs', 'reveal.js'), 'js')
        write(os.path.join(out, 'mudancas', 'x', 'media', 'longo.mp4'), b'\0' * 3_000_000, 'wb')
        write(os.path.join(out, 'mudancas', 'x', 'media', 'curta.jpg'), b'jpg', 'wb')
        write(os.path.join(out, 'tema', 'fontes', 'Inter-Regular.otf'), b'otf', 'wb')
        write(os.path.join(out, 'reunioes', 'outra.html'), '<aside class="notes">n</aside>')
        write(os.path.join(out, '_revisao', 'x.html'), 'revisao')

        print('deck files')
        files = slides.deck_files(deck, out)
        check('the deck, its _files, its media and the fonts', files == sorted([
            'reunioes/2026-11-11.html', 'reunioes/2026-11-11_files/libs/reveal.js',
            'mudancas/x/media/longo.mp4', 'mudancas/x/media/curta.jpg',
            'tema/fontes/Inter-Regular.otf']))

        print('send')
        zip_path = os.path.join(temporary, 'para enviar.zip')
        slides.send_version(out, zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            htmls = [archive.read(n).decode() for n in names if n.endswith('.html')]
        check('send strips every notes aside', len(htmls) == 3 and not any('class="notes"' in h
                                                                          for h in htmls))
        slides.send_version(out, zip_path, max_video_mb=2, files=files)
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            deck_text = archive.read('reunioes/2026-11-11.html').decode()
        check('only the deck files go', sorted(names) == sorted(f for f in files
                                                                if not f.endswith('longo.mp4')))
        check('a video over the limit leaves and its slide says so',
              '<video' not in deck_text and 'longo.mp4' in deck_text and 'curta.jpg' in deck_text)

        print('archive')
        meetings = os.path.join(temporary, 'Meetings')
        archived = slides.archive(out, '2026-11-11', meetings_dir=meetings, files=files)
        check('archive named "<date> apresentação.zip"',
              archived == os.path.join(meetings, '2026-11-11 apresentação.zip')
              and os.path.isfile(archived))
        with zipfile.ZipFile(archived) as archive:
            check('the archive keeps the notes',
                  'class="notes"' in archive.read('reunioes/2026-11-11.html').decode())
    finally:
        shutil.rmtree(temporary)
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
