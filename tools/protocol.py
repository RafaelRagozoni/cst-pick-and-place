"""Protocol batches (vault spec BAS-01): what "the same code" means, and the refusals that hold it.

A protocol batch is one the baseline track can use. Its budgets, seeds, selection, Curiosity and
step limit come only from a versioned protocol file (bench/P1.json), never from the command line;
it starts only from a clean tree, the CST submodule and the scene included; and it resumes only
with the fingerprint it started with. run_live.py --protocol applies these; a batch without
--protocol (a smoke) is free of all of them and records its fingerprint anyway.

The fingerprint is everything that decides a run's behaviour and is not in its arguments: the
repository's commit and what is uncommitted, the CST submodule's commit, the scene the bridge loads,
the success test, the protocol file, the CoppeliaSim install, Java and Python. The agent writes the
rest -- its effective Config and the bridge's handshake -- to agent.json (AgentMain --describe).
"""
import hashlib
import json
import os
import platform
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, 'coppelia_environment')
SCENE = os.path.join('coppelia_environment', 'pick_and_place.ttt')
LIBS = ('libcoppeliaSim.so', 'libcoppeliaSimHeadless.so')

# What a protocol file holds; every key is required. Optional: 'note'; 'theta', the success rate
# M2's time to threshold counts to; and 'primary', the one metric that decides a comparison
# (bench.py compare), one of PRIMARY. P1 fixes both from the pilot, before its batch runs.
KEYS = ('protocol', 'successTest', 'conditions', 'selection', 'curiosity', 'seeds', 'emax', 'eref',
        'stepLimit')
OPTIONAL = ('note', 'theta', 'primary')
PRIMARY = ('m1', 'm2_final', 'm3_steps', 'm4_bins_p2')
# run_live.py arguments a protocol fixes: given on the command line, they are refused.
FIXED = ('selection', 'curiosity', 'seeds', 'emax', 'eref', 'step_limit')


class Refused(Exception):
    """A protocol rule says no; the message says what to change."""


def git(root, *args):
    r = subprocess.run(['git', '-C', root] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('git %s in %s: %s' % (' '.join(args), root, r.stderr.strip()))
    return r.stdout.rstrip()                         # porcelain lines start with a space


def dirty(root=ROOT):
    """What is not committed, as `git status --porcelain` lines: the tree, the scene and the CST
    submodule's own files (a submodule moved to another commit shows as ' M cst')."""
    lines = git(root, 'status', '--porcelain', '--ignore-submodules=none').splitlines()
    cst = os.path.join(root, 'cst')
    if os.path.exists(os.path.join(cst, '.git')):
        lines += ['cst: ' + l for l in git(cst, 'status', '--porcelain').splitlines()]
    return lines


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def success_test():
    """goals.SUCCESS_TEST, the version of the success test the bridge in this tree runs."""
    sys.path.insert(0, ENV)
    try:
        import goals
    finally:
        sys.path.remove(ENV)
    return goals.SUCCESS_TEST


def coppelia():
    """The CoppeliaSim install bridge.py --launch finds, and a hash of its libraries."""
    sys.path.insert(0, ENV)
    try:
        import simprocess
        root = simprocess.find_root()
    finally:
        sys.path.remove(ENV)
    return {'root': root, 'libs': {l: sha256(os.path.join(root, l)) for l in LIBS
                                   if os.path.isfile(os.path.join(root, l))}}


def java_version():
    """The first line of `java -version`, from the java the agent's start script picks."""
    home = os.environ.get('JAVA_HOME')
    java = os.path.join(home, 'bin', 'java') if home else 'java'
    try:
        r = subprocess.run([java, '-version'], capture_output=True, text=True)
    except OSError as e:
        return 'unknown: %s' % e
    return (r.stderr or r.stdout).splitlines()[0]


def fingerprint(root=ROOT, protocol_file=None, env=True):
    """The code and environment a batch runs with. `env` False leaves out CoppeliaSim, Java and
    Python (the offline tests' temporary repositories have none of them)."""
    fp = {'commit': git(root, 'rev-parse', 'HEAD'), 'dirty': dirty(root)}
    cst = os.path.join(root, 'cst')
    fp['cst'] = git(cst, 'rev-parse', 'HEAD') if os.path.exists(os.path.join(cst, '.git')) else None
    scene = os.path.join(root, SCENE)
    fp['scene'] = sha256(scene) if os.path.isfile(scene) else None
    fp['protocol'] = None if protocol_file is None else {
        'name': read_protocol(protocol_file)['protocol'], 'sha256': sha256(protocol_file)}
    if env:
        fp['successTest'] = success_test()
        fp['coppeliaSim'] = coppelia()
        fp['java'] = java_version()
        fp['python'] = platform.python_version()
    return fp


def differences(old, new):
    """What changed between two fingerprints, one line each; [] if nothing did."""
    out = []
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            out.append('%s: %s -> %s' % (k, json.dumps(old.get(k)), json.dumps(new.get(k))))
    return out


def read_protocol(path):
    """A protocol file, checked: every key present, nothing unknown, values of the right kind."""
    with open(path) as f:
        p = json.load(f)
    missing = [k for k in KEYS if k not in p]
    unknown = [k for k in p if k not in KEYS + OPTIONAL]
    if missing or unknown:
        raise Refused('%s: %s%s' % (path, 'missing ' + ', '.join(missing) if missing else '',
                                    ('; ' if missing and unknown else '')
                                    + ('unknown ' + ', '.join(unknown) if unknown else '')))
    ints = [k for k in ('emax', 'eref', 'stepLimit') if not isinstance(p[k], int) or p[k] < 0]
    if ints or not p['seeds'] or not all(isinstance(s, int) for s in p['seeds']) \
            or not p['conditions']:
        raise Refused('%s: emax, eref and stepLimit are whole numbers >= 0, seeds and conditions '
                      'non-empty lists%s' % (path, ' (not: %s)' % ', '.join(ints) if ints else ''))
    if 'primary' in p and p['primary'] not in PRIMARY:
        raise Refused('%s: primary is one of %s, not %s' % (path, ', '.join(PRIMARY), p['primary']))
    if 'theta' in p and not (isinstance(p['theta'], (int, float)) and 0 < p['theta'] <= 1):
        raise Refused('%s: theta is a success rate in (0, 1], not %s' % (path, p['theta']))
    return p


def flag(arg):
    return '--' + arg.replace('_', '-')


def check_start(protocol, path, condition, given, dirt, test):
    """Refuse a protocol batch that cannot start: `given` the FIXED arguments set on the command
    line, `dirt` dirty(), `test` the tree's success test."""
    if given:
        raise Refused('%s fixes %s: drop %s from the command line, or write a new protocol version'
                      % (path, ' '.join(flag(k) for k in FIXED), ' '.join(flag(g) for g in given)))
    if condition is None or condition not in protocol['conditions']:
        raise Refused('%s runs --condition %s; got %s' % (path, ' or '.join(protocol['conditions']),
                                                          condition))
    if protocol['successTest'] != test:
        raise Refused('%s was written for success test %s, and this tree runs %s: a new test is a '
                      'new protocol version' % (path, protocol['successTest'], test))
    if dirt:
        raise Refused('a protocol batch starts from a clean tree (scene and cst included); commit '
                      'or stash:\n  ' + '\n  '.join(dirt))


def check_resume(meta, now, given):
    """Refuse resuming a protocol batch with other code, or with budgets from the command line.
    `meta` a seed's run.json, `now` this tree's fingerprint (with the batch's protocol file)."""
    if given:
        raise Refused('a protocol batch resumes with its own protocol: drop %s'
                      % ' '.join(flag(g) for g in given))
    if now['dirty']:
        raise Refused('a protocol batch resumes from a clean tree; commit or stash:\n  '
                      + '\n  '.join(now['dirty']))
    diff = differences(meta['fingerprint'], now)
    if diff:
        raise Refused('the batch started with another fingerprint; resuming would mix two codes in '
                      'one run:\n  ' + '\n  '.join(diff))
