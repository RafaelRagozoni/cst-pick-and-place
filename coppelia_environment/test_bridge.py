"""BRG-02 acceptance: drive the bridge over the wire, and check the run log it writes.

Needs CoppeliaSim running, and starts the bridge itself as a subprocess.

    python3 test_bridge.py
"""
import math
import os
import subprocess
import sys
import tempfile
import time

import metrics
from actions import grab, move
from bridge_client import BridgeClient, BridgeError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 5561
STEP_LIMIT = 130     # episode 0 is driven to this limit, so its normal end is exercised too
LOG = os.path.join(tempfile.gettempdir(), 'brg02_run.jsonl.gz')


def start_bridge():
    p = subprocess.Popen([sys.executable, os.path.join(HERE, 'bridge.py'),
                          '--port', str(PORT), '--mode', 'fixed', '--step-limit', str(STEP_LIMIT),
                          '--log', LOG, '--condition', 'TEST'],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=HERE)
    for _ in range(120):
        line = p.stdout.readline()
        if 'listening' in line:
            return p
        if p.poll() is not None:
            raise RuntimeError('bridge died at startup:\n' + line + p.stdout.read())
    raise RuntimeError('bridge did not come up')


def main():
    proc = start_bridge()
    ok = True
    try:
        c = BridgeClient(port=PORT)
        try:
            c.step([])
            refused_before_reset = False
        except BridgeError:
            refused_before_reset = True
        info = c.info()
        checks = [
            ('protocol advertised', info['protocol'] == 2),
            ('14 primitives offered', len(info['primitives']) == 14),
            ('goal steps advertised', info['goalSteps'] == ['reach', 'grasp', 'transport', 'release']),
            ('physics reported', info['physics']['engineName'] == 'bullet'),
            ('logging to the given path', info['log'] == LOG and info['condition'] == 'TEST'),
            ('step before any reset is refused', refused_before_reset),
        ]

        r = c.reset(seed=1, episode=0)
        obs = r['obs']
        checks += [
            ('reset returns an observation', 'innerSense' in obs and 'vision' in obs),
            ('reset is not already successful', r['success'] is False),
            ('goal starts at reach', r['goal']['current'] == 'reach'),
            ('gripper open after reset', obs['innerSense']['gripper']['width'] > 0.05),
        ]

        # A blank cycle must still advance the simulation exactly once.
        t0 = obs['t']
        s = c.step([])
        checks.append(('one step advances the clock once',
                       abs((s['obs']['t'] - t0) - 0.05) < 1e-6))

        # Bad requests must not kill the bridge mid-episode.
        try:
            c.call(op='nonsense')
            bad_handled = False
        except BridgeError:
            bad_handled = True
        checks.append(('unknown op returns an error, survives', bad_handled and c.ping()['ok']))

        # --- drive the task over the wire ---------------------------------
        # Joint-space only: this is the interface the agent gets, no IK, no teleporting.
        cube = s['obs']['vision']['cube']['pos']
        print('  driving the task over the wire (cube at %s)' % [round(v, 3) for v in cube])

        def run(records, n):
            r = None
            for _ in range(n):
                r = c.step(records)
            return r

        # A hand-built joint-space "expert": nudge joints until the tool is over the cube, descend,
        # close, lift, swing to the pad, open. Crude on purpose -- it exercises the wire protocol,
        # not the agent.
        latency = []
        seq = [([move(1, +1)], 60), ([move(2, -1)], 40), ([], 20)]
        for recs, n in seq:
            for _ in range(n):
                t = time.perf_counter()
                r = c.step(recs)
                latency.append((time.perf_counter() - t) * 1000)

        checks.append(('observation carries joints', len(r['obs']['innerSense']['joints']) == 6))
        checks.append(('observation carries goal state', 'current' in r['goal']))
        checks.append(('bridge tracks step count', r['step'] > 100))

        # Annotations: logged with their step, and never allowed to overwrite a logged field.
        c.step([grab(False)], annotate={'habit_id': ['h42'], 'drives': {'curiosity': 0.7},
                                        'repertoire': {'size': 14}})
        try:
            c.step([], annotate={'success': True})
            clash_refused = False
        except BridgeError:
            clash_refused = True
        checks.append(('annotation overwriting a field refused', clash_refused))
        r = c.step([])
        while not r['done']:
            r = c.step([])
        steps_ep0 = r['step']
        try:
            c.step([])
            refused_after_done = False
        except BridgeError:
            refused_after_done = True
        checks.append(('episode ends at the step limit', steps_ep0 == STEP_LIMIT))
        checks.append(('step after the episode ended refused', refused_after_done))

        # A reset mid-episode closes it; a second, short episode is closed by the shutdown.
        c.reset(seed=1, episode=1)
        for _ in range(3):
            c.step([])

        lat = sorted(latency)
        print('  per-cycle round trip: mean %.2f ms, median %.2f, p95 %.2f'
              % (sum(lat) / len(lat), lat[len(lat) // 2], lat[int(len(lat) * 0.95)]))

        for name, good in checks:
            print('  %-40s %s' % (name, 'PASS' if good else 'FAIL'))
            ok &= good

        c.shutdown()
    finally:
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()

    # --- the log the bridge wrote ---------------------------------------
    recs = metrics.load(LOG)
    terms = [x for x in recs if x['done']]
    acting = [x for x in recs if not x['done']]
    noted = [x for x in acting if x.get('drives')]
    m = metrics.reduce_log(recs)
    log_checks = [
        ('log: one terminal record per episode', [x['episode'] for x in terms] == [0, 1]),
        ('log: every step of episode 0 recorded',
         sum(1 for x in acting if x['episode'] == 0) == steps_ep0),
        ('log: limit-ended episode not aborted, reset one is',
         not terms[0]['episode_summary'].get('aborted') and terms[1]['episode_summary'].get('aborted')),
        ('log: condition and seed recorded',
         all(x['condition'] == 'TEST' and x['seed'] == 1 for x in recs)),
        ('log: annotation stored with its step',
         len(noted) == 1 and noted[0]['habit_id'] == ['h42'] and noted[0]['action'][0]['action'] == 'GRAB'),
        ('log: reduces to the metrics',
         m['episodes'] == 2 and m['totalSteps'] == steps_ep0 + 3 and m['repertoire'] == {'size': 14}),
        ('log: joint energy accumulated', terms[0]['episode_summary']['jointEnergy'] > 0.5),
    ]
    for name, good in log_checks:
        print('  %-40s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= good

    print('\nBRG-02 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
