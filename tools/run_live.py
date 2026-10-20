"""Run the agent live, headless, one independent run per seed, in parallel.

    python3 tools/run_live.py --condition C0 --selection ucb --seeds 1 2 3 --emax 1000
    python3 tools/run_live.py --selection ucb:0.1 --curiosity count --seeds 1 2 3 --emax 200
    python3 tools/run_live.py --resume runs/<batch> --emax 2000       # continue it to 2000
    python3 tools/run_live.py --protocol bench/P1.json --condition C4   # a baseline batch (BAS-01)

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
    s<seed>/run.json       arguments, git commit, fingerprint, start and end, exit codes, resumes
    s<seed>/agent.json     the agent's effective Config and the bridge's handshake (AgentMain --describe)
    protocol.json          with --protocol: a copy of the protocol file the batch runs

--resume continues every seed of a batch (or --seeds) from its checkpoint, with the batch's own agent
snapshot and settings; --emax and --eref are totals, so --emax 2000 after 1000 runs 1000 more, and
either one left out keeps the batch's own. The log goes on in the same file, cut first to the
checkpoint's episode if the run was stopped mid-way.

--protocol FILE runs a protocol batch (vault spec BAS-01, tools/protocol.py): selection, Curiosity,
seeds, E_max, E_ref and step limit come from the file and cannot be given, --condition must be one it
lists, and the tree must be clean, scene and cst included. Resuming one refuses another fingerprint
and any budget. Without --protocol nothing is refused, and the fingerprint is recorded all the same.

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
import protocol                                     # noqa: E402
import runlog                                       # noqa: E402

CHILDREN = []          # every bridge and agent started, so Ctrl-C can stop them all
CHECKPOINT = 'checkpoint.json.gz'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def git_commit(fp):
    """The short commit, -dirty if anything is uncommitted: any file, the scene, or cst."""
    return fp['commit'][:7] + ('-dirty' if fp['dirty'] else '')


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


def budgets(a, meta):
    """E_max and E_ref for resuming a seed: the command line's, else the seed's own. A default here
    would change the protocol silently: --eref 0 cut every batch at its first success once."""
    return (meta['emax'] if a.emax is None else a.emax,
            meta['eref'] if a.eref is None else a.eref)


def run_seed(a, seed, batch, agent_bin, fp, lock, resume):
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
            {'start': now(), 'fromEpisode': nxt, 'commit': git_commit(fp), 'logCut': cut or None,
             'fingerprint': fp})
        emax, eref = budgets(a, meta)
        meta.update(emax=emax, eref=eref, keepEvery=a.keep_every)
        with lock:
            print('  seed %d resumes at episode %d%s' % (seed, nxt, ' (log: %s)' % cut if cut else ''),
                  flush=True)
    else:
        os.makedirs(d)
        meta = {'condition': a.condition, 'selection': a.selection, 'curiosity': a.curiosity,
                'seed': seed, 'emax': a.emax,
                'eref': a.eref, 'stepLimit': a.step_limit, 'commit': git_commit(fp),
                'protocol': fp['protocol'] and fp['protocol']['name'], 'fingerprint': fp,
                'start': now(), 'keepEvery': a.keep_every, 'pid': os.getpid()}
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
             '--emax', str(meta['emax']), '--eref', str(meta['eref']),
             '--selection', meta['selection'], '--checkpoint', ckpt, '--keep-every', str(a.keep_every)]
            # Batches from before --curiosity have no such key, and their agent no such flag.
            + (['--curiosity', meta['curiosity']] if 'curiosity' in meta else [])
            + (['--resume', ckpt] if resume else ['--describe', os.path.join(d, 'agent.json')]),
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
        emax, eref = budgets(a, meta)
        end = emax if first is None else first + eref + 1
        if nxt >= end:
            print('  seed %d: nothing to do, at episode %d and %s' % (
                seed, nxt, 'E_max is %d' % emax if first is None
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
    ap.add_argument('--emax', type=int, help='Phase 1 episodes at most, in total; default 1000, '
                                             'or with --resume the batch\'s own')
    ap.add_argument('--eref', type=int, help='Phase 2 episodes after a first success; default 0, '
                                             'or with --resume the batch\'s own')
    ap.add_argument('--step-limit', type=int, help='default 500')
    ap.add_argument('--keep-every', type=int, default=100,
                    help='also keep a checkpoint every N episodes (0: only the last)')
    ap.add_argument('--jobs', type=int, default=None,
                    help='runs at once (default: all seeds); each takes ~1.5 cores')
    ap.add_argument('--tag', default='', help='appended to the batch folder name')
    ap.add_argument('--resume', metavar='BATCH', help='continue this batch from its checkpoints')
    ap.add_argument('--protocol', metavar='FILE',
                    help='a protocol batch: budgets, seeds and agent settings from FILE (BAS-01)')
    a = ap.parse_args()

    try:
        if a.resume:
            if a.condition or a.selection or a.curiosity or a.step_limit or a.tag or a.protocol:
                ap.error('--resume continues a batch with its own condition, selection, curiosity, '
                         'step limit and protocol')
            batch = os.path.abspath(a.resume)
            agent_bin = os.path.join(batch, 'agent', 'bin', 'agent')
            p_file = os.path.join(batch, 'protocol.json')
            fp = protocol.fingerprint(protocol_file=p_file if os.path.isfile(p_file) else None)
            if fp['protocol']:
                given = [k for k in ('emax', 'eref') if getattr(a, k) is not None]
                outside = sorted(set(a.seeds or []) - set(protocol.read_protocol(p_file)['seeds']))
                if outside:
                    raise protocol.Refused('seeds %s are not in the batch\'s protocol' % outside)
                runs = sorted(d for d in os.listdir(batch) if d.startswith('s') and d[1:].isdigit())
                with open(os.path.join(batch, runs[0], 'run.json')) as f:
                    protocol.check_resume(json.load(f), fp, given)
            seeds = resumable(a, batch)
            print('resuming %s (code now %s; the agent is the batch\'s own copy)'
                  % (batch, git_commit(fp)), flush=True)
        else:
            p = None
            if a.protocol:
                p = protocol.read_protocol(a.protocol)
                given = [k for k in protocol.FIXED if getattr(a, k) is not None]
                protocol.check_start(p, a.protocol, a.condition, given, protocol.dirty(),
                                     protocol.success_test())
                a.selection, a.curiosity, a.seeds = p['selection'], p['curiosity'], p['seeds']
                a.emax, a.eref, a.step_limit = p['emax'], p['eref'], p['stepLimit']
                a.tag = a.tag or p['protocol']
            fp = protocol.fingerprint(protocol_file=a.protocol)
    except protocol.Refused as e:
        sys.exit('refused: %s' % e)

    if not a.resume:
        a.condition, a.selection = a.condition or 'C0', a.selection or 'ucb'
        a.curiosity = a.curiosity or 'none'
        a.step_limit, seeds = a.step_limit or 500, a.seeds or [1]
        a.emax = 1000 if a.emax is None else a.emax
        a.eref = 0 if a.eref is None else a.eref
        name = '%s_%s_%s%s%s' % (datetime.datetime.now().strftime('%Y-%m-%d_%H%M'), a.condition,
                                 a.selection, '' if a.curiosity == 'none' else '_' + a.curiosity,
                                 '_' + a.tag if a.tag else '')
        # The agent snapshot's classpath runs through this folder, and ':' splits a classpath:
        # --selection ucb:0.1 left java unable to find agent.AgentMain.
        name = name.replace(':', '-')
        batch = os.path.join(ROOT, 'runs', name)
        os.makedirs(batch)
        print('batch %s (code %s%s)' % (batch, git_commit(fp),
                                        ', protocol %s' % p['protocol'] if p else ''), flush=True)
        if p:
            shutil.copy(a.protocol, os.path.join(batch, 'protocol.json'))
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
                                     args=(a, seed, batch, agent_bin, fp, lock, bool(a.resume)))
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
        print('resume with: python3 tools/run_live.py --resume %s' % os.path.relpath(batch))
        sys.exit(130)
    print('all done in %.1f min: python3 tools/summarize_run.py %s'
          % ((time.time() - t0) / 60, os.path.relpath(batch)), flush=True)


if __name__ == '__main__':
    main()
