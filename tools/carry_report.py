"""What happens to the cube once it is grasped (vault spec CRE-01): how carries end, how often the
agent lets go while holding, and how many of its choices with the cube held were UCB's forced draw.

    python3 tools/carry_report.py runs/<batch> [runs/<other> ...] [--block 500] [-o file.md]

One row per seed and block of episodes, then every seed together, block by block:

  grasps          carries started: the cube not held in one observation, held in the next
  dropped away    carries that ended with the cube let go more than 5 cm (xy) from the pad, % of grasps
  by grab_open    of those, % whose last action before the release was grab_open
  held choices    plans started on an observation with the cube held
  grab_open       % of the held choices that were grab_open
  new to bin      % of the held choices whose habit had not started before in its context, goal +
                  state bin, rebuilt from the observation (metrics.characterise, the Python twin of
                  Characterization.key). Without borrowing this is UCB's forced draw; rebuilt from
                  the log alone, so a batch from before CRE-01 has it too
  forced          % of the held choices made while some habit was untried there (no execution in the
                  context, nothing borrowed): UCB then starts one of them at random. Read from the
                  agent's `choice` field (CRE-01); "-" for a log from before it
  open new, open forced: the same two among the grab_open picks while holding
  transports/100  episodes in which the environment's tracker saw the transport stage, per 100

A log records the observation the agent saw before acting (translog.py), so a choice is judged on
its own record's observation, and a release is charged to the action of the record before it.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'coppelia_environment'))
import runlog                                   # noqa: E402
from metrics import characterise                # noqa: E402

NEAR_PAD_XY = 0.05                              # m; goals.py's transport and success radius


class Block:
    def __init__(self):
        self.first = None                       # episode indices covered
        self.last = None
        self.episodes = 0
        self.grasps = 0
        self.dropped_away = 0
        self.dropped_by_open = 0
        self.held_choices = 0
        self.held_open = 0
        self.held_new = 0
        self.held_logged = 0                    # held choices with the agent's `choice` field
        self.held_forced = 0
        self.open_new = 0
        self.open_logged = 0
        self.open_forced = 0
        self.transports = 0

    def add(self, other):
        for k, v in vars(other).items():
            if k == 'first':
                self.first = v if self.first is None else min(self.first, v)
            elif k == 'last':
                self.last = v if self.last is None else max(self.last, v)
            else:
                setattr(self, k, getattr(self, k) + v)


def holding(obs):
    return bool(obs['innerSense']['gripper']['isHolding'])


def scan(log, block):
    """Blocks of `block` episodes, in order, for one log."""
    blocks = []
    cur = Block()
    started_in = {}                             # (goal, bin) -> habits started there
    last_plan = None
    for ep, recs, summ in runlog.episodes(log):
        was_holding = False
        previous = None
        for r in recs:
            obs = r.get('obs')
            held = obs is not None and holding(obs)
            if obs is not None and not held and was_holding:
                if obs['derived']['cubeToPadXY'] > NEAR_PAD_XY:
                    cur.dropped_away += 1
                    if previous is not None and previous.get('habit_id') == 'grab_open':
                        cur.dropped_by_open += 1
            if held and not was_holding:
                cur.grasps += 1
            if obs is not None:
                was_holding = held
            previous = r
            if r.get('done') or r.get('plan') is None or r['plan'] == last_plan:
                continue
            last_plan = r['plan']
            habit = r['habit_id']
            tried = started_in.setdefault((r.get('goal'), characterise(obs)), set())
            new_to_bin = habit not in tried
            tried.add(habit)
            if not held:
                continue
            cur.held_choices += 1
            is_open = habit == 'grab_open'
            cur.held_open += is_open
            cur.held_new += new_to_bin
            cur.open_new += is_open and new_to_bin
            choice = r.get('choice')
            if choice is not None:
                forced = choice['untried'] > 0
                cur.held_logged += 1
                cur.held_forced += forced
                cur.open_logged += is_open
                cur.open_forced += is_open and forced
        cur.episodes += 1
        cur.first = ep if cur.first is None else cur.first
        cur.last = ep
        if 'transport' in (summ or {}).get('goalsReached', []):
            cur.transports += 1
        if cur.episodes == block:
            blocks.append(cur)
            cur = Block()
    if cur.episodes:
        blocks.append(cur)
    return blocks


def pct(part, whole):
    return '-' if not whole else '%.0f%%' % (100.0 * part / whole)


HEADER = ('| seed | episodes | grasps | dropped away | by grab_open | held choices | grab_open '
          '| new to bin | forced | open new | open forced | transports/100 |\n'
          '|---|---|---|---|---|---|---|---|---|---|---|---|')


def row(label, b):
    return '| %s | %d-%d | %d | %s | %s | %d | %s | %s | %s | %s | %s | %.1f |' % (
        label, b.first, b.last, b.grasps, pct(b.dropped_away, b.grasps),
        pct(b.dropped_by_open, b.dropped_away), b.held_choices, pct(b.held_open, b.held_choices),
        pct(b.held_new, b.held_choices), pct(b.held_forced, b.held_logged),
        pct(b.open_new, b.held_open), pct(b.open_forced, b.open_logged),
        100.0 * b.transports / b.episodes)


def report(paths, block):
    logs = runlog.find_logs(paths)
    lines = ['# Carry report', '', 'Vault spec CRE-01; columns in tools/carry_report.py. Blocks of '
             '%d episodes.' % block, '', HEADER]
    together = []
    for label, log, _ in logs:
        for i, b in enumerate(scan(log, block)):
            lines.append(row(label, b))
            if i == len(together):
                together.append(Block())
            together[i].add(b)
    if len(logs) > 1:
        for i, b in enumerate(together):
            lines.append(row('**all**', b))
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='+', help='batch folders, run folders or logs')
    ap.add_argument('--block', type=int, default=500, help='episodes per row (default 500)')
    ap.add_argument('-o', help='also write the report here')
    a = ap.parse_args()
    text = report(a.paths, a.block)
    if a.o:
        with open(a.o, 'w') as f:
            f.write(text)
    print(text, end='')


if __name__ == '__main__':
    main()
