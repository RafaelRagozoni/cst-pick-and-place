"""BRG-02: the simulation bridge server.

cap4 4.5: "a thin simulation bridge: a small service that owns the CoppeliaSim connection and
exposes a structured interface to the Java HECs. Each cycle the MotorHEC sends the command records,
the bridge applies them and steps the simulation exactly once, and the sensory HECs read back joint
states and object poses."

That is exactly this. One round trip per control cycle: command records in, one simulation step,
the full observation back. **CST drives the clock** -- the bridge never steps on its own, never runs
an episode loop, and holds no task logic. Everything task-shaped (the goal step list, success) is
computed from the observation by the same pure functions the Python side uses, and returned; the
agent is free to ignore them.

The bridge also owns the **environment rules** -- notably the grasp predicate (SIM-04). The agent
opens and closes the gripper; the environment decides when the cube is attached. No habit can reach
that decision, which is what keeps the C1 ablation meaningful.

Transport is ZeroMQ REQ/REP with JSON bodies (DEC-03). It is deliberately confined to `serve()`:
the whole request handler is a plain dict-in/dict-out function, so swapping the transport is one
function, not a redesign.

    python3 bridge.py [--port 5555] [--mode fixed|annulus] [--step-limit 500]
"""
import argparse
import json
import traceback

import zmq

import simconfig
from actions import Actuator, primitive_repertoire, record_id
from episode import EpisodeReset
from goals import GoalTracker, STEPS, succeeded
from grasp_rule import GraspRule
from observations import Observer

PROTOCOL_VERSION = 1
DEFAULT_PORT = 5555


class Bridge:
    """Owns the simulator. Plain methods -- no transport in here."""

    def __init__(self, sim, simIK=None, mode='fixed', step_limit=500, manipulability=True):
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
        self.warmed = False

    # --- operations ------------------------------------------------------
    def ping(self):
        return {'protocol': PROTOCOL_VERSION, 'physics': simconfig.physics_signature(self.sim)}

    def info(self):
        """Everything the agent needs to build its primary repertoire and read the goal list."""
        return {
            'protocol': PROTOCOL_VERSION,
            'primitives': [{'id': record_id(h[0]), 'records': h} for h in primitive_repertoire()],
            'goalSteps': list(STEPS),
            'stepLimit': self.step_limit,
            'physics': simconfig.physics_signature(self.sim),
        }

    def reset(self, seed, episode):
        # One discarded reset per process, for the same reason run() does it: a reset is
        # history-independent only from the second one onward (SIM-08).
        if not self.warmed:
            self.reset_ctl.reset(seed, episode)
            self.warmed = True
        placement = self.reset_ctl.reset(seed, episode)
        self.tracker.reset()
        self.steps = 0
        obs = self.obs.read()
        return {'obs': obs, 'placement': placement, 'goal': self._goal(obs, None),
                'success': False, 'done': False, 'step': 0}

    def step(self, records):
        """Apply one cycle's records, advance the simulation exactly once, return the result."""
        self.actuator.apply(records)
        self.sim.step()
        self.steps += 1
        obs = self.obs.read()
        fired = self.tracker.update(obs)
        success = succeeded(obs)
        done = success or self.steps >= self.step_limit
        return {'obs': obs, 'goal': self._goal(obs, fired), 'success': success,
                'done': done, 'step': self.steps}

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
                return dict(ok=True, **self.step(recs))
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
    ap.add_argument('--sim-port', type=int, default=23000)
    ap.add_argument('--no-manipulability', action='store_true')
    a = ap.parse_args()

    c = RemoteAPIClient(port=a.sim_port)
    sim, simIK = c.require('sim'), c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))

    bridge = Bridge(sim, simIK, mode=a.mode, step_limit=a.step_limit,
                    manipulability=not a.no_manipulability)
    serve(bridge, a.port)
    sim.stopSimulation()


if __name__ == '__main__':
    main()
