"""Offline checks of video.py: overlays, stage chips, the MP4 encoder, stills and still anchors,
with synthetic frames and no simulator (vault spec APR-01).

    python3 tools/test_video.py
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video                                        # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def raises_with(exception_type, text, function, *args):
    try:
        function(*args)
    except exception_type as error:
        return text in str(error)
    return False


def gray_frame(level=200):
    return Image.new('RGB', video.CAMERA['size'], (level, level, level))


def main():
    print('stage chips')
    check('done, done, now, todo', video.stage_chip_states({'reach': 85, 'grasp': 104}, 120,
                                                           'transport') ==
          [('chegar ao cubo · 85', 'feito'), ('pegar · 104', 'feito'), ('levar ao pad', 'agora'),
           ('soltar no pad', 'falta')])
    check('a stage fired later is not done yet', video.stage_chip_states({'reach': 85}, 50, 'reach')
          == [('chegar ao cubo', 'agora'), ('pegar', 'falta'), ('levar ao pad', 'falta'),
              ('soltar no pad', 'falta')])

    print('top wedges')
    image = gray_frame()
    image.putpixel((0, 0), (0, 0, 0))
    image.putpixel((0, 40), (0, 0, 0))
    cleaned = video.clean_top_wedges(image)
    check('black pixel in the top 32 rows painted', cleaned.getpixel((0, 0)) == (198, 198, 203))
    check('black pixel below row 32 kept', cleaned.getpixel((0, 40)) == (0, 0, 0))

    print('overlay')
    frame = {'step': 120, 'habit': 'move_x+', 'stage': 'transport', 'holding': True}
    meta = {'episode': 7, 'stride': 2, 'n_steps': 500, 'fired': {'reach': 85, 'grasp': 104},
            'summary': {}, 'frames': [frame]}
    plain = gray_frame()
    shown = video.episode_overlay(plain, frame, meta, 'CRE-01 emendado · seed 1',
                                  'o 1º sucesso deste seed', 2)
    before, after = np.asarray(plain), np.asarray(shown)
    check('caption band (y 676–704) is drawn', (before[676:705] != after[676:705]).any())
    check('top-right corner untouched', (before[0:200, 1080:] == after[0:200, 1080:]).all())
    check('overlay keeps the size', shown.size == video.CAMERA['size'])
    check('caption names the replay, the speed and the rule',
          video.caption_text('o 1º sucesso deste seed', 2) ==
          'replay do log, sem física · 2× tempo real · o 1º sucesso deste seed')

    temporary = tempfile.mkdtemp(prefix='video_', dir=os.path.expanduser('~'))
    try:
        print('encoder')
        out = os.path.join(temporary, 'x.mp4')
        video.encode_mp4([gray_frame(20 * i) for i in range(10)], out, fps=20, hold_last_s=0.5)
        import imageio_ffmpeg
        check('10 frames + 0,5 s held at 20 fps -> 20 frames, 1 s',
              imageio_ffmpeg.count_frames_and_secs(out) == (20, 1.0))

        print('stills')
        episode_dir = os.path.join(temporary, 'ep0007')
        os.makedirs(episode_dir)
        frames_meta = []
        for index, step in enumerate((0, 4, 8, 12)):
            gray_frame(10 + 60 * index).save(os.path.join(episode_dir, 'f%04d.png' % index))
            frames_meta.append({'step': step, 'habit': 'h', 'stage': 'reach', 'holding': False})
        with open(os.path.join(episode_dir, 'meta.json'), 'w') as meta_file:
            json.dump({'episode': 7, 'stride': 4, 'n_steps': 13, 'summary': {}, 'drop': 9,
                       'fired': {'reach': 5}, 'frames': frames_meta}, meta_file)
        outs = [os.path.join(temporary, name) for name in ('a.jpg', 'b.jpg')]
        video.write_stills(episode_dir, [5, 11], outs)
        first, second = (Image.open(path) for path in outs)
        check('stills cropped to 1120 × 630', first.size == (1120, 630))
        check('nearest frame: step 5 -> the frame of step 4',
              abs(first.getpixel((500, 300))[0] - 70) <= 3)
        check('nearest frame: step 11 -> the frame of step 12',
              abs(second.getpixel((500, 300))[0] - 190) <= 3)

        print('still anchors')
        with open(os.path.join(episode_dir, 'meta.json')) as meta_file:
            meta = json.load(meta_file)
        check('plain step', video.resolve_still_step('8', meta) == 8)
        check('stage anchor with offset', video.resolve_still_step('reach-4', meta) == 1)
        check('drop anchor', video.resolve_still_step('drop+40', meta) == 49)
        check('last anchor is the terminal step', video.resolve_still_step('last', meta) == 12)
        check('stage that never fired raises', raises_with(LookupError, 'grasp',
                                                           video.resolve_still_step, 'grasp', meta))

        print('learning blocks')
        summaries = [{'episode': e, 'steps': 500, 'goals': ['reach', 'grasp'] if e % 2 else [],
                      'success': e in (150, 151), 'energy': 1.0} for e in range(250)]
        blocks = video.learning_blocks(summaries, 100)
        check('three blocks, the last one short', [(b['start'], b['end'], b['n']) for b in blocks]
              == [(0, 99, 100), (100, 199, 100), (200, 249, 50)])
        check('grasp and success rates per block', (blocks[1]['grasp'], blocks[1]['success']) ==
              (50.0, 2.0))
        check('success axis: next even number up, at least 2', video.success_axis_top(blocks) == 2
              and video.success_axis_top([{'success': 4.1}]) == 6)

        print('learning frame and card')
        meta = {'episode': 150, 'stride': 4, 'n_steps': 500, 'fired': {'reach': 85},
                'summary': {}, 'frames': [frame]}
        plain = gray_frame()
        drawn = np.asarray(video.learning_frame(plain, meta, frame, 'Episódio 150 de 250 · seed 1',
                                                blocks, 1, 'o bloco inteiro', 'um episódio a cada 100'))
        check('learning frame draws the chart panel (top right)',
              (np.asarray(plain)[20:266, 812:1260] != drawn[20:266, 812:1260]).any())
        result = np.asarray(video.learning_frame(plain, meta, frame, 'x', blocks, 1, 'n', 'r',
                                                 show_result=True))
        check('result line differs from the state line', (result[60:110] != drawn[60:110]).any())
        check('result text counts the stages in order',
              video.result_text({'reach': 1, 'transport': 9}) == 'chegou ao cubo, não pegou'
              and video.result_text(dict.fromkeys(video.STAGE_WORDS, 1)) == 'sucesso')
        shown = video.card(plain, [('Título', video.font('Bold', 40), 58),
                                   ('linha', video.body_font(), 28)])
        check('card is drawn in the centre', (np.asarray(shown)[340:380, 600:680] !=
                                              np.asarray(plain)[340:380, 600:680]).any())
    finally:
        shutil.rmtree(temporary)
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
