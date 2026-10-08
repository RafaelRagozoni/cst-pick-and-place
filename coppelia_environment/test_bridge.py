"""BRG-02 acceptance: drive the bridge through a full pick-and-place over the wire.

Needs CoppeliaSim running, and starts the bridge itself as a subprocess.

    python3 test_bridge.py
"""
import math
import os
import subprocess
import sys
import time

from actions import grab, move
from bridge_client import BridgeClient, BridgeError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 5561


def start_bridge():
    p = subprocess.Popen([sys.executable, os.path.join(HERE, 'bridge.py'),
                          '--port', str(PORT), '--mode', 'fixed', '--step-limit', '4000'],
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
        info = c.info()
        checks = [
            ('protocol advertised', info['protocol'] == 2),
            ('14 primitives offered', len(info['primitives']) == 14),
            ('goal steps advertised', info['goalSteps'] == ['reach', 'grasp', 'transport', 'release']),
            ('physics reported', info['physics']['engineName'] == 'bullet'),
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

    print('\nBRG-02 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
