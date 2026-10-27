"""Offline checks of SimProcess's start lock, on a fake CoppeliaSim: no simulator needed.

The fake writes when it starts and when its port opens, after a pause. Started together, real
processes would overlap; the lock must line them up, start then open, one at a time, and a start
that fails must not keep the lock.

    python3 test_simprocess.py
"""
import os
import stat
import sys
import tempfile
import threading

import simprocess

FAILS = []

FAKE = '''#!%s
import os, socket, sys, time
port = int([arg for arg in sys.argv if arg.startswith('-GzmqRemoteApi.rpcPort=')][0].split('=')[1])
with open(os.environ['FAKE_EVENTS'], 'a') as events:
    events.write('start\\n')
if os.environ.get('FAKE_CRASH'):
    sys.exit(1)
time.sleep(0.3)
server = socket.socket()
server.bind(('127.0.0.1', port))
server.listen()
with open(os.environ['FAKE_EVENTS'], 'a') as events:
    events.write('open\\n')
sys.stdin.read()
'''


def check(name, ok):
    print('  %-50s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def start_and_stop(root, outcomes, index):
    process = simprocess.SimProcess(root)
    try:
        process.start(timeout=20)
        outcomes[index] = 'ok'
    except RuntimeError as error:
        outcomes[index] = 'failed: %s' % error
    finally:
        process.close()


def start_together(root, count):
    outcomes = [None] * count
    threads = [threading.Thread(target=start_and_stop, args=(root, outcomes, i))
               for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def main():
    with tempfile.TemporaryDirectory() as root:
        script = os.path.join(root, 'coppeliaSim.sh')
        with open(script, 'w') as f:
            f.write(FAKE % sys.executable)
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        events_path = os.path.join(root, 'events')
        os.environ['FAKE_EVENTS'] = events_path

        outcomes = start_together(root, 4)
        events = open(events_path).read().split()
        check('four started together all open', outcomes == ['ok'] * 4)
        check('one start at a time: start, open, start, open, ...',
              events == ['start', 'open'] * 4)

        os.remove(events_path)
        os.environ['FAKE_CRASH'] = '1'
        crashed = start_together(root, 1)
        del os.environ['FAKE_CRASH']
        after_crash = start_together(root, 1)
        check('a start that fails lets go of the lock',
              crashed[0].startswith('failed: CoppeliaSim exited at startup')
              and after_crash == ['ok'])
    print('%d failed' % len(FAILS) if FAILS else 'all passed')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
