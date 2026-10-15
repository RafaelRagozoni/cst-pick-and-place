"""Reading run logs (translog.py format), including ones still being written.

A log is gzip JSONL: one record per step, then one terminal record per episode (`done` true, with
`episode_summary`). The bridge flushes at every episode end, so a log of a run in progress reads
cleanly up to its last finished episode; the cut tail is dropped, never half-parsed.
"""
import gzip
import json
import os
import zlib


def find_logs(paths):
    """Each path may be a log, a run folder (s1/) or a batch folder: -> [(label, log, meta)]."""
    out = []
    for p in paths:
        if os.path.isfile(p):
            name = os.path.basename(p)
            label = (os.path.basename(os.path.dirname(os.path.abspath(p)))
                     if name == 'log.jsonl.gz' else name.split('.')[0])
            out.append((label, p, _meta(os.path.dirname(p))))
        elif os.path.isfile(os.path.join(p, 'log.jsonl.gz')):
            out.append((os.path.basename(os.path.normpath(p)), os.path.join(p, 'log.jsonl.gz'),
                        _meta(p)))
        elif os.path.isdir(p):
            subs = sorted(d for d in os.listdir(p) if os.path.isfile(os.path.join(p, d, 'log.jsonl.gz')))
            if not subs:
                raise SystemExit('no log.jsonl.gz in %s or its subfolders' % p)
            out += find_logs([os.path.join(p, d) for d in subs])
        else:
            raise SystemExit('not found: %s' % p)
    return out


def _meta(folder):
    f = os.path.join(folder, 'run.json')
    if os.path.isfile(f):
        with open(f) as fh:
            return json.load(fh)
    return {}


def records(path):
    """Every complete record, in order."""
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt') as f:
        try:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    return                      # a line cut where an unfinished log stops
        except (EOFError, zlib.error):
            return                              # the stream of a run still going ends unflushed


def episodes(path):
    """(episode index, [records], summary or None) per episode. Only finished episodes."""
    current, recs = None, []
    for r in records(path):
        if r['episode'] != current:
            current, recs = r['episode'], []
        recs.append(r)
        if r.get('done'):
            yield current, recs, r.get('episode_summary')
            recs = []
