"""Offline checks of episode_pick.py on a fake log whose answers are known (vault spec APR-01).

    python3 tools/test_episode_pick.py
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import episode_pick as ep_pick                      # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-64s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def raises_with(exception_type, text, function, *args):
    """True if function(*args) raises exception_type with `text` in its message."""
    try:
        function(*args)
    except exception_type as error:
        return text in str(error)
    return False


ALL_STAGES = ['reach', 'grasp', 'transport', 'release']


def observation(holding, cube_to_pad_xy=0.2):
    return {'innerSense': {'gripper': {'isHolding': holding}},
            'derived': {'cubeToPadXY': cube_to_pad_xy}}


def episode_records(episode, goals, energy, release_at=None):
    """Step records of one episode, then its terminal record. release_at = None: the cube is never
    held; otherwise it is grasped at step 1 and let go at step 2 at that distance from the pad."""
    if release_at is None:
        held_and_distance = [(False, 0.2)] * 3
    else:
        held_and_distance = [(False, 0.2), (True, 0.2), (False, release_at)]
    records = [{'episode': episode, 'step': step, 'obs': observation(held, distance),
                'habit_id': 'h%d' % step, 'done': False}
               for step, (held, distance) in enumerate(held_and_distance)]
    records.append({'episode': episode, 'step': len(records), 'obs': observation(False), 'done': True,
                    'episode_summary': {'steps': 3 + episode, 'success': 'release' in goals,
                                        'jointEnergy': energy, 'goalsReached': goals}})
    return records


# episode: (goals, energy, release_at). Successes at 2 (lowest energy, but the 1st), 4 and 6;
# the cube is let go away from the pad at 3 and 7, next to it (0,02 m) at 5; transport last at 8.
FAKE_EPISODES = {
    0: ([], 5.0, None),
    1: (['reach'], 5.0, None),
    2: (ALL_STAGES, 1.0, None),
    3: (['reach', 'grasp'], 5.0, 0.2),
    4: (ALL_STAGES, 3.0, None),
    5: (['reach', 'grasp'], 5.0, 0.02),
    6: (ALL_STAGES, 2.0, None),
    7: (['reach', 'grasp'], 5.0, 0.3),
    8: (['reach', 'grasp', 'transport'], 5.0, None),
    9: (['reach'], 5.0, None),
}


def write_log(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, 'wt') as log_file:
        for line in lines:
            log_file.write(line + '\n')


def fake_log_lines(episodes=FAKE_EPISODES):
    return [json.dumps(record) for episode, (goals, energy, release_at) in sorted(episodes.items())
            for record in episode_records(episode, goals, energy, release_at)]


def main():
    temporary = tempfile.mkdtemp(prefix='episode_pick_')
    try:
        log = os.path.join(temporary, 'batch', 's1', 'log.jsonl.gz')
        write_log(log, fake_log_lines())
        summaries = ep_pick.episode_summaries(log)

        print('summaries')
        check('one summary per finished episode', [s['episode'] for s in summaries] == list(range(10)))
        check('summary fields', summaries[2] == {'episode': 2, 'steps': 5, 'success': True,
                                                 'goals': ALL_STAGES, 'energy': 1.0})

        print('rules')
        check('every 4 -> 0, 4, 8', [p.episode for p in ep_pick.every(summaries, 4)] == [0, 4, 8])
        check('every: rule text', ep_pick.every(summaries, 4)[0].rule == 'um episódio a cada 4')
        check('first_success -> 2', ep_pick.first_success(summaries)
              == ep_pick.Pick(2, 'o 1º sucesso deste seed'))
        last_transport = ep_pick.last_with_stage(summaries, 'transport')
        check('last_with_stage transport -> 8', last_transport.episode == 8)
        check('last_with_stage: rule names the stage in Portuguese',
              last_transport.rule == "o último episódio deste seed que chegou a 'levar ao pad'")
        check('min_energy_success skips the 1st success -> 6',
              ep_pick.min_energy_success(summaries)
              == ep_pick.Pick(6, 'o sucesso de menor energia depois do 1º acerto'))
        drop = ep_pick.first_drop_away(log, 5)
        check('first_drop_away from 5 -> 7 (5 lets go next to the pad)', drop.episode == 7)
        check('first_drop_away: rule text', drop.rule == 'o 1º episódio a partir do 5 em que o cubo '
              'é pego e largado longe do pad')
        check('first_drop_away from 0 -> 3', ep_pick.first_drop_away(log, 0).episode == 3)

        print('no match raises')
        failures_only = [s for s in summaries if not s['success']]
        check('rule with no match raises (names the rule)',
              raises_with(LookupError, 'soltar no pad', ep_pick.last_with_stage, failures_only,
                          'release'))
        check('min_energy_success with a single success raises',
              raises_with(LookupError, 'menor energia', ep_pick.min_energy_success,
                          [s for s in summaries if s['episode'] < 4]))
        check('first_success with none raises', raises_with(LookupError, '1º sucesso',
                                                            ep_pick.first_success, failures_only))
        check('first_drop_away with none raises', raises_with(LookupError, 'a partir do 8',
                                                              ep_pick.first_drop_away, log, 8))
        check('unknown stage raises ValueError', raises_with(ValueError, 'lift',
                                                             ep_pick.last_with_stage, summaries,
                                                             'lift'))

        print('batch')
        second_seed = {e: v for e, v in FAKE_EPISODES.items()}
        second_seed[9] = (ALL_STAGES, 1.5, None)          # beats seed 1's 2.0
        write_log(os.path.join(temporary, 'batch', 's2', 'log.jsonl.gz'), fake_log_lines(second_seed))
        seed_label, best = ep_pick.min_energy_success_batch(os.path.join(temporary, 'batch'))
        check('min_energy_success_batch -> s2, 9', (seed_label, best.episode) == ('s2', 9))
        check('batch rule counts the seeds', best.rule ==
              'o sucesso de menor energia depois do 1º acerto, entre os 2 seeds')

        print('extract_episodes')
        stops = os.path.join(temporary, 'stops', 'log.jsonl.gz')
        lines = fake_log_lines()
        end_of_five = max(i for i, line in enumerate(lines)
                          if line.startswith('{"episode": 5,') and '"done": true' in line)
        write_log(stops, lines[:end_of_five + 1] + ['{"episode": 5, "step": 99, BROKEN'] +
                  lines[end_of_five + 1:])
        extracted = ep_pick.extract_episodes(stops, {2, 5})
        expected = {episode: episode_records(episode, *FAKE_EPISODES[episode]) for episode in (2, 5)}
        check('extract_episodes: exact records, and stops after the last one asked for',
              extracted == expected)

        print('cache')
        cache = os.path.join(temporary, 'cache')
        cached_log = os.path.join(temporary, 'cached', 'log.jsonl.gz')
        write_log(cached_log, fake_log_lines())
        first_read = ep_pick.episode_summaries(cached_log, cache)
        status = os.stat(cached_log)
        with open(cached_log, 'wb') as log_file:
            log_file.write(b'x' * status.st_size)           # same size, unreadable
        os.utime(cached_log, ns=(status.st_atime_ns, status.st_mtime_ns))
        check('same path, size and mtime: the cache answers, the log is not read',
              ep_pick.episode_summaries(cached_log, cache) == first_read)
        write_log(cached_log + '.new', fake_log_lines({e: FAKE_EPISODES[e] for e in range(3)}))
        os.replace(cached_log + '.new', cached_log)
        check('a changed log is read again', len(ep_pick.episode_summaries(cached_log, cache)) == 3)

        print('command line')
        command = subprocess.run([sys.executable, os.path.join(HERE, 'episode_pick.py'),
                                  os.path.join(temporary, 'batch'), '--rule', 'first-success',
                                  '--cache', cache], capture_output=True, text=True)
        check('CLI on a batch: one line per seed',
              command.stdout.splitlines() == ['s1\t2\to 1º sucesso deste seed',
                                              's2\t2\to 1º sucesso deste seed'])
        command = subprocess.run([sys.executable, os.path.join(HERE, 'episode_pick.py'),
                                  os.path.join(temporary, 'batch'), '--rule', 'min-energy-success',
                                  '--cache', cache], capture_output=True, text=True)
        check('CLI min-energy-success on a batch: the best seed', command.stdout.splitlines() ==
              ['s2\t9\to sucesso de menor energia depois do 1º acerto, entre os 2 seeds'])
        command = subprocess.run([sys.executable, os.path.join(HERE, 'episode_pick.py'),
                                  os.path.join(temporary, 'batch', 's1'), '--rule',
                                  'last-with-stage:release', '--cache', cache],
                                 capture_output=True, text=True)
        check('CLI last-with-stage on a run', command.stdout.splitlines() ==
              ["s1\t6\to último episódio deste seed que chegou a 'soltar no pad'"])
    finally:
        shutil.rmtree(temporary)
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
