"""Offline checks of runlog.py: reading a log still being written, and cutting one for a resume.

    python3 tools/test_runlog.py
"""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runlog                                       # noqa: E402

FAILS = []


def check(name, ok):
    print('  %-58s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def write(path, episodes, partial=None, mode='wt', unfinished=False):
    """Episodes of 3 steps and a terminal record; `partial`: one more cut short, no terminal.
    `unfinished`: flushed but never closed, as a run killed hard leaves it."""
    f = gzip.open(path, mode)
    for ep in episodes:
        for step in range(3):
            f.write(json.dumps({'episode': ep, 'step': step, 'done': False}) + '\n')
        f.write(json.dumps({'episode': ep, 'step': 3, 'done': True,
                            'episode_summary': {'steps': 3}}) + '\n')
    if partial is not None:
        f.write(json.dumps({'episode': partial, 'step': 0, 'done': False}) + '\n')
    f.flush()                                       # what the bridge does at every episode end
    if unfinished:
        shutil.copy(path, path + '.snap')           # the bytes on disk before any close
        f.close()
        shutil.move(path + '.snap', path)
    else:
        f.close()


def finished(path):
    return [ep for ep, _, _ in runlog.episodes(path)]


def main():
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'log.jsonl.gz')
    print('--- cut_after: a log made ready for a resumed run ---')

    write(p, range(3))
    before = open(p, 'rb').read()
    check('ends cleanly at the checkpoint: left as it is', runlog.cut_after(p, 2) == ''
          and open(p, 'rb').read() == before)

    write(p, range(4))
    msg = runlog.cut_after(p, 2)
    check('an episode logged past the checkpoint is dropped', finished(p) == [0, 1, 2]
          and 'dropped 4 records' in msg)

    write(p, range(3), partial=3)
    runlog.cut_after(p, 2)
    check('an episode cut short by a stop is dropped', finished(p) == [0, 1, 2]
          and sum(1 for _ in runlog.records(p)) == 12)

    write(p, range(3), partial=3, unfinished=True)
    msg = runlog.cut_after(p, 2)
    check('an unfinished stream is cut and closed', finished(p) == [0, 1, 2]
          and 'unfinished tail' in msg and runlog.cut_after(p, 2) == '')

    write(p, range(2))
    try:
        runlog.cut_after(p, 2)
        check('a log shorter than the checkpoint is refused', False)
    except SystemExit:
        check('a log shorter than the checkpoint is refused', True)

    write(p, range(3), partial=3)
    runlog.cut_after(p, 2)
    write(p, range(3, 5), mode='at')
    check('a resumed run appends: one log, episodes 0..4 in order', finished(p) == [0, 1, 2, 3, 4])

    write(p, range(5, 7), partial=7, mode='at', unfinished=True)
    check('a resumed run still going reads to its last finished episode',
          finished(p) == list(range(7)))

    shutil.rmtree(d)
    print('\nRUNLOG: %s' % ('PASS' if not FAILS else 'FAIL (%s)' % ', '.join(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
