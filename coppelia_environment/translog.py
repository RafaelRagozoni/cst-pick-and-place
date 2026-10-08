"""SIM-07: the transition log, and the one class that writes it.

Two things drive episodes: runner.py (Python policies -- C6) and bridge.py (the CST agent). Both
write through EpisodeLog, so the log metrics.py reduces has a single definition. Two writers with
two copies of the schema would drift, and a field missing from one would only surface as a metric
that cannot be computed after the experiment grid has already run.

Log format: one JSON object per line.

    {episode, step, t, seed, condition, obs, action, habit_id, goal_step, goal_fired,
     success, done, rewards}

The observation logged in a record is the one the agent saw **before** acting, and the action is
what it did about it. The next record's `obs` is therefore the resulting state, so `(s, a, s')`
triples read off unambiguously -- except across an episode boundary, which is why every episode ends
with a terminal record carrying `action: null`, `done: true` and the `episode_summary`. Merging
observation and outcome into one record is what makes those triples ambiguous, so it is
deliberately not done.

`rewards` and `habit_id` are the agent's to fill: the CST side computes the drives (WP2) and knows
which habit a record belongs to. Anything else the agent attaches -- drive levels, the repertoire
for metric 4 -- is written alongside, as long as it does not overwrite a field this module owns.

One logger, three consumers: the ablation metrics (metrics.py), credit-assignment debugging, and
the behaviour-cloning dataset of nn_slots_spec.md 4.3.

Logs are gzipped when the path ends in `.gz`, which is the default and strongly recommended: a full
observation is ~1.5 kB of the ~1.8 kB record, and the projected ablation grid (1e6 steps x 35 runs)
comes to ~63 GB uncompressed. The JSON is highly repetitive, so gzip costs little CPU and takes a
large bite out of that.
"""
import gzip
import json

from actions import record_id

# Fields the log owns. An agent annotation may add fields, never replace one of these.
OWNED = frozenset(('episode', 'step', 't', 'seed', 'condition', 'obs', 'action', 'goal_step',
                   'goal_fired', 'success', 'done', 'episode_summary'))


def open_log(path, mode='wt'):
    """Transparently gzip when the path ends in .gz. Shared by every writer and metrics.load()."""
    return gzip.open(path, mode) if str(path).endswith('.gz') else open(path, mode.replace('t', ''))


def check_annotation(extra):
    """Raise if an agent annotation would overwrite a field the log owns."""
    clash = sorted(OWNED.intersection(extra or {}))
    if clash:
        raise ValueError('annotation would overwrite logged fields: %s' % ', '.join(clash))


def _q(obs):
    return [j['pos'] for j in obs['innerSense']['joints']]


class EpisodeLog:
    """Writes one episode: an acting record per step, then one terminal record."""

    def __init__(self, sink, seed, episode, condition, obs, cube_start):
        self.sink = sink
        self.head = {'episode': episode, 'seed': seed, 'condition': condition}
        self.cube_start = cube_start
        self.obs = obs
        self.steps = 0
        self.energy = 0.0          # E_joint, cap4 metric 3: summed absolute joint-angle change

    def step(self, records, nxt, goal_step, goal_fired, success, extra=None):
        """Log one step: `records` were applied to the state the previous call left, giving `nxt`."""
        check_annotation(extra)
        self.energy += sum(abs(a - b) for a, b in zip(_q(nxt), _q(self.obs)))
        rec = dict(self.head, step=self.steps, t=self.obs['t'], obs=self.obs, action=records,
                   habit_id=[record_id(r) for r in records], goal_step=goal_step,
                   goal_fired=goal_fired, success=success, done=False, rewards={})
        rec.update(extra or {})
        self.sink.write(json.dumps(rec) + '\n')
        self.obs = nxt
        self.steps += 1

    def close(self, goal_step, success, goals_reached, aborted=False):
        """Write the terminal record. `aborted`: the episode was reset before it was done."""
        summary = {'steps': self.steps, 'success': success, 'jointEnergy': self.energy,
                   'goalsReached': list(goals_reached), 'cube_start': self.cube_start}
        if aborted:
            summary['aborted'] = True
        self.sink.write(json.dumps(dict(
            self.head, step=self.steps, t=self.obs['t'], obs=self.obs, action=None, habit_id=None,
            goal_step=goal_step, goal_fired=None, success=success, done=True, rewards={},
            episode_summary=summary)) + '\n')
        return summary
