"""What the macros did (vault spec MAC-01), and the numbers its exploratory runs are judged on.

    python3 tools/macro_report.py runs/<batch> [runs/<other> ...] [--last 100] [-o file.md]
    python3 tools/macro_report.py runs/<macro batch> runs/<P1 batch> --window 400 499 --seeds 1 2 3

One row per seed of each batch. A batch without macros (the C4 it is compared with) gets the same
row, its macro columns empty. Over the whole run:

  events          the HabitLearner's macro events: created / replaced / repeated / exists / empty /
                  refused (HabitLearnerCodelet.MacroEvent, logged as `macro` on the step they
                  happened in, or on the terminal record for the episode's last cycle; logs from
                  before bridge protocol 3 lack those, the release's among them)
  active, retired at the end (the last logged repertoire)
  never ran       active macros at the end that were never chosen
  runs            plans whose habit was a macro
  goal met        % of those runs in which one of the run's own actions completed the Task stage the
                  macro was built for (macro_<goal>_<n>). A record's goal_fired is the outcome of
                  that record's action (translog.py), so a goal fired in the record after the run
                  belongs to the next habit, not to the macro
  by stage        the same, per stage the macros were built for (R7: macros leaving from a pose
                  that varies inside the bin should fail more)
  ticks/run       median steps a macro run lasted

Over the last --last episodes (default 100) of each seed, or the episodes --window FIRST LAST of
every seed -- MAC-01's exploratory runs (500 episodes) are held to P1's over the same episodes --
what MAC-01's pass test compares:

  reach ticks     median steps from the episode start to the reach completion, episodes with one
  grasps/100      grasp completions per 100 episodes
  transports/100  transport completions per 100 episodes
  collisions/100  collision onsets (envCollision or selfCollision turning on) per 100 episodes
  in macro        % of all collision onsets that followed a step of a macro (R3: the straight line
                  hits something); the onset is seen in the record after the action that caused it,
                  the episode's terminal record included (its obs is the last action's outcome)
"""
import argparse
import collections
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runlog                                   # noqa: E402

KINDS = ('created', 'replaced', 'repeated', 'exists', 'empty', 'refused')


def macro_goal(habit_id):
    """'macro_grasp_3' -> 'grasp'."""
    return habit_id[len('macro_'):].rsplit('_', 1)[0]


def is_macro(habit_id):
    return bool(habit_id) and habit_id.startswith('macro_')


def collided(record):
    inner = record['obs']['innerSense']
    return bool(inner.get('envCollision')) or bool(inner.get('selfCollision'))


class Seed:
    def __init__(self, label):
        self.label = label
        self.events = dict.fromkeys(KINDS, 0)
        self.built = set()
        self.retired = set()
        self.chosen = set()
        self.runs = 0
        self.runs_met = 0
        self.runs_by_goal = collections.defaultdict(lambda: [0, 0])     # goal -> [runs, met]
        self.run_ticks = []
        self.repertoire = None
        self.episodes = []
        # per episode: reach step, grasps, transports, collision onsets, onsets after a macro step
        self.by_episode = {}


def close(s, run):
    """Counts a finished macro run as met or not, in total and by stage."""
    s.runs_met += run[3]
    s.runs_by_goal[macro_goal(run[0])][1] += run[3]


def count_collision_onset(episode_row, record, previous):
    """A collision seen in `record` that `previous` did not see: the previous record's action caused
    it. The terminal record counts too, since its obs is the outcome of the episode's last action."""
    if previous is not None and collided(record) and not collided(previous):
        episode_row['onsets'] += 1
        if is_macro(previous.get('habit_id')):
            episode_row['onsets_in_macro'] += 1


def count_macro_events(s, record):
    """The HabitLearner's macro events logged on `record`, a step or the terminal record (a stage met
    on the episode's last observation builds its macro on the cycle that ends the episode)."""
    for event in record.get('macro') or ():
        s.events[event['kind']] = s.events.get(event['kind'], 0) + 1
        if event['kind'] in ('created', 'replaced'):
            s.built.add(event['macro'])
        if event.get('retired'):
            s.retired.add(event['retired'])


def scan(label, path):
    s = Seed(label)
    run = None                                  # [habit, plan, records so far, met]
    previous = None
    for r in runlog.records(path):
        if r.get('done') and 'episode_summary' in r:
            if previous is not None:
                count_collision_onset(s.by_episode[previous['episode']], r, previous)
            count_macro_events(s, r)
            if run is not None:
                close(s, run)
                run = None
            previous = None
            continue
        ep = r['episode']
        if ep not in s.by_episode:
            s.by_episode[ep] = {'reach': None, 'grasp': 0, 'transport': 0, 'onsets': 0,
                                'onsets_in_macro': 0}
            s.episodes.append(ep)
        row = s.by_episode[ep]
        fired = r.get('goal_fired')
        if fired == 'reach' and row['reach'] is None:
            row['reach'] = r['step']
        elif fired in ('grasp', 'transport'):
            row[fired] += 1
        count_collision_onset(row, r, previous)
        count_macro_events(s, r)
        if r.get('repertoire'):
            s.repertoire = r['repertoire']

        habit = r.get('habit_id')
        if run is not None and (habit != run[0] or r.get('plan') != run[1]):
            close(s, run)
            run = None
        if is_macro(habit) and run is None:
            run = [habit, r.get('plan'), 0, 0]
            s.runs += 1
            s.runs_by_goal[macro_goal(habit)][0] += 1
            s.chosen.add(habit)
        if run is not None:
            run[2] += 1
            if run[2] == 1:
                s.run_ticks.append(0)
            s.run_ticks[-1] += 1
            if fired == macro_goal(run[0]):
                run[3] = 1                      # this record's own action completed the stage
        previous = r
    if run is not None:
        close(s, run)
    return s


def last_rows(s, last, window=None):
    """The rows the pass columns cover: episodes window[0]..window[1], else the last `last`."""
    if not s.episodes:
        return []
    if window:
        return [s.by_episode[e] for e in s.episodes if window[0] <= e <= window[1]]
    first_kept = max(s.episodes) - last + 1
    return [s.by_episode[e] for e in s.episodes if e >= first_kept]


def fmt(v, digits=0):
    if v is None:
        return '-'
    return ('%%.%df' % digits) % v


def by_stage(s):
    """'grasp 100 · reach 50': % of the runs that met their goal, per stage."""
    if not s.runs:
        return '-'
    return ' · '.join('%s %s' % (goal, fmt(100.0 * met / runs))
                      for goal, (runs, met) in sorted(s.runs_by_goal.items()))


def row(batch, s, last, window=None):
    rows = last_rows(s, last, window)
    n = len(rows)
    reach = [r['reach'] for r in rows if r['reach'] is not None]
    onsets = sum(r['onsets'] for r in rows)
    in_macro = sum(r['onsets_in_macro'] for r in rows)
    has_macros = any(s.events.values())
    active = (s.repertoire or {}).get('macro', 0)
    retired = (s.repertoire or {}).get('retired', 0)
    never = len(s.built - s.retired - s.chosen)
    cells = [batch, s.label, str(len(s.episodes)),
             ' / '.join(str(s.events[k]) for k in KINDS) if has_macros else '-',
             '%d / %d' % (active, retired) if has_macros else '-',
             str(never) if has_macros else '-',
             str(s.runs) if has_macros else '-',
             fmt(100.0 * s.runs_met / s.runs) if s.runs else '-',
             by_stage(s),
             fmt(statistics.median(s.run_ticks)) if s.run_ticks else '-',
             fmt(statistics.median(reach)) if reach else '-',
             fmt(100.0 * sum(r['grasp'] for r in rows) / n, 1) if n else '-',
             fmt(100.0 * sum(r['transport'] for r in rows) / n, 1) if n else '-',
             fmt(100.0 * onsets / n, 1) if n else '-',
             fmt(100.0 * in_macro / onsets) if onsets and has_macros else '-']
    return '| ' + ' | '.join(cells) + ' |'


def report(paths, last, window=None, seeds=None):
    lines = ['| batch | seed | episodes | events c / rp / rep / ex / em / ref | active / retired '
             '| never ran | runs | goal met % | by stage % | ticks/run | reach ticks | grasps/100 '
             '| transports/100 | collisions/100 | in macro % |',
             '|' + '---|' * 15]
    for path in paths:
        batch = os.path.basename(os.path.normpath(path))
        for label, log, _ in runlog.find_logs([path]):
            if seeds and label not in ['s%d' % k for k in seeds]:
                continue
            lines.append(row(batch, scan(label, log), last, window))
    lines.append('')
    covered = ('episodes %d-%d of each seed' % tuple(window) if window
               else 'the last %d episodes of each seed' % last)
    lines.append('_Columns after "ticks/run" cover %s. Events: created, replaced, repeated, exists, '
                 'empty, refused._' % covered)
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='+', help='batch folders, run folders or logs')
    ap.add_argument('--last', type=int, default=100, help='episodes the pass columns cover')
    ap.add_argument('--window', type=int, nargs=2, metavar=('FIRST', 'LAST'),
                    help='the pass columns cover these episodes of every seed instead')
    ap.add_argument('--seeds', type=int, nargs='+', help='only these seeds')
    ap.add_argument('-o', help='also write the report here')
    a = ap.parse_args()
    text = report(a.paths, a.last, a.window, a.seeds)
    if a.o:
        with open(a.o, 'w') as f:
            f.write(text)
    print(text, end='')


if __name__ == '__main__':
    main()
