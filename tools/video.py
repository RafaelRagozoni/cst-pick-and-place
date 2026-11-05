"""Captioned replay videos and frame strips from a run log, rendered headless (vault spec APR-01).

    python3 tools/video.py episode runs/<batch>/s1 --rule last-with-stage:transport --stride 2 \\
        --title "CRE-01 emendado · seed 1" --out media/cre01.mp4 \\
        [--stills grasp-40,grasp+4,drop-12,drop+40 --stills-prefix media/base]
    python3 tools/video.py learning runs/<batch>/s1 --every 100 --stride 4 --out media/learn.mp4 \\
        [--epilogue first-success] [--estimate]

A replay, not a re-run: each frame puts the arm, the cube and the fingers where the log says they
were (replay.py's FRAME_LUA), seen by an offscreen vision sensor, so no window and no physics. The
caption says so, with the speed (the stride: 20 frames/s of every Nth step is N× real time) and the
rule that chose the episode (episode_pick.py). Two known approximations of the replay, the cube's
fixed yaw and the fingers posed from a table, are why the caption says "replay do log".

Stills take a step number or an anchor: a stage (reach, grasp, transport, release: the step it
fired), `drop` (the cube let go away from the pad) or `last` (the terminal record), with an
optional +k or -k. The script that makes a change's media then holds no step numbers of its own.
"""
import argparse
import bisect
import functools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENV = os.path.join(REPO, 'coppelia_environment')
sys.path.insert(0, HERE)
sys.path.insert(0, ENV)
import episode_pick                             # noqa: E402
import runlog                                   # noqa: E402
from episode_pick import STAGE_WORDS            # noqa: E402
from slide_facts import fmt_percent             # noqa: E402

CAMERA = {'eye': (1.40, -1.31, 1.70), 'at': (0.0, -0.02, 1.03), 'size': (1280, 720), 'fov_deg': 45}
SCENE = os.path.join(ENV, 'pick_and_place.ttt')
FPS = 20
STILL_CROP = (120, 70, 1240, 700)
LEARNING_BLOCK = 100                            # episodes per bar of the learning video's chart

FONT_FILE = '/usr/share/fonts/opentype/inter/Inter-%s.otf'

# dataviz reference palette, dark steps: the overlays sit on a dark panel
SURFACE = (26, 26, 25, 235)
INK = (240, 239, 236, 255)
MUTED = (195, 194, 183, 255)
BAR = (57, 135, 229, 255)
NOT_YET = (88, 88, 84, 255)                     # bars of blocks the video has not reached
DONE = (46, 160, 67, 255)
NOW = (232, 170, 40, 255)
EDGE = (120, 128, 140, 255)
SUCCESS_INK = (120, 220, 140, 255)
WEDGE_FILL = (198, 198, 203)

RESULTS = ['não chegou ao cubo', 'chegou ao cubo, não pegou', 'pegou o cubo, não o levou ao pad',
           'levou o cubo ao pad, não soltou lá', 'sucesso']


@functools.lru_cache(maxsize=None)
def font(weight, size):
    return ImageFont.truetype(FONT_FILE % weight, size)


def title_font():
    return font('SemiBold', 24)


def body_font():
    return font('Regular', 19)


def chip_font():
    return font('SemiBold', 16)


def small_font():
    return font('Regular', 15)


def tiny_font():
    return font('Regular', 13)


# --- rendering from the log ------------------------------------------------------------------
def look_at(eye, at, up=(0, 0, 1)):
    """The 12-number object matrix of a camera at `eye` looking at `at`."""
    z = [a - e for a, e in zip(at, eye)]
    norm = math.sqrt(sum(v * v for v in z))
    z = [v / norm for v in z]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    norm = math.sqrt(sum(v * v for v in x))
    x = [v / norm for v in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [x[0], y[0], z[0], eye[0], x[1], y[1], z[1], eye[1], x[2], y[2], z[2], eye[2]]


def first_firings(records):
    """{stage: the step it first fired} over every record of the episode."""
    fired = {}
    for record in records:
        if record.get('goal_fired'):
            fired.setdefault(record['goal_fired'], record['step'])
    return fired


def render_frames(jobs, out_dir):
    """jobs: [(records of one episode, terminal last; stride)]. Writes out_dir/ep<NNNN>/f<XXXX>.png
    (every stride-th step, then the terminal record) and meta.json; one scene load for all jobs.
    Returns the episode folders, in the order of the jobs."""
    import replay
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from grasp_rule import GraspRule
    from simprocess import SimProcess
    width, height = CAMERA['size']
    folders = []
    with SimProcess(gui=False) as process:
        sim = RemoteAPIClient(port=process.rpc_port).require('sim')
        sim.loadScene(SCENE)
        ur5 = sim.getObject('/UR5')
        arm = [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
               if 'RG2' not in sim.getObjectAlias(j, 2)][:6]
        cube = sim.getObject('/Cube')
        gripper_base = sim.getObject('/UR5/RG2')
        finger_shapes = sorted(sim.getObjectsInTree(gripper_base, sim.sceneobject_shape, 1),
                               key=lambda h: len(sim.getObjectAlias(h, 2).split('/')))
        widths, finger_poses = replay.calibrate_fingers(sim, GraspRule(sim), gripper_base,
                                                        finger_shapes)
        script = sim.createScript(sim.scripttype_customization, replay.FRAME_LUA, 0, 'lua')
        sim.initScript(script)
        camera = sim.createVisionSensor(2, [width, height, 0, 0],
                                        [0.01, 25.0, math.radians(CAMERA['fov_deg']), 0.1,
                                         0, 0, 0, 0, 0, 0, 0])
        sim.setExplicitHandling(camera, 1)
        sim.setObjectMatrix(camera, look_at(CAMERA['eye'], CAMERA['at']), -1)

        for records, stride in jobs:
            terminal = records[-1]
            summary = terminal.get('episode_summary') or {}
            steps = [r for r in records if not r.get('done')]
            episode = terminal['episode']
            name = 'ep%04d' % episode
            if os.path.isdir(os.path.join(out_dir, name)):
                name += '_stride%d' % stride
            folder = os.path.join(out_dir, name)
            os.makedirs(folder)
            yaw = replay.yaw_quat(summary.get('cube_start', [0, 0, 0])[2])
            frames = []
            for index, record in enumerate(steps[::stride] + [terminal]):
                observation = record['obs']
                joints = [j['pos'] for j in observation['innerSense']['joints']]
                k = min(bisect.bisect_left(widths, observation['innerSense']['gripper']['width']),
                        len(widths) - 1)
                error = sim.callScriptFunction('frame', script, arm, joints, cube,
                                               list(observation['vision']['cube']['pos']) + yaw,
                                               finger_shapes, finger_poses[k], gripper_base, '')
                if error:
                    raise RuntimeError(error)
                sim.handleVisionSensor(camera)
                pixels, resolution = sim.getVisionSensorImg(camera)
                Image.frombytes('RGB', (resolution[0], resolution[1]), bytes(pixels)).transpose(
                    Image.Transpose.FLIP_TOP_BOTTOM).save(os.path.join(folder, 'f%04d.png' % index))
                is_terminal = bool(record.get('done'))
                frames.append({'step': record['step'],
                               'habit': None if is_terminal else record.get('habit_id'),
                               'stage': ('done' if is_terminal and summary.get('success')
                                         else record.get('goal_step')),
                               'holding': observation['innerSense']['gripper']['isHolding']})
            meta = {'episode': episode, 'stride': stride, 'n_steps': len(steps), 'summary': summary,
                    'fired': first_firings(records),
                    'drop': episode_pick.drop_away_step(records), 'frames': frames}
            with open(os.path.join(folder, 'meta.json'), 'w') as meta_file:
                json.dump(meta, meta_file)
            print('episode %d: %d frames (stride %d), stages %s, success %s' % (
                episode, len(frames), stride, list(meta['fired']), summary.get('success')),
                flush=True)
            folders.append(folder)
    return folders


def load_meta(episode_dir):
    with open(os.path.join(episode_dir, 'meta.json')) as meta_file:
        return json.load(meta_file)


def frame_image(episode_dir, index):
    return clean_top_wedges(Image.open(os.path.join(episode_dir, 'f%04d.png' % index)).convert('RGB'))


# --- drawing ---------------------------------------------------------------------------------
def clean_top_wedges(image):
    """Paint the dark wedges the vision sensor leaves in the top rows the floor colour."""
    pixels = np.array(image)
    top = pixels[:32]
    top[top.astype(int).sum(2) < 60] = WEDGE_FILL
    return Image.fromarray(pixels)


def stage_chip_states(fired, step, current_stage):
    """[(label, state)] for the four stages in order: 'feito' (label with the step it fired),
    'agora' (the stage being worked on) or 'falta'."""
    states = []
    for stage, words in STAGE_WORDS.items():
        at = fired.get(stage)
        if at is not None and step >= at:
            states.append(('%s · %d' % (words, at), 'feito'))
        elif current_stage == stage:
            states.append((words, 'agora'))
        else:
            states.append((words, 'falta'))
    return states


def caption_text(rule, speed):
    return 'replay do log, sem física · %d× tempo real · %s' % (speed, rule)


def chip_widths(draw, chips):
    return [draw.textlength(label, font=chip_font()) + 26 for label, _ in chips]


def draw_chips(draw, x, y, chips):
    for i, ((label, state), width) in enumerate(zip(chips, chip_widths(draw, chips))):
        box = (x, y, x + width, y + 30)
        if state == 'feito':
            draw.rounded_rectangle(box, 15, fill=DONE)
            draw.text((x + 13, y + 6), label, font=chip_font(), fill=INK)
        elif state == 'agora':
            draw.rounded_rectangle(box, 15, outline=NOW, width=2)
            draw.text((x + 13, y + 6), label, font=chip_font(), fill=NOW)
        else:
            draw.rounded_rectangle(box, 15, outline=EDGE, width=1)
            draw.text((x + 13, y + 6), label, font=chip_font(), fill=MUTED)
        x += width
        if i < len(chips) - 1:
            draw.text((x + 6, y + 3), '›', font=chip_font(), fill=MUTED)
            x += 22


def draw_episode_panel(draw, title, line, line_color, chips):
    """The top-left panel: title, one line of state, the stage chips; as wide as its content."""
    content = max(draw.textlength(title, font=title_font()), draw.textlength(line, font=body_font()),
                  sum(chip_widths(draw, chips)) + 22 * (len(chips) - 1))
    draw.rounded_rectangle((20, 20, 20 + 40 + content, 170), 14, fill=SURFACE)
    draw.text((40, 34), title, font=title_font(), fill=INK)
    draw.text((40, 72), line, font=body_font(), fill=line_color)
    draw_chips(draw, 40, 116, chips)


def draw_caption(draw, text):
    """Bottom-right caption (y 676–704); a text too wide for one line goes on two, the second one
    in that band."""
    width_limit = CAMERA['size'][0] - 60
    lines = [text]
    if draw.textlength(text, font=small_font()) > width_limit and ' · ' in text:
        head, _, tail = text.rpartition(' · ')
        lines = [head, tail]
    for row, line in enumerate(reversed(lines)):
        top = 676 - 32 * row
        width = draw.textlength(line, font=small_font())
        draw.rounded_rectangle((1260 - width - 24, top, 1260, top + 28), 10, fill=(26, 26, 25, 170))
        draw.text((1260 - width - 12, top + 5), line, font=small_font(), fill=MUTED)


def state_line(frame, n_steps):
    holding = '  ·  cubo na garra' if frame['holding'] else ''
    return 'passo %d / %d  ·  hábito %s%s' % (frame['step'], n_steps, frame['habit'] or '—', holding)


def episode_overlay(image, frame, meta, title, rule, speed):
    """One video frame: the episode panel (title; step, habit, cube in the gripper; the stages)
    and the caption with the replay, the speed and the rule."""
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw_episode_panel(draw, title, state_line(frame, meta['n_steps']), MUTED,
                       stage_chip_states(meta['fired'], frame['step'], frame['stage']))
    draw_caption(draw, caption_text(rule, speed))
    return Image.alpha_composite(base, layer).convert('RGB')


def result_text(fired):
    reached = 0
    for stage in STAGE_WORDS:
        if stage not in fired:
            break
        reached += 1
    return RESULTS[reached]


def card(image, lines):
    """A centred card over a frame: [(text, font, line height)]; the first two lines in ink."""
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    height = 40 + sum(line_height for _, _, line_height in lines)
    width = max(draw.textlength(text, font=f) for text, f, _ in lines) + 80
    width = max(width, 800)
    centre_x, top = CAMERA['size'][0] / 2, CAMERA['size'][1] / 2 - height / 2
    draw.rounded_rectangle((centre_x - width / 2, top - 10, centre_x + width / 2, top + height), 18,
                           fill=SURFACE)
    y = top + 14
    for i, (text, f, line_height) in enumerate(lines):
        draw.text((centre_x - draw.textlength(text, font=f) / 2, y), text, font=f,
                  fill=INK if i < 2 else MUTED)
        y += line_height
    return Image.alpha_composite(base, layer).convert('RGB')


# --- output ----------------------------------------------------------------------------------
def encode_mp4(frames, out_path, fps=FPS, hold_last_s=2.0):
    """Encode PIL frames (any iterable) to H.264 MP4, the last one held hold_last_s seconds.
    Returns the number of frames written."""
    import imageio_ffmpeg
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    width, height = CAMERA['size']
    encoder = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo',
         '-pix_fmt', 'rgb24', '-s', '%dx%d' % (width, height), '-r', str(fps), '-i', '-',
         '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', out_path], stdin=subprocess.PIPE)
    last, count = None, 0
    try:
        for frame in frames:
            if frame.size != (width, height):
                raise ValueError('frame %d is %s, the video is %dx%d' % (count, frame.size, width,
                                                                         height))
            last = frame.tobytes()
            encoder.stdin.write(last)
            count += 1
        if last is None:
            raise ValueError('no frames to encode for %s' % out_path)
        for _ in range(int(round(hold_last_s * fps))):
            encoder.stdin.write(last)
            count += 1
    finally:
        encoder.stdin.close()
        code = encoder.wait()
    if code != 0:
        raise RuntimeError('ffmpeg exited %d writing %s' % (code, out_path))
    return count


def crop_still(image):
    return image.crop(STILL_CROP)


def nearest_frame_index(meta, step):
    return min(range(len(meta['frames'])), key=lambda i: (abs(meta['frames'][i]['step'] - step), i))


def write_stills(episode_dir, steps, out_paths):
    """For each step, the frame nearest to it, cropped, as JPEG (quality 88); no overlay."""
    meta = load_meta(episode_dir)
    for step, path in zip(steps, out_paths):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        crop_still(frame_image(episode_dir, nearest_frame_index(meta, step))).save(path, quality=88)


def resolve_still_step(spec, meta):
    """'104' -> 104; 'grasp-40' -> 40 steps before grasp fired; 'drop+40'; 'last'."""
    spec = spec.strip()
    if spec.lstrip('-').isdigit():
        return int(spec)
    anchor, offset = spec, 0
    for sign in ('+', '-'):
        if sign in spec:
            anchor, _, amount = spec.partition(sign)
            offset = int(amount) * (1 if sign == '+' else -1)
            break
    if anchor in STAGE_WORDS:
        if anchor not in meta['fired']:
            raise LookupError("still %r: the stage '%s' never fired in episode %d" % (
                spec, anchor, meta['episode']))
        at = meta['fired'][anchor]
    elif anchor == 'drop':
        if meta.get('drop') is None:
            raise LookupError('still %r: the cube is never let go away from the pad in episode %d'
                              % (spec, meta['episode']))
        at = meta['drop']
    elif anchor == 'last':
        at = meta['frames'][-1]['step']
    else:
        raise ValueError('still %r: a step number or one of %s, drop, last, with +k or -k' % (
            spec, ', '.join(STAGE_WORDS)))
    return at + offset


# --- the learning video ----------------------------------------------------------------------
def learning_blocks(summaries, size=LEARNING_BLOCK):
    """Per block of `size` episodes: start, end, n, % of episodes that grasped, % successes."""
    blocks = []
    last = max(s['episode'] for s in summaries)
    for start in range(0, last + 1, size):
        block = [s for s in summaries if start <= s['episode'] < start + size]
        if not block:
            continue
        blocks.append({'start': start, 'end': start + len(block) - 1, 'n': len(block),
                       'grasp': 100.0 * sum('grasp' in s['goals'] for s in block) / len(block),
                       'success': 100.0 * sum(bool(s['success']) for s in block) / len(block)})
    return blocks


def success_axis_top(blocks):
    """The top of the success axis: the highest block rounded up to the next even %, at least 2."""
    return max(2, 2 * math.ceil(max(b['success'] for b in blocks) / 2))


def block_index(blocks, episode):
    return next(i for i, b in enumerate(blocks) if b['start'] <= episode <= b['end'])


def percent_label(value):
    return fmt_percent(value / 100.0)


def draw_mini_bars(draw, x0, y0, width, title, key, top, blocks, current):
    """One bar per block, shown up to the current one; the current one labelled."""
    draw.text((x0, y0), title, font=small_font(), fill=MUTED)
    gap = 2
    bar_width = (width - gap * (len(blocks) - 1)) / len(blocks)
    base, height = y0 + 64, 40
    draw.line((x0, base, x0 + width, base), fill=(110, 110, 104, 255), width=1)
    for i, block in enumerate(blocks):
        x = x0 + i * (bar_width + gap)
        if i > current:
            draw.rectangle((x, base - 2, x + bar_width, base), fill=NOT_YET)
            continue
        value = block[key]
        bar_height = max(2, round(height * value / top)) if value > 0 else 0
        if bar_height:
            draw.rounded_rectangle((x, base - bar_height, x + bar_width, base), 4, fill=BAR,
                                   corners=(True, True, False, False))
        if i == current:
            label = percent_label(value)
            label_width = draw.textlength(label, font=tiny_font())
            draw.text((x + bar_width / 2 - label_width / 2, base - bar_height - 17), label,
                      font=tiny_font(), fill=INK)
            draw.polygon([(x + bar_width / 2 - 5, base + 9), (x + bar_width / 2 + 5, base + 9),
                          (x + bar_width / 2, base + 3)], fill=INK)
    return base, bar_width


def draw_chart_panel(draw, blocks, current, note):
    left, inner = 812, 832
    width = 1260 - 20 - inner
    draw.rounded_rectangle((left, 20, 1260, 266), 14, fill=SURFACE)
    block = blocks[current]
    draw.text((inner, 32), 'Bloco %d–%d (%d episódios)' % (block['start'], block['end'], block['n']),
              font=font('Medium', 21), fill=INK)
    draw.text((inner, 60), note, font=tiny_font(), fill=MUTED)
    draw_mini_bars(draw, inner, 84, width, 'pegou o cubo · % dos episódios, eixo 0–100%', 'grasp',
                   100, blocks, current)
    top = success_axis_top(blocks)
    base, bar_width = draw_mini_bars(draw, inner, 160, width,
                                     'sucesso · %% dos episódios, eixo 0–%d%%' % top, 'success', top,
                                     blocks, current)
    every_label = max(1, math.ceil(len(blocks) / 5))
    for i in range(0, len(blocks), every_label):
        x = inner + i * (bar_width + 2) + bar_width / 2
        text = str(blocks[i]['start'])
        draw.text((x - draw.textlength(text, font=tiny_font()) / 2, base + 10), text,
                  font=tiny_font(), fill=MUTED)


def learning_frame(image, meta, frame, title, blocks, current, note, rule, show_result=False):
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if show_result:
        result = result_text(meta['fired'])
        line, color = 'resultado: ' + result, SUCCESS_INK if result == RESULTS[-1] else NOW
    else:
        line, color = state_line(frame, meta['n_steps']), MUTED
    draw_episode_panel(draw, title, line, color,
                       stage_chip_states(meta['fired'], frame['step'], frame['stage']))
    draw_chart_panel(draw, blocks, current, note)
    draw_caption(draw, caption_text(rule, meta['stride']))
    return Image.alpha_composite(base, layer).convert('RGB')


def seed_words(label):
    return 'seed ' + label.lstrip('s')


def learning_seconds(summaries, picks, stride, epilogue=None, epilogue_stride=None):
    """How long learning_video's MP4 will run, from the summaries alone (nothing rendered)."""
    by_episode = {s['episode']: s for s in summaries}
    frames = 4.0 * FPS
    for pick in picks:
        frames += math.ceil(by_episode[pick.episode]['steps'] / stride) + 1 + 1.5 * FPS
    if epilogue is not None:
        frames += 3.0 * FPS + math.ceil(by_episode[epilogue.episode]['steps'] /
                                        (epilogue_stride or stride)) + 1 + 1.5 * FPS + 5.0 * FPS
    return frames / FPS


def learning_video(run_dir, picks, stride, out_path, epilogue=None, epilogue_stride=None,
                   title='Como o agente aprende', cache_dir=episode_pick.DEFAULT_CACHE_DIR):
    """One episode per pick, each beside the rates of the whole block it belongs to, then an
    optional epilogue (e.g. the first success), marked as outside the sample, and a closing card
    with what came after it. Every number is computed from the log and run.json. Writes out_path
    and out_path + '.json' (seed, rule, episodes, stride, epilogue, seconds)."""
    (label, log, run_meta), = runlog.find_logs([run_dir])
    summaries = episode_pick.episode_summaries(log, cache_dir)
    blocks = learning_blocks(summaries)
    epilogue_stride = epilogue_stride or stride
    wanted = {pick.episode for pick in picks} | ({epilogue.episode} if epilogue else set())
    records = episode_pick.extract_episodes(log, wanted)
    work = tempfile.mkdtemp(prefix='quadros_', dir=os.path.dirname(os.path.abspath(out_path)))
    try:
        jobs = [(records[pick.episode], stride) for pick in picks]
        if epilogue is not None:
            jobs.append((records[epilogue.episode], epilogue_stride))
        folders = render_frames(jobs, work)
        sample_rule = picks[0].rule

        def frames():
            first_dir = folders[0]
            sampled = ', '.join(str(p.episode) for p in picks[:3]) + ', …, %d' % picks[-1].episode
            yield from [card(frame_image(first_dir, 0), [
                (title, font('Bold', 40), 58),
                ('%s · %s: %s' % (seed_words(label), sample_rule, sampled), font('Medium', 21), 34),
                ('ao lado, as taxas do bloco de %d episódios a que o episódio pertence'
                 % LEARNING_BLOCK, body_font(), 28),
                ('replay do log, sem física · %d× tempo real' % stride, small_font(), 22)])
            ] * int(4.0 * FPS)
            for pick, folder in zip(picks, folders):
                meta = load_meta(folder)
                current = block_index(blocks, pick.episode)
                heading = 'Episódio %d de %d · %s' % (pick.episode, len(summaries), seed_words(label))
                note = 'o bloco inteiro, não só o episódio do vídeo'
                for index, frame in enumerate(meta['frames']):
                    yield learning_frame(frame_image(folder, index), meta, frame, heading, blocks,
                                         current, note, sample_rule)
                yield from [learning_frame(frame_image(folder, len(meta['frames']) - 1), meta,
                                           meta['frames'][-1], heading, blocks, current, note,
                                           sample_rule, show_result=True)] * int(1.5 * FPS)
            if epilogue is None:
                return
            folder = folders[-1]
            meta = load_meta(folder)
            yield from [card(frame_image(folder, 0), [
                ('Fora da amostra: %s' % epilogue.rule.replace(' deste seed', ''), font('Bold', 40),
                 58),
                ('episódio %d · %s' % (epilogue.episode, seed_words(label)), font('Medium', 21), 34),
                ('%d× tempo real' % epilogue_stride, small_font(), 22)])] * int(3.0 * FPS)
            current = block_index(blocks, epilogue.episode)
            heading = 'Episódio %d · %s' % (epilogue.episode, epilogue.rule.replace('deste seed',
                                                                                     'do ' + seed_words(label)))
            note = 'fora da amostra: ' + sample_rule
            for index, frame in enumerate(meta['frames']):
                yield learning_frame(frame_image(folder, index), meta, frame, heading, blocks,
                                     current, note, epilogue.rule)
            last_image = frame_image(folder, len(meta['frames']) - 1)
            yield from [learning_frame(last_image, meta, meta['frames'][-1], heading, blocks, current,
                                       note, epilogue.rule, show_result=True)] * int(1.5 * FPS)
            phase2 = run_meta['eref']
            after = [s for s in summaries
                     if epilogue.episode < s['episode'] <= epilogue.episode + phase2]
            wins = sum(bool(s['success']) for s in after)
            yield from [card(last_image, [
                ('Depois do episódio %d' % epilogue.episode, font('Bold', 40), 58),
                ('nos %d episódios seguintes: %d sucessos (%s)' % (
                    len(after), wins, fmt_percent(wins / len(after), 1) if after else '—'),
                 font('Medium', 21), 34),
                ('a Fase 2 da bateria são os %d episódios depois do 1º sucesso' % phase2,
                 body_font(), 28)])] * int(5.0 * FPS)

        count = encode_mp4(frames(), out_path, hold_last_s=0)
    finally:
        shutil.rmtree(work)
    info = {'seed': label, 'rule': picks[0].rule, 'episodes': [p.episode for p in picks],
            'stride': stride, 'n_episodes': len(summaries), 'seconds': count / FPS,
            'epilogue': None if epilogue is None else {
                'episode': epilogue.episode, 'rule': epilogue.rule, 'stride': epilogue_stride}}
    with open(out_path + '.json', 'w') as info_file:
        json.dump(info, info_file, ensure_ascii=False, indent=1)
    print('wrote %s: %d frames, %.1f s' % (out_path, count, count / FPS))
    return info


# --- the episode video -----------------------------------------------------------------------
def episode_video(run_dir, rule_spec, stride, title, out_path, stills=(), stills_prefix=None,
                  cache_dir=episode_pick.DEFAULT_CACHE_DIR):
    """The captioned replay of the one episode a rule picks, plus stills by step or anchor; the
    title gets " · episódio N" appended, so a media script types no episode number. Writes out_path and out_path + '.json' (episode, seed, rule, stride, seconds, stills)."""
    (label, log, _), = runlog.find_logs([run_dir])
    picks = episode_pick.picks_for_rule(log, rule_spec, cache_dir)
    if len(picks) != 1:
        raise ValueError('rule %r picks %d episodes; an episode video needs exactly one'
                         % (rule_spec, len(picks)))
    pick = picks[0]
    records = episode_pick.extract_episodes(log, {pick.episode})[pick.episode]
    work = tempfile.mkdtemp(prefix='quadros_', dir=os.path.dirname(os.path.abspath(out_path)))
    try:
        folder, = render_frames([(records, stride)], work)
        meta = load_meta(folder)
        shown_title = '%s · episódio %d' % (title, pick.episode)
        frames = (episode_overlay(frame_image(folder, i), frame, meta, shown_title, pick.rule,
                                  stride) for i, frame in enumerate(meta['frames']))
        count = encode_mp4(frames, out_path)
        written = []
        if stills:
            prefix = stills_prefix or os.path.splitext(out_path)[0]
            steps = [resolve_still_step(spec, meta) for spec in stills]
            paths = ['%s_%d.jpg' % (prefix, i + 1) for i in range(len(steps))]
            write_stills(folder, steps, paths)
            written = [{'spec': spec, 'step': meta['frames'][nearest_frame_index(meta, step)]['step'],
                        'path': os.path.relpath(path, os.path.dirname(os.path.abspath(out_path)))}
                       for spec, step, path in zip(stills, steps, paths)]
    finally:
        shutil.rmtree(work)
    info = {'episode': pick.episode, 'seed': label, 'rule': pick.rule, 'stride': stride,
            'seconds': count / FPS, 'fired': meta['fired'], 'drop': meta['drop'], 'stills': written}
    with open(out_path + '.json', 'w') as info_file:
        json.dump(info, info_file, ensure_ascii=False, indent=1)
    print('wrote %s: episode %d of %s, %.1f s; %s' % (out_path, pick.episode, label, count / FPS,
                                                      pick.rule))
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('episode', help='the captioned replay of one episode, plus stills')
    one.add_argument('run_dir')
    one.add_argument('--rule', required=True, help=' | '.join(episode_pick.RULE_NAMES))
    one.add_argument('--stride', type=int, default=2)
    one.add_argument('--title', required=True)
    one.add_argument('--out', required=True)
    one.add_argument('--stills', default='', help='comma-separated steps or anchors (grasp-40, '
                     'drop+40, last, ...)')
    one.add_argument('--stills-prefix')
    learn = commands.add_parser('learning', help='one episode every N beside its block\'s rates')
    learn.add_argument('run_dir')
    learn.add_argument('--every', type=int, required=True)
    learn.add_argument('--stride', type=int, default=4)
    learn.add_argument('--out', required=True)
    learn.add_argument('--epilogue', choices=['first-success'])
    learn.add_argument('--epilogue-stride', type=int)
    learn.add_argument('--title', default='Como o agente aprende')
    learn.add_argument('--estimate', action='store_true',
                       help='print how long the video will run, render nothing')
    for sub in (one, learn):
        sub.add_argument('--cache', default=episode_pick.DEFAULT_CACHE_DIR)
    args = parser.parse_args()
    if args.command == 'episode':
        episode_video(args.run_dir, args.rule, args.stride, args.title, args.out,
                      [s for s in args.stills.split(',') if s], args.stills_prefix, args.cache)
        return
    (_, log, _), = runlog.find_logs([args.run_dir])
    summaries = episode_pick.episode_summaries(log, args.cache)
    picks = episode_pick.every(summaries, args.every)
    epilogue = episode_pick.first_success(summaries) if args.epilogue else None
    seconds = learning_seconds(summaries, picks, args.stride, epilogue, args.epilogue_stride)
    print('%d episodes (%s) at stride %d%s: %.1f s' % (
        len(picks), picks[0].rule, args.stride,
        ', epilogue episode %d' % epilogue.episode if epilogue else '', seconds))
    if not args.estimate:
        learning_video(args.run_dir, picks, args.stride, args.out, epilogue, args.epilogue_stride,
                       args.title, args.cache)


if __name__ == '__main__':
    main()
