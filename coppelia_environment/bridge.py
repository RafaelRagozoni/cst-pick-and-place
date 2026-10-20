"""BRG-02: the simulation bridge server.

cap4 4.5: "a thin simulation bridge: a small service that owns the CoppeliaSim connection and
exposes a structured interface to the Java codelets." Each cycle the Motor codelet sends the command
records, the bridge applies them and steps the simulation exactly once, and the observation comes
back for the Sensory codelet. One round trip per control cycle: command records in, one simulation step,
the full observation back. **CST drives the clock** -- the bridge never steps on its own, never runs
an episode loop, and holds no task logic. Everything task-shaped (the goal step list, success) is
computed from the observation by the same pure functions the Python side uses, and returned; the
agent is free to ignore them.

The bridge also owns the **environment rules** -- notably the grasp predicate (SIM-04). The agent
opens and closes the gripper; the environment decides when the cube is attached. No habit can reach
that decision, which is what keeps the C1 ablation meaningful.

The bridge also **writes the run log** (translog.py), because it is the one place that sees every
observation and every command of a CST-driven run; metrics.py reduces that file. A step request may
carry an `annotate` dict -- the habit id, drive levels, the repertoire for metric 4 -- which is
logged with that step. Logging is not optional by accident: the bridge refuses to start unless it
is given either `--log` or an explicit `--no-log`, so a run that produces no data is a decision.

Transport is ZeroMQ REQ/REP with JSON bodies (DEC-03). It is deliberately confined to `serve()`:
the whole request handler is a plain dict-in/dict-out function, so swapping the transport is one
function, not a redesign.

    python3 bridge.py --launch headless --log runs/C0_s1.jsonl.gz --condition C0 [--port 5555]
    python3 bridge.py --launch gui --log ...         # the same, in a window you can watch
    python3 bridge.py --no-log                       # attach to an open CoppeliaSim, by hand

`--launch` starts a CoppeliaSim process for this run on free ports and stops it when the bridge
ends (simprocess.py); without it the bridge attaches to one already open (`--sim-port`, default
23000). Neither makes Bullet reproducible across runs: its contacts vary per process (simprocess.py).
"""
import argparse
import json
import signal
import sys
import traceback

import zmq

import simconfig
import simprocess
from actions import Actuator, joint_positions, primitive_repertoire, record_id
from episode import EpisodeReset
from goals import GoalTracker, STEPS, SUCCESS_TEST
from grasp_rule import GraspRule
from observations import Observer
from translog import EpisodeLog, check_annotation, open_log

# 2: MOVE records carry a relative `angle` (signed, the angle still to go) and a non-negative
#    `speed`; in 1 the direction was the sign of `speed` and a record lasted exactly one tick.
PROTOCOL_VERSION = 2
DEFAULT_PORT = 5555


class Bridge:
    """Owns the simulator. Plain methods -- no transport in here."""

    def __init__(self, sim, simIK=None, mode='fixed', step_limit=500, manipulability=True,
                 log_path=None, condition=None, log_append=False):
        if log_path and not condition:
            raise ValueError('a logged run needs a condition label')
        self.sim = sim
        self.step_limit = step_limit
        simconfig.pin_physics(sim)
        sim.setStepping(True)
        sim.startSimulation()
        self.grasp = GraspRule(sim)
        self.obs = Observer(sim, self.grasp, manipulability=manipulability, simIK=simIK)
        self.reset_ctl = EpisodeReset(sim, self.grasp, self.obs, mode=mode)
        self.actuator = Actuator(sim, self.reset_ctl.arm)
        self.reset_ctl.on_start = self.actuator.use_velocity_control
        self.tracker = GoalTracker()
        self.steps = 0
        self.done = True            # no episode until the first reset
        self.last_obs = None
        self.warmed = False
        self.log_path, self.condition = log_path, condition
        self.sink = open_log(log_path, 'at' if log_append else 'wt') if log_path else None
        self.episode = None         # the EpisodeLog of the episode in progress, when logging

    # --- operations ------------------------------------------------------
    def ping(self):
        return {'protocol': PROTOCOL_VERSION, 'physics': simconfig.physics_signature(self.sim)}

    def info(self):
        """Everything the agent needs to build its primary repertoire and read the goal list."""
        return {
            'protocol': PROTOCOL_VERSION,
            'primitives': [{'id': record_id(h[0]), 'records': h} for h in primitive_repertoire()],
            'goalSteps': list(STEPS),
            'successTest': SUCCESS_TEST,
            'stepLimit': self.step_limit,
            'physics': simconfig.physics_signature(self.sim),
            'log': self.log_path,
            'condition': self.condition,
        }

    def reset(self, seed, episode):
        self._close_episode(aborted=True)
        # One discarded reset per process, for the same reason run() does it: a reset is
        # history-independent only from the second one onward (SIM-08).
        if not self.warmed:
            self.reset_ctl.reset(seed, episode)
            self.warmed = True
        placement = self.reset_ctl.reset(seed, episode)
        self.tracker.reset()
        self.steps = 0
        self.done = False
        obs = self.last_obs = self.obs.read()
        if self.sink is not None:
            self.episode = EpisodeLog(self.sink, seed, episode, self.condition, obs,
                                      placement['cube'])
        return {'obs': obs, 'placement': placement, 'goal': self._goal(obs, None),
                'success': False, 'done': False, 'step': 0}

    def step(self, records, annotate=None):
        """Apply one cycle's records, advance the simulation exactly once, return the result.

        Refused outside an episode -- before the first reset, or once one is done -- so the log
        never holds steps that belong to no episode.
        """
        if self.done:
            raise RuntimeError('no episode in progress: reset first')
        check_annotation(annotate)
        self.actuator.apply(records, joint_positions(self.last_obs))
        self.sim.step()
        self.steps += 1
        obs = self.last_obs = self.obs.read()
        fired = self.tracker.update(obs)
        success = self.tracker.success
        self.done = success or self.steps >= self.step_limit
        if self.episode is not None:
            self.episode.step(records, obs, self.tracker.current, fired, success, annotate)
            if self.done:
                self._close_episode()
        return {'obs': obs, 'goal': self._goal(obs, fired), 'success': success,
                'done': self.done, 'step': self.steps}

    def _close_episode(self, aborted=False):
        """Write the episode's terminal record. `aborted`: reset or shut down before it was done."""
        if self.episode is not None:
            self.episode.close(self.tracker.current, False if aborted else self.tracker.success,
                               [t[0] for t in self.tracker.transitions], aborted=aborted)
            self.episode = None

    def close(self):
        self._close_episode(aborted=True)
        if self.sink is not None:
            self.sink.close()
            self.sink = None

    def _goal(self, obs, fired):
        return {'current': self.tracker.current, 'fired': fired,
                'reached': [t[0] for t in self.tracker.transitions]}

    # --- request handling (transport-free) -------------------------------
    def handle(self, req):
        op = req.get('op')
        try:
            if op == 'ping':
                return dict(ok=True, **self.ping())
            if op == 'info':
                return dict(ok=True, **self.info())
            if op == 'reset':
                return dict(ok=True, **self.reset(int(req['seed']), int(req['episode'])))
            if op == 'step':
                recs = req.get('records') or []
                if not isinstance(recs, list):
                    return {'ok': False, 'error': 'records must be a list'}
                note = req.get('annotate')
                if note is not None and not isinstance(note, dict):
                    return {'ok': False, 'error': 'annotate must be an object'}
                return dict(ok=True, **self.step(recs, note))
            if op == 'shutdown':
                return {'ok': True, 'bye': True}
            return {'ok': False, 'error': 'unknown op: %r' % op}
        except Exception as e:
            # Never let one bad request kill the simulation the agent is mid-episode on.
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e),
                    'traceback': traceback.format_exc(limit=3)}


def serve(bridge, port=DEFAULT_PORT):
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind('tcp://127.0.0.1:%d' % port)
    print('bridge listening on tcp://127.0.0.1:%d  (protocol %d)' % (port, PROTOCOL_VERSION),
          flush=True)
    try:
        while True:
            req = json.loads(sock.recv())
            rep = bridge.handle(req)
            sock.send_string(json.dumps(rep))
            if req.get('op') == 'shutdown':
                print('shutdown requested', flush=True)
                break
    finally:
        sock.close(0)
        ctx.term()


def main():
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    ap.add_argument('--mode', default='fixed', choices=('fixed', 'annulus'))
    ap.add_argument('--step-limit', type=int, default=500)
    ap.add_argument('--sim-port', type=int,
                    help='CoppeliaSim remote API port (default: 23000, or a free one with --launch)')
    ap.add_argument('--launch', choices=('headless', 'gui'),
                    help='start a fresh CoppeliaSim for this run and stop it at the end')
    ap.add_argument('--coppelia-root', help='CoppeliaSim install (default: $COPPELIASIM_ROOT, or '
                                            'the one ~/CoppeliaSim* directory)')
    ap.add_argument('--no-manipulability', action='store_true')
    ap.add_argument('--log', help='write the run log here (.jsonl.gz recommended)')
    ap.add_argument('--condition', help='condition label written into the log, e.g. C0')
    ap.add_argument('--no-log', action='store_true', help='run without a log, deliberately')
    ap.add_argument('--log-append', action='store_true',
                    help='add to the log instead of replacing it: a resumed run (run_live.py)')
    a = ap.parse_args()
    if bool(a.log) == a.no_log:
        ap.error('give either --log PATH (with --condition) or --no-log')
    if a.log and not a.condition:
        ap.error('--log needs --condition')

    # SIGTERM (run_live.py stopping a batch) unwinds like an exception, so the finally blocks
    # below still close the log and stop a launched CoppeliaSim instead of orphaning it.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    proc = None
    if a.launch:
        proc = simprocess.SimProcess(a.coppelia_root, gui=a.launch == 'gui', rpc_port=a.sim_port)
        proc.start()
        print('launched CoppeliaSim (%s) on port %d' % (a.launch, proc.rpc_port), flush=True)
    try:
        c = RemoteAPIClient(port=proc.rpc_port if proc else (a.sim_port or 23000))
        sim, simIK = c.require('sim'), c.require('simIK')
        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            pass
        sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'pick_and_place.ttt'))

        bridge = Bridge(sim, simIK, mode=a.mode, step_limit=a.step_limit,
                        manipulability=not a.no_manipulability, log_path=a.log,
                        condition=a.condition, log_append=a.log_append)
        try:
            serve(bridge, a.port)
        finally:
            bridge.close()
            try:
                sim.stopSimulation()
            except Exception:
                # Stopped mid-call (SIGTERM during a remote call): this client's socket is
                # unusable. Best effort only -- a launched CoppeliaSim is stopped below anyway.
                pass
    finally:
        if proc:
            proc.close()


if __name__ == '__main__':
    main()
