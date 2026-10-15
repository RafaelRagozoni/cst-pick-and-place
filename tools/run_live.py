"""Run the agent live, headless, one independent run per seed, in parallel.

    python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000

Each seed gets its own CoppeliaSim (bridge.py --launch headless), its own bridge and its own agent:
nothing is shared, so the seeds are independent samples. Seeds beyond --jobs wait their turn.

Everything lands in runs/<date>_<condition>_<selection>[_<tag>]/:
    agent/                 the compiled agent this batch ran -- a snapshot, so editing or
                           rebuilding the code while a run goes cannot change it halfway
    s<seed>/log.jsonl.gz   the bridge's run log (metrics.py, summarize_run.py, replay.py read it)
    s<seed>/agent.out      one line per episode
    s<seed>/bridge.out
    s<seed>/run.json       arguments, git commit, start and end, exit codes

Follow a run with `tail -f runs/.../s1/agent.out`, or summarize it while it goes:
`python3 tools/summarize_run.py runs/...`.
"""
import argparse
import datetime
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, 'agent')
BRIDGE = os.path.join(ROOT, 'coppelia_environment', 'bridge.py')
CHILDREN = []          # every bridge and agent started, so Ctrl-C can stop them all


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def git_commit():
    def git(*a):
        return subprocess.run(['git', '-C', ROOT] + list(a), capture_output=True,
                              text=True).stdout.strip()
    dirty = bool(git('status', '--porcelain', '--', 'agent', 'coppelia_environment/*.py'))
    return git('rev-parse', '--short', 'HEAD') + ('-dirty' if dirty else '')


def snapshot_agent(dest):
    """Build the agent and copy the runnable distribution: the batch runs this copy."""
    subprocess.run([os.path.join(AGENT, 'gradlew'), '-q', 'installDist'], cwd=AGENT, check=True)
    shutil.copytree(os.path.join(AGENT, 'build', 'install', 'agent'), dest)
    return os.path.join(dest, 'bin', 'agent')


def run_seed(a, seed, batch, agent_bin, commit, lock):
    d = os.path.join(batch, 's%d' % seed)
    os.makedirs(d)
    meta = {'condition': a.condition, 'selection': a.selection, 'seed': seed, 'emax': a.emax,
            'eref': a.eref, 'stepLimit': a.step_limit, 'commit': commit,
            'start': datetime.datetime.now().isoformat(timespec='seconds')}
    with open(os.path.join(d, 'run.json'), 'w') as f:      # rewritten with the end and exits
        json.dump(meta, f, indent=1)
    port = free_port()
    with open(os.path.join(d, 'bridge.out'), 'w') as bout, \
            open(os.path.join(d, 'agent.out'), 'w') as aout:
        bridge = subprocess.Popen(
            [sys.executable, BRIDGE, '--launch', 'headless', '--port', str(port),
             '--step-limit', str(a.step_limit), '--log', os.path.join(d, 'log.jsonl.gz'),
             '--condition', a.condition], stdout=bout, stderr=subprocess.STDOUT)
        CHILDREN.append(bridge)
        agent = subprocess.Popen(
            [agent_bin, '--port', str(port), '--condition', a.condition, '--seed', str(seed),
             '--emax', str(a.emax), '--eref', str(a.eref), '--selection', a.selection],
            stdout=aout, stderr=subprocess.STDOUT)
        CHILDREN.append(agent)
        meta['agentExit'] = agent.wait()
        try:
            meta['bridgeExit'] = bridge.wait(60)
        except subprocess.TimeoutExpired:
            # The agent ended without shutting the bridge down (it crashed): stop it, which also
            # stops its CoppeliaSim and closes the log.
            bridge.terminate()
            bridge.wait(60)
            meta['bridgeExit'] = 'terminated: the agent ended without shutting it down'
    meta['end'] = datetime.datetime.now().isoformat(timespec='seconds')
    with open(os.path.join(d, 'run.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    with lock:
        print('  seed %d done: agent exit %s, bridge exit %s -> %s'
              % (seed, meta['agentExit'], meta['bridgeExit'], d), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--condition', default='C0')
    ap.add_argument('--selection', default='ucb')
    ap.add_argument('--seeds', type=int, nargs='+', default=[1])
    ap.add_argument('--emax', type=int, default=1000, help='Phase 1 episodes at most')
    ap.add_argument('--eref', type=int, default=0, help='Phase 2 episodes after a first success')
    ap.add_argument('--step-limit', type=int, default=500)
    ap.add_argument('--jobs', type=int, default=None,
                    help='runs at once (default: all seeds); each takes ~1.5 cores')
    ap.add_argument('--tag', default='', help='appended to the batch folder name')
    a = ap.parse_args()

    name = '%s_%s_%s%s' % (datetime.datetime.now().strftime('%Y-%m-%d_%H%M'), a.condition,
                           a.selection, '_' + a.tag if a.tag else '')
    batch = os.path.join(ROOT, 'runs', name)
    os.makedirs(batch)
    commit = git_commit()
    print('batch %s (code %s)' % (batch, commit), flush=True)
    agent_bin = snapshot_agent(os.path.join(batch, 'agent'))

    lock = threading.Lock()
    jobs = a.jobs or len(a.seeds)
    pending = list(a.seeds)
    running = []
    # Ctrl-C or `kill` stops the whole batch cleanly. SIGINT is reset explicitly: a process started
    # in the background by a non-interactive shell inherits it ignored.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    t0 = time.time()
    try:
        while pending or running:
            running = [t for t in running if t.is_alive()]
            while pending and len(running) < jobs:
                seed = pending.pop(0)
                t = threading.Thread(target=run_seed,
                                     args=(a, seed, batch, agent_bin, commit, lock), daemon=True)
                t.start()
                running.append(t)
                print('  seed %d started' % seed, flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print('\ninterrupted: stopping every agent and bridge (each bridge stops its simulator)')
        for p in CHILDREN:
            if p.poll() is None:
                p.terminate()
        for p in CHILDREN:
            try:
                p.wait(60)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(130)
    print('all done in %.1f min: python3 tools/summarize_run.py %s'
          % ((time.time() - t0) / 60, batch), flush=True)


if __name__ == '__main__':
    main()
