"""Reading run logs (translog.py format), including ones still being written.

A log is gzip JSONL: one record per step, then one terminal record per episode (`done` true, with
`episode_summary`). The bridge flushes at every episode end, so a log of a run in progress reads
cleanly up to its last finished episode; the cut tail is dropped, never half-parsed. A resumed run
appends a second gzip member (bridge.py --log-append), which gzip reads as one stream.
"""
import gzip
import json
import os
import zlib

READ_ERRORS = (EOFError, zlib.error, gzip.BadGzipFile)


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
        except READ_ERRORS:
            return                              # the stream of a run still going ends unflushed


def cut_after(path, last_episode):
    """Make the log end right after `last_episode`'s terminal record, so a run resumed from the
    checkpoint taken after that episode can append from the next one.

    Returns '' when the log already ends there, cleanly. Otherwise rewrites it without what came
    after -- an episode the bridge logged before the agent could checkpoint it, an episode cut
    short when the run was stopped, a stream left unfinished -- and says what went.
    """
    opener = gzip.open if path.endswith('.gz') else open
    last_done, after, clean = None, 0, True
    with opener(path, 'rt') as f:
        try:
            for line in f:
                r = json.loads(line)
                if r['episode'] > last_episode:
                    after += 1
                elif r.get('done'):
                    last_done = r['episode']
        except (json.JSONDecodeError,) + READ_ERRORS:
            clean = False
    if last_done != last_episode:
        raise SystemExit('%s: the log has episodes up to %s, the checkpoint is after episode %d: '
                         'they do not belong together' % (path, last_done, last_episode))
    if clean and not after:
        return ''
    tmp = path + '.cut'
    with opener(path, 'rt') as f, (gzip.open(tmp, 'wt', compresslevel=6) if path.endswith('.gz')
                                   else open(tmp, 'w')) as out:
        for line in f:
            r = json.loads(line)
            if r['episode'] > last_episode:
                break
            out.write(line)
            if r['episode'] == last_episode and r.get('done'):
                break
    os.replace(tmp, path)
    return 'dropped %d records after episode %d%s' % (
        after, last_episode, '' if clean else ' and an unfinished tail')


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
