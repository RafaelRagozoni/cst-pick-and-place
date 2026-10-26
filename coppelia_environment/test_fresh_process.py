"""SIM-09 acceptance: runs in fresh CoppeliaSim processes give the same physics.

Needs no CoppeliaSim open: each run is `bridge.py --launch headless`. It closes the gripper on
nothing -- the finger contact where same-seed runs were seen to part -- over two episodes, in RUNS
processes, and requires all identical. Five, not two: with a few variants per process, two runs
land on the same one often enough to pass by luck. FAILS under Bullet, the engine pinned today: its contacts vary per
process (three variants in six processes). MuJoCo, ODE and Newton passed it (2026-10-15).

    python3 test_fresh_process.py
"""
import os
import subprocess
import sys

from actions import grab
from bridge_client import BridgeClient
from simprocess import free_port

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = 5


def bridge(args):
    port = free_port()
    p = subprocess.Popen([sys.executable, os.path.join(HERE, 'bridge.py'), '--port', str(port)]
                         + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         cwd=HERE)
    out = []
    for line in p.stdout:
        out.append(line)
        if 'listening' in line:
            return p, port, out
    p.wait()
    return p, None, out


def close_gripper_run():
    """Two episodes: close the gripper on nothing, then reset and close again."""
    p, port, out = bridge(['--launch', 'headless', '--no-log'])
    if port is None:
        raise RuntimeError('bridge did not come up:\n' + ''.join(out))
    c = BridgeClient(port=port)
    trace = []
    for ep in range(2):
        c.reset(1, ep)
        for _ in range(60):
            o = c.step([grab(False)])['obs']
            inner = o['innerSense']
            trace.append([j['pos'] for j in inner['joints']] + [inner['gripper']['width']])
    c.shutdown()
    p.wait(60)
    return trace


def main():
    runs = [close_gripper_run() for _ in range(RUNS)]
    dev = max(max(abs(x - y) for x, y in zip(ra, rb))
              for run in runs[1:] for ra, rb in zip(runs[0], run))
    checks = [('%d fresh processes, gripper closing, identical' % RUNS, dev <= 1e-9)]
    print('  max deviation from the first run: %.2g' % dev)

    ok = True
    for name, good in checks:
        print('  %-48s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= good
    print('\nSIM-09 ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
