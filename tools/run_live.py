"""Run the agent live, headless, one independent run per seed, in parallel.

    python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000
    python3 tools/run_live.py --selection ucb:0.1 --curiosity count --seeds 1 2 3 --emax 200
    python3 tools/run_live.py --resume runs/<batch> --emax 2000       # continue it to 2000

Each seed gets its own CoppeliaSim (bridge.py --launch headless), its own bridge and its own agent:
nothing is shared, so the seeds are independent samples. Seeds beyond --jobs wait their turn.

Everything lands in runs/<date>_<condition>_<selection>[_<curiosity>][_<tag>]/ (the curiosity yield
named only when it is not none):
    agent/                 the compiled agent this batch ran -- a snapshot, so editing or
                           rebuilding the code while a run goes cannot change it halfway
    s<seed>/log.jsonl.gz   the bridge's run log (metrics.py, summarize_run.py, replay.py read it)
    s<seed>/checkpoint.json.gz      the agent after its last finished episode (Checkpoint.java)
    s<seed>/checkpoints/after-epN.json.gz   kept every --keep-every episodes
    s<seed>/agent.out      one line per episode
    s<seed>/bridge.out
    s<seed>/run.json       arguments, git commit, start and end, exit codes, resumes

--resume continues every seed of a batch (or --seeds) from its checkpoint, with the batch's own agent
snapshot and settings; --emax and --eref are totals, so --emax 2000 after 1000 runs 1000 more. The
log goes on in the same file, cut first to the checkpoint's episode if the run was stopped mid-way.

Follow a run with `tail -f runs/.../s1/agent.out`, or summarize it while it goes:
`python3 tools/summarize_run.py runs/...`.
"""
import argparse
import datetime
import gzip
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runlog                                       # noqa: E402

CHILDREN = []          # every bridge and agent started, so Ctrl-C can stop them all
CHECKPOINT = 'checkpoint.json.gz'


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


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def snapshot_agent(dest):
    """Build the agent and copy the runnable distribution: the batch runs this copy."""
    subprocess.run([os.path.join(AGENT, 'gradlew'), '-q', 'installDist'], cwd=AGENT, check=True)
    shutil.copytree(os.path.join(AGENT, 'build', 'install', 'agent'), dest)
    return os.path.join(dest, 'bin', 'agent')


def read_checkpoint(d):
    with gzip.open(os.path.join(d, CHECKPOINT), 'rt') as f:
        c = json.load(f)
    return c['nextEpisode'], c.get('firstSuccess')


def write_meta(d, meta):
    with open(os.path.join(d, 'run.json'), 'w') as f:
        json.dump(meta, f, indent=1)


def run_seed(a, seed, batch, agent_bin, commit, lock, resume):
    d = os.path.join(batch, 's%d' % seed)
    log = os.path.join(d, 'log.jsonl.gz')
    if resume:
        with open(os.path.join(d, 'run.json')) as f:
            meta = json.load(f)
        nxt, _ = read_checkpoint(d)
        cut = runlog.cut_after(log, nxt - 1)
        for k in ('end', 'agentExit', 'bridgeExit'):
            meta.pop(k, None)
        meta['pid'] = os.getpid()
        meta.setdefault('resumes', []).append(
            {'start': now(), 'fromEpisode': nxt, 'commit': commit, 'logCut': cut or None})
        meta.update(emax=a.emax, eref=a.eref, keepEvery=a.keep_every)
        with lock:
            print('  seed %d resumes at episode %d%s' % (seed, nxt, ' (log: %s)' % cut if cut else ''),
                  flush=True)
    else:
        os.makedirs(d)
        meta = {'condition': a.condition, 'selection': a.selection, 'curiosity': a.curiosity,
                'seed': seed, 'emax': a.emax,
                'eref': a.eref, 'stepLimit': a.step_limit, 'commit': commit, 'start': now(),
                'keepEvery': a.keep_every, 'pid': os.getpid()}
    write_meta(d, meta)                             # rewritten with the end and exits
    port = free_port()
    ckpt = os.path.join(d, CHECKPOINT)
    with open(os.path.join(d, 'bridge.out'), 'a' if resume else 'w') as bout, \
            open(os.path.join(d, 'agent.out'), 'a' if resume else 'w') as aout:
        bridge = subprocess.Popen(
            [sys.executable, BRIDGE, '--launch', 'headless', '--port', str(port),
             '--step-limit', str(meta['stepLimit']), '--log', log, '--condition', meta['condition']]
            + (['--log-append'] if resume else []), stdout=bout, stderr=subprocess.STDOUT)
        CHILDREN.append(bridge)
        agent = subprocess.Popen(
            [agent_bin, '--port', str(port), '--condition', meta['condition'], '--seed', str(seed),
             '--emax', str(a.emax), '--eref', str(a.eref), '--selection', meta['selection'],
             '--checkpoint', ckpt, '--keep-every', str(a.keep_every)]
            # Batches from before --curiosity have no such key, and their agent no such flag.
            + (['--curiosity', meta['curiosity']] if 'curiosity' in meta else [])
            + (['--resume', ckpt] if resume else []), stdout=aout, stderr=subprocess.STDOUT)
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
    meta['end'] = now()
    write_meta(d, meta)
    with lock:
        print('  seed %d done: agent exit %s, bridge exit %s -> %s'
              % (seed, meta['agentExit'], meta['bridgeExit'], d), flush=True)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, TypeError):
        return False
    except PermissionError:
        return True


def resumable(a, batch):
    """The seeds of a batch to resume; refuses what cannot continue."""
    seeds = a.seeds or sorted(int(s[1:]) for s in os.listdir(batch)
                              if s.startswith('s') and s[1:].isdigit())
    out = []
    for seed in seeds:
        d = os.path.join(batch, 's%d' % seed)
        with open(os.path.join(d, 'run.json')) as f:
            meta = json.load(f)
        if 'end' not in meta and alive(meta.get('pid')):
            raise SystemExit('%s is still running (run_live.py pid %s): stop it first, or two runs '
                             'would write one log' % (d, meta['pid']))
        if not os.path.isfile(os.path.join(d, CHECKPOINT)):
            raise SystemExit('%s has no %s: it ran before checkpoints existed, or never finished '
                             'an episode' % (d, CHECKPOINT))
        nxt, first = read_checkpoint(d)
        end = a.emax if first is None else first + a.eref + 1
        if nxt >= end:
            print('  seed %d: nothing to do, at episode %d and %s' % (
                seed, nxt, 'E_max is %d' % a.emax if first is None
                else 'refinement ends at %d' % (end - 1)))
            continue
        out.append(seed)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--condition', help='default C0')
    ap.add_argument('--selection', help='default ucb')
    ap.add_argument('--curiosity', help='Curiosity yield: none, count, count:<W>, lp, lp:<W>; '
                                        'default none (Task cannot take the goal: CUR-01)')
    ap.add_argument('--seeds', type=int, nargs='+', help='default 1; with --resume, every seed')
    ap.add_argument('--emax', type=int, default=1000, help='Phase 1 episodes at most, in total')
    ap.add_argument('--eref', type=int, default=0, help='Phase 2 episodes after a first success')
    ap.add_argument('--step-limit', type=int, help='default 500')
    ap.add_argument('--keep-every', type=int, default=100,
                    help='also keep a checkpoint every N episodes (0: only the last)')
    ap.add_argument('--jobs', type=int, default=None,
                    help='runs at once (default: all seeds); each takes ~1.5 cores')
    ap.add_argument('--tag', default='', help='appended to the batch folder name')
    ap.add_argument('--resume', metavar='BATCH', help='continue this batch from its checkpoints')
    a = ap.parse_args()

    commit = git_commit()
    if a.resume:
        if a.condition or a.selection or a.curiosity or a.step_limit or a.tag:
            ap.error('--resume continues a batch with its own condition, selection, curiosity and '
                     'step limit')
        batch = os.path.abspath(a.resume)
        agent_bin = os.path.join(batch, 'agent', 'bin', 'agent')
        seeds = resumable(a, batch)
        print('resuming %s (code now %s; the agent is the batch\'s own copy)' % (batch, commit),
              flush=True)
    else:
        a.condition, a.selection = a.condition or 'C0', a.selection or 'ucb'
        a.curiosity = a.curiosity or 'none'
        a.step_limit, seeds = a.step_limit or 500, a.seeds or [1]
        name = '%s_%s_%s%s%s' % (datetime.datetime.now().strftime('%Y-%m-%d_%H%M'), a.condition,
                                 a.selection, '' if a.curiosity == 'none' else '_' + a.curiosity,
                                 '_' + a.tag if a.tag else '')
        # The agent snapshot's classpath runs through this folder, and ':' splits a classpath:
        # --selection ucb:0.1 left java unable to find agent.AgentMain.
        name = name.replace(':', '-')
        batch = os.path.join(ROOT, 'runs', name)
        os.makedirs(batch)
        print('batch %s (code %s)' % (batch, commit), flush=True)
        agent_bin = snapshot_agent(os.path.join(batch, 'agent'))

    lock = threading.Lock()
    jobs = a.jobs or max(1, len(seeds))
    pending = list(seeds)
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
                t = threading.Thread(target=run_seed, daemon=True,
                                     args=(a, seed, batch, agent_bin, commit, lock, bool(a.resume)))
                t.start()
                running.append(t)
                if not a.resume:
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
        for t in running:
            t.join(10)                              # each writes its run.json end and exit codes
        print('resume with: python3 tools/run_live.py --resume %s --emax %d'
              % (os.path.relpath(batch), a.emax))
        sys.exit(130)
    print('all done in %.1f min: python3 tools/summarize_run.py %s'
          % ((time.time() - t0) / 60, os.path.relpath(batch)), flush=True)


if __name__ == '__main__':
    main()
