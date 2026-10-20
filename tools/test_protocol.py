"""Offline checks of protocol.py: the refusals that keep a baseline batch on one code (BAS-01).

Each check runs against a throwaway git repository with a scene file and a submodule standing in
for cst, so nothing here touches this repository, CoppeliaSim or a running batch.

    python3 tools/test_protocol.py
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocol                                     # noqa: E402
import run_live                                     # noqa: E402

FAILS = []
PROTOCOL = {'protocol': 'PT', 'successTest': 'S3', 'conditions': ['C0', 'C4'],
            'selection': 'ucb:0.1', 'curiosity': 'lp', 'seeds': [1, 2], 'emax': 10, 'eref': 5,
            'stepLimit': 500}


def check(name, ok):
    print('  %-62s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def refused(fn, *args, says=''):
    """True if fn(*args) refuses, with `says` in its message."""
    try:
        fn(*args)
    except protocol.Refused as e:
        return says in str(e)
    return False


def sh(cwd, *cmd):
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t',
                    '-c', 'protocol.file.allow=always'] + list(cmd),
                   cwd=cwd, check=True, capture_output=True)


def repo(tmp):
    """A repository like this one: a tracked scene and a cst submodule, all committed."""
    sub = os.path.join(tmp, 'cst-origin')
    os.makedirs(sub)
    sh(sub, 'init', '-q')
    with open(os.path.join(sub, 'Idea.java'), 'w') as f:
        f.write('class Idea {}\n')
    sh(sub, 'add', '.')
    sh(sub, 'commit', '-qm', 'cst')
    root = os.path.join(tmp, 'sim')
    os.makedirs(os.path.join(root, 'coppelia_environment'))
    sh(root, 'init', '-q')
    with open(os.path.join(root, protocol.SCENE), 'wb') as f:
        f.write(b'scene v1')
    sh(root, 'submodule', 'add', '-q', sub, 'cst')
    sh(root, 'add', '.')
    sh(root, 'commit', '-qm', 'sim')
    return root


def main():
    tmp = tempfile.mkdtemp()
    try:
        root = repo(tmp)
        check('a committed tree is clean, cst included', protocol.dirty(root) == [])
        start = protocol.fingerprint(root, env=False)
        check('the fingerprint has the commit, cst and the scene',
              len(start['commit']) == 40 and len(start['cst']) == 40 and len(start['scene']) == 64)

        p = os.path.join(tmp, 'PT.json')
        with open(p, 'w') as f:
            json.dump(PROTOCOL, f)
        good = protocol.read_protocol(p)
        clean = (good, p, 'C4', [], [], 'S3')
        try:
            protocol.check_start(*clean)
            check('a clean tree, the right condition and test: it starts', True)
        except protocol.Refused as e:
            check('a clean tree, the right condition and test: it starts (%s)' % e, False)

        # Rule 1: the tree, the scene and cst.
        with open(os.path.join(root, protocol.SCENE), 'wb') as f:
            f.write(b'scene v2')
        dirt = protocol.dirty(root)
        check('a modified scene is dirty', any('pick_and_place.ttt' in l for l in dirt))
        check('  ... and refused at the start',
              refused(protocol.check_start, good, p, 'C4', [], dirt, 'S3', says='pick_and_place'))
        sh(root, 'checkout', '-q', '--', protocol.SCENE)
        with open(os.path.join(root, 'cst', 'Idea.java'), 'a') as f:
            f.write('// edited\n')
        dirt = protocol.dirty(root)
        check('an edit inside cst is dirty, and says where',
              any(l.startswith('cst: ') and 'Idea.java' in l for l in dirt))
        check('  ... and refused at the start',
              refused(protocol.check_start, good, p, 'C4', [], dirt, 'S3', says='Idea.java'))
        sh(os.path.join(root, 'cst'), 'checkout', '-q', '--', 'Idea.java')
        with open(os.path.join(root, 'notes.txt'), 'w') as f:
            f.write('x')
        check('an untracked file is dirty', any('notes.txt' in l for l in protocol.dirty(root)))
        os.remove(os.path.join(root, 'notes.txt'))
        check('back to clean', protocol.dirty(root) == [])

        # Rule 2: the protocol file, not the command line.
        check('--emax on the command line is refused',
              refused(protocol.check_start, good, p, 'C4', ['emax'], [], 'S3', says='--emax'))
        check('--step-limit is named as the flag it is',
              refused(protocol.check_start, good, p, 'C4', ['step_limit'], [], 'S3',
                      says='--step-limit'))
        check('a condition the protocol does not list is refused',
              refused(protocol.check_start, good, p, 'C6', [], [], 'S3', says='C0 or C4'))
        check('no --condition is refused', refused(protocol.check_start, good, p, None, [], [], 'S3'))
        check('another success test in the tree is refused',
              refused(protocol.check_start, good, p, 'C4', [], [], 'S4', says='S4'))
        for name, change in (('a missing key', lambda d: d.pop('eref')),
                             ('an unknown key', lambda d: d.update(emx=3)),
                             ('a negative budget', lambda d: d.update(emax=-1)),
                             ('no seeds', lambda d: d.update(seeds=[]))):
            bad = dict(PROTOCOL)
            change(bad)
            with open(p, 'w') as f:
                json.dump(bad, f)
            check('a protocol file with %s is refused' % name, refused(protocol.read_protocol, p))
        with open(p, 'w') as f:
            json.dump(PROTOCOL, f)

        # Rule 4: resume with the fingerprint it started with.
        meta = {'fingerprint': protocol.fingerprint(root, p, env=False)}
        same = protocol.fingerprint(root, p, env=False)
        try:
            protocol.check_resume(meta, same, [])
            check('the same code resumes', True)
        except protocol.Refused as e:
            check('the same code resumes (%s)' % e, False)
        check('--eref on a protocol resume is refused',
              refused(protocol.check_resume, meta, same, ['eref'], says='--eref'))
        with open(os.path.join(root, 'bridge.py'), 'w') as f:
            f.write('# the bridge changed\n')
        check('a resume from a dirty tree is refused',
              refused(protocol.check_resume, meta, protocol.fingerprint(root, p, env=False), [],
                      says='bridge.py'))
        sh(root, 'add', 'bridge.py')
        sh(root, 'commit', '-qm', 'bridge')
        check('a resume on another commit is refused, and says what changed',
              refused(protocol.check_resume, meta, protocol.fingerprint(root, p, env=False), [],
                      says='commit:'))
        edited = dict(PROTOCOL, eref=6)
        with open(p, 'w') as f:
            json.dump(edited, f)
        later = dict(protocol.fingerprint(root, p, env=False), commit=meta['fingerprint']['commit'])
        check('a resume after the protocol file was edited is refused',
              refused(protocol.check_resume, meta, later, [], says='protocol:'))

        # Without --protocol, resuming keeps the batch's own budgets.
        a = argparse.Namespace(emax=None, eref=None)
        check('a resume without --emax or --eref keeps the batch\'s own',
              run_live.budgets(a, {'emax': 2000, 'eref': 500}) == (2000, 500))
        a.emax = 3000
        check('--emax on a resume is a new total; E_ref stays',
              run_live.budgets(a, {'emax': 2000, 'eref': 500}) == (3000, 500))
    finally:
        shutil.rmtree(tmp)

    real = os.path.join(protocol.ROOT, 'bench', 'P0.json')
    check('bench/P0.json reads, for the success test this tree runs',
          protocol.read_protocol(real)['successTest'] == protocol.success_test())

    print('\nprotocol: %s' % ('PASS' if not FAILS else 'FAIL (%d)' % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
