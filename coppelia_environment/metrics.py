"""SIM-07: reduce a run log to the five metrics of cap4 4.6.3.

Pure functions over the JSONL the runner writes -- no simulator. The point of the acceptance test is
that a finished run reduces to every reported metric **without re-running anything**: if a metric
cannot be computed from the log, the log is missing a field and that is a bug to fix now, not after
a two-day experiment grid.

Metric 4 (repertoire size and fusion fraction) needs the HabitPool, which lives on the CST side: the
agent logs it with every step (agent/.../Telemetry.java). A log without it -- the Python runner's --
reports it as unavailable rather than silently returning 0, which would look like a real measurement.
"""
import gzip
import json
import math
from collections import Counter

# Behaviour characterisation, cap4 4.3: task space (end-effector and object positions), augmented
# with the salient-event dimensions -- gripper state, contact flag, object displacement.
POS_BIN = 0.05          # m
DISP_BIN = 0.02         # m


def characterise(obs):
    """The behaviour characterisation b of cap4 4.3, as a bin tuple."""
    eef = obs['innerSense']['eef']['pos']
    cube = obs['vision']['cube']['pos']
    g = obs['innerSense']['gripper']
    return (
        tuple(int(math.floor(v / POS_BIN)) for v in eef),
        tuple(int(math.floor(v / POS_BIN)) for v in cube),
        bool(g['isHolding']),
        bool(g['inContact']),
        int(obs['derived']['cubeDisplacement'] / DISP_BIN),
    )


def load(path):
    """Reads plain or gzipped JSONL."""
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as f:
        return [json.loads(l) for l in f]


def reduce_log(records):
    """Return the five metrics. `records` is the parsed JSONL of one run (one condition, one seed)."""
    summaries = [r['episode_summary'] for r in records if r.get('done') and 'episode_summary' in r]
    n = len(summaries)
    successes = [i for i, s in enumerate(summaries) if s['success']]

    # 1. task success rate
    success_rate = len(successes) / n if n else float('nan')

    # 2. episodes to first success (None if never)
    first = successes[0] if successes else None

    # 3. steps and joint energy per *successful* episode
    ok = [s for s in summaries if s['success']]
    steps_per_success = sum(s['steps'] for s in ok) / len(ok) if ok else float('nan')
    energy_per_success = sum(s['jointEnergy'] for s in ok) / len(ok) if ok else float('nan')

    # 4. repertoire size / fusion fraction -- from the log if the agent recorded it
    rep = [r['repertoire'] for r in records if 'repertoire' in r]
    repertoire = rep[-1] if rep else None

    # 5. state-space coverage: distinct characterisation bins visited
    bins = set(characterise(r['obs']) for r in records if r.get('obs'))

    goals = Counter(g for s in summaries for g in s.get('goalsReached', []))

    return {
        'episodes': n,
        'successRate': success_rate,
        'episodesToFirstSuccess': first,
        'stepsPerSuccess': steps_per_success,
        'jointEnergyPerSuccess': energy_per_success,
        'repertoire': repertoire,          # None == not logged (e.g. runner.py, no HabitPool)
        'coverageBins': len(bins),
        'goalStepsReached': dict(goals),
        'totalSteps': sum(s['steps'] for s in summaries),
    }


def report(m):
    print('  episodes                 : %d' % m['episodes'])
    print('  1. success rate          : %.3f' % m['successRate'])
    print('  2. episodes to 1st success: %s' % (m['episodesToFirstSuccess']
                                                if m['episodesToFirstSuccess'] is not None
                                                else 'never'))
    print('  3. steps / success       : %.1f' % m['stepsPerSuccess'])
    print('     joint energy / success: %.2f rad' % m['jointEnergyPerSuccess'])
    print('  4. repertoire            : %s' % (m['repertoire'] or 'unavailable (not logged)'))
    print('  5. coverage bins visited : %d' % m['coverageBins'])
    print('  goal steps reached       : %s' % (m['goalStepsReached'] or 'none'))


if __name__ == '__main__':
    import sys
    report(reduce_log(load(sys.argv[1])))
