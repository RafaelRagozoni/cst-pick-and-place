"""Choose the episode a replay shows by a named rule, never by hand (vault spec APR-01).

    python3 tools/episode_pick.py runs/<batch>[/sN] --rule <rule> [--cache DIR]

    rules: every:N | first-success | last-with-stage:STAGE | min-energy-success | first-drop-away:START
    prints: seed <tab> episode <tab> the rule in Portuguese, which goes into the video's caption

A slide's video is only as honest as the reason it shows that episode, so every pick carries the
sentence that says how it was chosen. A rule that matches nothing raises LookupError with that
sentence; it never falls back to another episode.

Reading is fast because most lines are never parsed: the episode number is read from the start of
each line, the summaries come from the terminal lines only (`"done": true`), and extraction stops
after the last episode asked for. Summaries are cached per log, keyed by path, size and mtime.
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import carry_report                             # noqa: E402
import runlog                                   # noqa: E402

Pick = collections.namedtuple('Pick', 'episode rule')

STAGE_WORDS = {'reach': 'chegar ao cubo', 'grasp': 'pegar', 'transport': 'levar ao pad',
               'release': 'soltar no pad'}

DEFAULT_CACHE_DIR = os.path.expanduser('~/.cache/episode_pick')
EPISODE_PREFIX = '{"episode": '
TERMINAL_MARK = '"done": true'
MIN_ENERGY_RULE = 'o sucesso de menor energia depois do 1º acerto'


def no_match(rule, where):
    return LookupError('nenhum episódio casa com a regra "%s" em %s' % (rule, where))


# --- reading ----------------------------------------------------------------------------------
def episode_of_line(line):
    """The episode number of a log line, read from its start without parsing the record (translog
    writes "episode" first); a line of another shape is parsed; None if it cannot be read."""
    if line.startswith(EPISODE_PREFIX):
        comma = line.find(',', len(EPISODE_PREFIX))
        if comma > 0:
            try:
                return int(line[len(EPISODE_PREFIX):comma])
            except ValueError:
                pass
    try:
        return json.loads(line)['episode']
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def lines_with_episode(log):
    """(episode, raw line) for every line; ends quietly where a run still being written stops."""
    opener = gzip.open if log.endswith('.gz') else open
    with opener(log, 'rt') as log_file:
        try:
            for line in log_file:
                yield episode_of_line(line), line
        except runlog.READ_ERRORS:
            return


def cache_file_for(log, cache_dir):
    name = hashlib.sha1(os.path.abspath(log).encode()).hexdigest()[:16] + '.json'
    return os.path.join(cache_dir, name)


def episode_summaries(log, cache_dir=None):
    """One dict per finished episode: {'episode', 'steps', 'success', 'goals', 'energy'}, read
    from the terminal lines only. With cache_dir, a log whose path, size and mtime have not
    changed is answered from the cache without being opened."""
    status = os.stat(log)
    stamp = {'log': os.path.abspath(log), 'size': status.st_size, 'mtime_ns': status.st_mtime_ns}
    cache_file = cache_file_for(log, cache_dir) if cache_dir else None
    if cache_file and os.path.isfile(cache_file):
        with open(cache_file) as cached_file:
            cached = json.load(cached_file)
        if cached.get('stamp') == stamp:
            return cached['summaries']
    summaries = []
    for _, line in lines_with_episode(log):
        if TERMINAL_MARK not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            break                               # a line cut where an unfinished log stops
        summary = record.get('episode_summary') or {}
        summaries.append({'episode': record['episode'], 'steps': summary.get('steps'),
                          'success': bool(summary.get('success')),
                          'goals': summary.get('goalsReached') or [],
                          'energy': summary.get('jointEnergy')})
    if cache_file:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file + '.tmp', 'w') as cached_file:
            json.dump({'stamp': stamp, 'summaries': summaries}, cached_file)
        os.replace(cache_file + '.tmp', cache_file)
    return summaries


def extract_episodes(log, episodes):
    """{episode: [its records, terminal last]} for the episodes asked for; reading stops right
    after the terminal record of the last one. LookupError if one of them is not finished."""
    wanted = set(episodes)
    last_wanted = max(wanted)
    found = {episode: [] for episode in sorted(wanted)}
    for episode, line in lines_with_episode(log):
        if episode is None or episode not in wanted:
            if episode is not None and episode > last_wanted:
                break
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            break
        found[episode].append(record)
        if episode == last_wanted and record.get('done'):
            break
    unfinished = [episode for episode, records in found.items()
                  if not records or not records[-1].get('done')]
    if unfinished:
        raise LookupError('episodes not finished in %s: %s' % (log, unfinished))
    return found


def drop_away_step(records):
    """Step of the first record where the cube, held at the observation before, is let go more
    than carry_report.NEAR_PAD_XY from the pad (carry_report's "dropped away"); None if never."""
    was_holding = False
    for record in records:
        observation = record.get('obs')
        if observation is None:
            continue
        holding = carry_report.holding(observation)
        if (was_holding and not holding
                and observation['derived']['cubeToPadXY'] > carry_report.NEAR_PAD_XY):
            return record['step']
        was_holding = holding
    return None


# --- rules ------------------------------------------------------------------------------------
def every(summaries, n):
    if n <= 0:
        raise ValueError('every needs n > 0, got %d' % n)
    rule = 'um episódio a cada %d' % n
    picks = [Pick(s['episode'], rule) for s in summaries if s['episode'] % n == 0]
    if not picks:
        raise no_match(rule, 'os resumos')
    return picks


def first_success(summaries):
    rule = 'o 1º sucesso deste seed'
    for summary in summaries:
        if summary['success']:
            return Pick(summary['episode'], rule)
    raise no_match(rule, 'os resumos')


def last_with_stage(summaries, stage):
    if stage not in STAGE_WORDS:
        raise ValueError('unknown stage %r; stages: %s' % (stage, ', '.join(STAGE_WORDS)))
    rule = "o último episódio deste seed que chegou a '%s'" % STAGE_WORDS[stage]
    for summary in reversed(summaries):
        if stage in summary['goals']:
            return Pick(summary['episode'], rule)
    raise no_match(rule, 'os resumos')


def lowest_energy_success_after_first(summaries):
    """The summary of the success with the lowest joint energy among those after the first; None
    if there is none."""
    after_first = [s for s in summaries if s['success']][1:]
    return min(after_first, key=lambda s: s['energy']) if after_first else None


def min_energy_success(summaries):
    best = lowest_energy_success_after_first(summaries)
    if best is None:
        raise no_match(MIN_ENERGY_RULE, 'os resumos')
    return Pick(best['episode'], MIN_ENERGY_RULE)


def min_energy_success_batch(batch_dir, cache_dir=None):
    """(seed label, Pick) of the lowest-energy success after the first, over every seed."""
    logs = runlog.find_logs([batch_dir])
    rule = '%s, entre os %d seeds' % (MIN_ENERGY_RULE, len(logs))
    candidates = []
    for label, log, _ in logs:
        best = lowest_energy_success_after_first(episode_summaries(log, cache_dir))
        if best is not None:
            candidates.append((best['energy'], label, best['episode']))
    if not candidates:
        raise no_match(rule, batch_dir)
    _, label, episode = min(candidates)
    return label, Pick(episode, rule)


def first_drop_away(log, start):
    rule = 'o 1º episódio a partir do %d em que o cubo é pego e largado longe do pad' % start
    current, records = None, []
    for episode, line in lines_with_episode(log):
        if episode is None or episode < start:
            continue
        if episode != current:
            current, records = episode, []
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            break
        records.append(record)
        if record.get('done') and drop_away_step(records) is not None:
            return Pick(episode, rule)
    raise no_match(rule, log)


RULE_NAMES = ('every:N', 'first-success', 'last-with-stage:STAGE', 'min-energy-success',
              'first-drop-away:START')


def picks_for_rule(log, rule_spec, cache_dir=None):
    """The picks of one log for a rule written as on the command line (RULE_NAMES)."""
    name, _, argument = rule_spec.partition(':')
    if name == 'every':
        return every(episode_summaries(log, cache_dir), int(argument))
    if name == 'first-success':
        return [first_success(episode_summaries(log, cache_dir))]
    if name == 'last-with-stage':
        return [last_with_stage(episode_summaries(log, cache_dir), argument)]
    if name == 'min-energy-success':
        return [min_energy_success(episode_summaries(log, cache_dir))]
    if name == 'first-drop-away':
        return [first_drop_away(log, int(argument))]
    raise ValueError('unknown rule %r; rules: %s' % (rule_spec, ' | '.join(RULE_NAMES)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('path', help='a run folder (s1/), a batch folder or a log')
    parser.add_argument('--rule', required=True, help=' | '.join(RULE_NAMES))
    parser.add_argument('--cache', default=DEFAULT_CACHE_DIR,
                        help='summary cache folder (default %(default)s)')
    args = parser.parse_args()
    logs = runlog.find_logs([args.path])
    if args.rule == 'min-energy-success' and len(logs) > 1:
        label, pick = min_energy_success_batch(args.path, args.cache)
        print('%s\t%d\t%s' % (label, pick.episode, pick.rule))
        return
    for label, log, _ in logs:
        for pick in picks_for_rule(log, args.rule, args.cache):
            print('%s\t%d\t%s' % (label, pick.episode, pick.rule))


if __name__ == '__main__':
    main()
