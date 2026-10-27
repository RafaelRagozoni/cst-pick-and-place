"""A CoppeliaSim process owned by one run: `bridge.py --launch` starts one and stops it at the end.

No CoppeliaSim to open by hand, nothing left running after a run, and each process on its own free
ports (ZMQ and WebSocket remote API), so a launched run never meets a CoppeliaSim the user has open
and several runs can go side by side.

What it does NOT give is reproducibility under Bullet. Bullet contacts are not deterministic across
processes: six fresh processes closing the gripper on nothing gave three different physics (parting
at the finger contact by ~3e-5), with address randomization off and Python's hash seed fixed alike;
under MuJoCo, ODE or Newton all six were identical (test_fresh_process.py, agent/README "Risks").

The install is found from --coppelia-root, else $COPPELIASIM_ROOT (the variable CoppeliaSim's own
tooling uses), else the one ~/CoppeliaSim* directory if there is exactly one.
"""
import fcntl
import glob
import os
import signal
import socket
import subprocess
import tempfile
import time

# Held while one CoppeliaSim starts, by every SimProcess of this user (SimProcess.start).
START_LOCK = os.path.join(tempfile.gettempdir(), 'coppeliasim-start-%d.lock' % os.getuid())

def find_root(explicit=None):
    root = explicit or os.environ.get('COPPELIASIM_ROOT')
    if root:
        if not os.path.isfile(os.path.join(root, 'coppeliaSim.sh')):
            raise RuntimeError('no coppeliaSim.sh in %s' % root)
        return root
    found = glob.glob(os.path.expanduser('~/CoppeliaSim*/coppeliaSim.sh'))
    if len(found) != 1:
        raise RuntimeError('set COPPELIASIM_ROOT or pass --coppelia-root (found %d installs '
                           'under ~/CoppeliaSim*)' % len(found))
    return os.path.dirname(found[0])


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _listening(port):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(('127.0.0.1', port)) == 0


class SimProcess:
    """A CoppeliaSim process owned by one run. Use as a context manager: it is always stopped."""

    def __init__(self, root=None, gui=False, rpc_port=None):
        self.root = find_root(root)
        self.gui = gui
        self.rpc_port = rpc_port or free_port()
        self.proc = None
        self.log = tempfile.NamedTemporaryFile('w+', prefix='coppeliasim_', suffix='.log',
                                               delete=False)

    def start(self, timeout=90):
        """Start CoppeliaSim and wait for its remote API port; `timeout` counts once it is our turn.

        One start at a time on this machine (START_LOCK): at startup CoppeliaSim deletes the old
        folders in ~/.config/.CoppeliaSim/autoSavedScenes, and processes starting together delete
        the same folder and abort ("cannot remove all: No such file or directory"). Every launched
        process leaves its folder there, being stopped by a signal, so the first batch after some
        days without runs met it: 3 of 9 aborted on 2026-10-27, the other 6 did not open their port
        in 90 s. 40 planted folders of 9 MB each, aged 8 days, made 6 of 9 abort without the lock
        and none with it. A CoppeliaSim opened by hand does not take the lock.
        """
        with open(START_LOCK, 'w') as start_lock:
            # flock rather than a lock file of our own: the kernel lets go when the holder dies,
            # however it dies, so a crashed run cannot leave the next one waiting forever.
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            if _listening(self.rpc_port):
                # Waiting for the port would "succeed" at once, against whatever holds it.
                raise RuntimeError('port %d is already in use' % self.rpc_port)
            cmd = [os.path.join(self.root, 'coppeliaSim.sh')]
            if not self.gui:
                cmd.append('-h')
            cmd += ['-GzmqRemoteApi.rpcPort=%d' % self.rpc_port,
                    '-GwsRemoteApi.port=%d' % free_port()]
            # stdin stays open: headless CoppeliaSim quits when its stdin closes. A new session,
            # so stop() can signal the script and the simulator it spawns together.
            self.proc = subprocess.Popen(cmd, cwd=self.root, stdin=subprocess.PIPE,
                                         stdout=self.log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
            started = time.time()
            while not _listening(self.rpc_port):
                if self.proc.poll() is not None:
                    raise RuntimeError('CoppeliaSim exited at startup:\n' + self.tail())
                if time.time() - started > timeout:
                    self.stop()
                    raise RuntimeError('CoppeliaSim did not open port %d in %d s:\n%s'
                                       % (self.rpc_port, timeout, self.tail()))
                time.sleep(0.2)
        return self

    def stop(self, timeout=15):
        """SIGTERM, then SIGKILL, to the whole process group, until every member is gone.

        Waiting for the launcher script is not enough: it exits on SIGTERM while the simulator it
        spawned, if stuck mid-simulation, ignores the signal and keeps the port.
        """
        if self.proc is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if self._group_gone():
                return
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                return
            t0 = time.time()
            while time.time() - t0 < timeout:
                if self._group_gone():
                    return
                time.sleep(0.1)
        raise RuntimeError('CoppeliaSim (process group %d) survived SIGKILL' % self.proc.pid)

    def _group_gone(self):
        self.proc.poll()                     # reap the script, or it lingers as a zombie member
        try:
            os.killpg(self.proc.pid, 0)
            return False
        except ProcessLookupError:
            return True

    def close(self):
        """Stop the process and drop its console log."""
        self.stop()
        if os.path.exists(self.log.name):
            os.unlink(self.log.name)

    def tail(self, n=20):
        self.log.flush()
        with open(self.log.name) as f:
            return ''.join(f.readlines()[-n:])

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
