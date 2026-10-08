"""PIL-01: is the pick-and-place reachable using only the primitive repertoire?

Everything that has succeeded so far was driven by a scripted *Cartesian* expert commanding tool
poses through inverse kinematics. The agent gets none of that. It gets the primary repertoire of
cap4 4.4.1 -- joint rotations in either direction for each of the six joints, plus gripper
open/close, 14 single-record habits -- each run until its step completes (actions.StepCompletion),
as the agent will run them.

This pilot answers, before any of the habit machinery is built:

  1. is the task reachable in that action space at all (the gate cap5 sets on WP3);
  2. how many steps does the shortest sensible solution take (which is where the per-episode step
     limit, E_max and E_ref should come from, instead of the placeholders they are now);
  3. how much does moving one joint at a time cost against moving six at once -- a measured
     motivation for parallel fusion.

**Reproducibility.** The controller is deterministic: two runs produce identical primitive sequences
and identical step counts. The *trajectories* are not bit-identical, because Bullet's contact solver
diverges by ~1e-4 rad once the fingers touch the cube -- SIM-08's bit-exact result was measured on a
contact-free trajectory. That does not affect the paired statistics, which depend on both conditions
seeing the same placements (a pure function of the seed), not on exact trajectory replay.

**It is a floor, not a prediction.** The controller here follows tool-space waypoints and looks one
step ahead; the agent has neither. A step count from this run says a solution of that length exists,
not that the agent will find one. Set the episode step limit at a stated multiple of it.

Vocabulary follows cap4: the four *goal steps* are reach / grasp / transport / release
(Section 4.5) and are tracked by goals.GoalTracker. The waypoints below are *segments* of the
motion, a finer decomposition, and are deliberately named differently so the two are not conflated.

    python3 pilot.py                 # as fast as the simulator allows
    python3 pilot.py --slow 0.05     # roughly real time, for watching in the GUI
    python3 pilot.py --slow 0.15     # slow motion
    python3 pilot.py --record pilot.gif   # write an animated GIF you can just open
    python3 pilot.py --no-fit-view        # leave the GUI view alone

Two cameras are involved, and they are independent:

  * the **GUI view** -- what you see on screen. Reframed at startup with sim.cameraFitToView, which
    goes through the view itself. Setting /DefaultCamera's matrix does NOT work: the GUI writes its
    own view state back over it. Disable with --no-fit-view.
  * the **recording camera** (RunCam) -- an offscreen vision sensor used by --record. Its pose is
    CAM_EYE / CAM_AT below. Edit those to change the recorded angle.
"""
import argparse
import json
import math
import os
import random
import time

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

import simconfig
from actions import Actuator, StepCompletion, grab, primitive_repertoire, record_id
from episode import EpisodeReset
from goals import GoalTracker, succeeded
from grasp_rule import GraspRule
from observations import TABLE_TOP_Z, Observer
from translog import open_log

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')

HOVER = TABLE_TOP_Z + 0.22
GRASP_Z = 0.755
CARRY = TABLE_TOP_Z + 0.25
PLACE_Z = 0.80

ARRIVE_TOL = 0.02          # m, waypoint reached
SEGMENT_BUDGET = 4000      # steps before a segment is declared stalled
STALL_PATIENCE = 25        # steps without improvement before perturbing
STALL_PERTURB = 12         # random primitives injected to escape a local minimum
MAX_PERTURB = 8            # give up after this many perturbation bursts
GRIP_CAP = 120             # hard cap on waiting for the gripper
SETTLE_CAP = 200           # hard cap on waiting for the cube to settle after release

# Pose of the recording camera, in world coordinates: where it sits, and what it looks at.
# Edit these two lines to change the angle of the recorded GIF.
#
# Deliberately explicit rather than copied from /DefaultCamera. Inheriting that camera makes the
# recording depend on wherever the view was last dragged and saved -- it was once found at
# z = 0.374, below table height, pointing at nothing, which would have produced an empty GIF.
CAM_EYE = (1.35, 2, 1.85)
CAM_AT = (-0.05, 2.00, 0.95)
FIT_VIEW_TO = ('/Workbench', '/UR5', '/Cube', '/PlacePad')


def look_at(eye, at, up=(0, 0, 1)):
    """Matrix for a vision sensor at `eye` looking at `at`. A vision sensor looks down its +z."""
    z = [a - e for a, e in zip(at, eye)]
    n = math.sqrt(sum(v * v for v in z))
    z = [v / n for v in z]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    n = math.sqrt(sum(v * v for v in x))
    x = [v / n for v in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [x[0], y[0], z[0], eye[0],
            x[1], y[1], z[1], eye[1],
            x[2], y[2], z[2], eye[2]]


def fit_gui_view(sim):
    """Point the GUI's main view at the workcell. No-op when there is no view (headless)."""
    try:
        sim.cameraFitToView(0, [sim.getObject(n) for n in FIT_VIEW_TO])
        return True
    except Exception:
        return False


class Kinematics:
    """A kinematic model of the arm, used ONLY to predict where a candidate primitive would land.

    This never solves inverse kinematics and never commands the running simulation -- doing either
    would quietly turn the pilot back into the Cartesian expert it exists to avoid. It reads the
    current joint values, applies a hypothetical delta, and reads the resulting tool pose.
    """

    def __init__(self, sim, simIK, arm, tip, target):
        self.sim, self.simIK, self.arm = sim, simIK, arm
        self.env = simIK.createEnvironment()
        self.grp = simIK.createGroup(self.env)
        _, m, _ = simIK.addElementFromScene(self.env, self.grp, sim.getObject('/UR5'), tip, target,
                                            simIK.constraint_pose)
        self.ikJ = [m[j] for j in arm]
        self.ikTip = m[tip]

    def predict(self, q_now, joint, delta):
        """Tool position if `joint` moved by `delta` from the current configuration."""
        simIK = self.simIK
        for ij, q in zip(self.ikJ, q_now):
            simIK.setJointPosition(self.env, ij, q)
        simIK.setJointPosition(self.env, self.ikJ[joint], q_now[joint] + delta)
        return simIK.getObjectPose(self.env, self.ikTip, -1)[:3]


class Pilot:
    def __init__(self, sim, simIK, log_path, slow=0.0, record=None, every=3):
        simconfig.pin_physics(sim)
        self.sim = sim
        self.record = record
        self.every = every
        self.frames = []
        self.cam = None
        if record:
            # Created while the simulation is STOPPED: objects created mid-run are destroyed by the
            # stopSimulation() inside every episode reset, which is exactly what went wrong first.
            # Rendering goes through a vision sensor rather than the GUI viewport because the sensor
            # renders offscreen and reliably, which the GUI's OpenGL view may not on every machine.
            self.cam = sim.createVisionSensor(
                2, [640, 480, 0, 0], [0.01, 25.0, math.radians(50), 0.1, 0, 0, 0, 0, 0, 0, 0])
            sim.setObjectAlias(self.cam, 'RunCam')
            sim.setExplicitHandling(self.cam, 1)
            sim.setObjectMatrix(self.cam, look_at(CAM_EYE, CAM_AT), -1)

        sim.setStepping(True)
        sim.startSimulation()
        self.grasp = GraspRule(sim)
        self.obs = Observer(sim, self.grasp, manipulability=False)
        self.reset = EpisodeReset(sim, self.grasp, self.obs, mode='fixed')
        self.actuator = Actuator(sim, self.reset.arm)
        self.reset.on_start = self.actuator.use_velocity_control
        self.arm = self.reset.arm
        self.kin = Kinematics(sim, simIK, self.arm, sim.getObject('/UR5/tip'),
                              sim.getObject('/target'))
        self.tracker = GoalTracker()
        self.repertoire = primitive_repertoire()
        self.moves = [h for h in self.repertoire if h[0]['action'] == 'MOVE']
        self.rng = random.Random(0)
        self.sink = open_log(log_path)
        self.steps = 0
        self.energy = 0.0
        self.prev_q = None
        self.segment = '-'
        self.per_segment = {}
        self.cube_disturbance = 0.0
        self.slow = slow

    def grab_frame(self):
        from PIL import Image
        self.sim.handleVisionSensor(self.cam)
        img, res = self.sim.getVisionSensorImg(self.cam)
        self.frames.append(Image.frombytes('RGB', (res[0], res[1]), bytes(img))
                           .transpose(Image.FLIP_TOP_BOTTOM))

    def _q(self, o):
        return [j['pos'] for j in o['innerSense']['joints']]

    def run_primitive(self, habit, o):
        """Run one primitive until its step completes, exactly as the agent will."""
        step = StepCompletion(habit, o)
        while True:
            o, _ = self.apply(step.commands(o), o)
            if step.update(o) is not None:
                return o

    def apply(self, records, o_before):
        for r in records:
            assert any(record_id(r) == record_id(h[0]) for h in self.repertoire), \
                'pilot emitted a non-primitive record: %r' % r
        self.actuator.apply(records)
        self.sim.step()
        if self.slow:
            time.sleep(self.slow)      # only for watching; does not affect the simulation
        self.steps += 1
        if self.cam is not None and self.steps % self.every == 0:
            self.grab_frame()
        o = self.obs.read()
        q = self._q(o)
        if self.prev_q is not None:
            self.energy += sum(abs(a - b) for a, b in zip(q, self.prev_q))
        self.prev_q = q
        fired = self.tracker.update(o)
        self.per_segment[self.segment] = self.per_segment.get(self.segment, 0) + 1
        self.sink.write(json.dumps({
            'episode': 0, 'step': self.steps - 1, 't': o_before['t'], 'seed': 0,
            'condition': 'PILOT', 'segment': self.segment,
            'obs': o_before, 'action': records, 'habit_id': [record_id(r) for r in records],
            'goal_step': self.tracker.current, 'goal_fired': fired,
            'success': succeeded(o), 'done': False, 'rewards': {},
        }) + '\n')
        return o, fired

    # --- the controller --------------------------------------------------
    def go_to(self, o, name, target):
        """Greedy: each step take the single primitive that most reduces distance to `target`."""
        self.segment = name
        best_seen = math.inf
        since = 0
        bursts = 0
        while True:
            tip = o['innerSense']['eef']['pos']
            d = math.dist(tip, target)
            if d <= ARRIVE_TOL:
                return o, True
            if self.per_segment.get(name, 0) > SEGMENT_BUDGET:
                return o, False

            q = self._q(o)
            scored = []
            for h in self.moves:
                rec = h[0]
                p = self.kin.predict(q, rec['joint'], rec['angle'])
                scored.append((math.dist(p, target), h))
            scored.sort(key=lambda x: x[0])
            best_d, best_h = scored[0]

            if best_d < best_seen - 1e-5:
                best_seen = best_d
                since = 0
            else:
                since += 1

            if since > STALL_PATIENCE:
                # R2: no single-joint move improves things. Perturb rather than give up at once.
                bursts += 1
                if bursts > MAX_PERTURB:
                    return o, False
                for _ in range(STALL_PERTURB):
                    o = self.run_primitive(self.rng.choice(self.moves), o)
                since = 0
                best_seen = math.dist(o['innerSense']['eef']['pos'], target)
                continue

            o = self.run_primitive(best_h, o)

    def gripper(self, o, name, opening):
        """Hold the GRAB primitive until the grasp state actually changes.

        Event-driven rather than a fixed wait: a fixed wait inflates the step count with idling and
        would make the floor this pilot reports dishonestly high. It is also what an agent does --
        it issues GRAB records until something changes.
        """
        self.segment = name
        recs = [grab(opening)]
        want_holding = not opening
        for _ in range(GRIP_CAP):
            o, _ = self.apply(recs, o)
            if o['innerSense']['gripper']['isHolding'] == want_holding:
                break
        return o

    def run(self):
        # Warm-up reset, discarded. SIM-08: a reset is history-independent only from the *second*
        # one onward, so without this the run is not bit-reproducible -- and a greedy controller
        # turns a 1e-5 rad difference into a different step count.
        self.reset.reset(0, 0)
        self.reset.reset(0, 0)
        o = self.obs.read()
        self.prev_q = self._q(o)
        cube = list(o['vision']['cube']['pos'])
        pad = list(o['vision']['pad']['pos'])
        cube0 = list(cube)
        print('  cube %s   pad %s' % ([round(v, 3) for v in cube], [round(v, 3) for v in pad]))

        plan = [
            ('approach', [cube[0], cube[1], HOVER], None),
            ('descend', [cube[0], cube[1], GRASP_Z], None),
            ('close', None, False),
            ('lift', [cube[0], cube[1], CARRY], None),
            ('traverse', [pad[0], pad[1], CARRY], None),
            ('lower', [pad[0], pad[1], PLACE_Z], None),
            ('open', None, True),
            ('retreat', [pad[0], pad[1], CARRY], None),
        ]
        for name, target, grip in plan:
            if grip is None:
                o, ok = self.go_to(o, name, target)
                if name == 'descend':
                    self.cube_disturbance = math.dist(o['vision']['cube']['pos'], cube0)
                print('    %-9s %5d steps  %s' % (name, self.per_segment.get(name, 0),
                                                  'ok' if ok else 'STALLED'))
                if not ok:
                    return self.finish(o, False)
            else:
                o = self.gripper(o, name, grip)
                held = o['innerSense']['gripper']['isHolding']
                print('    %-9s %5d steps  holding=%s' % (name, self.per_segment.get(name, 0), held))
        # Wait only until the release goal step actually fires, not a fixed number of steps.
        self.segment = 'settle'
        for _ in range(SETTLE_CAP):
            o, _ = self.apply([], o)
            if self.tracker.current == 'done':
                break
        return self.finish(o, succeeded(o))

    def finish(self, o, ok):
        self.sink.write(json.dumps({
            'episode': 0, 'step': self.steps, 't': o['t'], 'seed': 0, 'condition': 'PILOT',
            'obs': o, 'action': None, 'habit_id': None, 'goal_step': self.tracker.current,
            'goal_fired': None, 'success': ok, 'done': True, 'rewards': {},
            'episode_summary': {'steps': self.steps, 'success': ok, 'jointEnergy': self.energy,
                                'goalsReached': [t[0] for t in self.tracker.transitions],
                                'cube_start': tuple(o['vision']['cube']['pos'])},
        }) + '\n')
        self.sink.close()
        if self.record and self.frames:
            self.frames[0].save(self.record, save_all=True, append_images=self.frames[1:],
                                duration=80, loop=0, optimize=True)
            print('  wrote %d frames -> %s' % (len(self.frames), self.record))
        return ok, o


def fusion_headroom(log_path):
    """How much of this run's length is due to moving one joint at a time.

    NOT measured against the Cartesian expert: that expert interpolates over a *chosen* number of
    steps (80, 60, 90 ...), so its length is a stylistic choice, not a lower bound, and comparing
    against it produced a ratio that read as "primitives are faster", which is meaningless.

    Measured instead from this run's own joint trajectory, per motion segment:
      sequential cost = sum over joints of |dq_j|   (one joint at a time -- what a primitive does)
      parallel cost   = max over joints of |dq_j|   (all joints at once -- what a fused habit does)
    Their ratio is the headroom parallel fusion has to recover, and it depends on nothing but
    geometry.
    """
    from collections import defaultdict
    per = defaultdict(lambda: [0.0] * 6)
    prev = {}
    for line in open_log(log_path, 'rt'):
        r = json.loads(line)
        if r.get('done') or not r.get('obs'):
            continue
        seg = r.get('segment', '-')
        q = [j['pos'] for j in r['obs']['innerSense']['joints']]
        if seg in prev:
            for i in range(6):
                per[seg][i] += abs(q[i] - prev[seg][i])
        prev[seg] = q
    rows = []
    tot_seq = tot_par = 0.0
    for seg, d in per.items():
        seq, par = sum(d), max(d)
        if par < 1e-6:
            continue
        rows.append((seg, seq, par, seq / par))
        tot_seq += seq
        tot_par += par
    return rows, (tot_seq / tot_par if tot_par else float('nan'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=os.path.join(HERE, 'pilot.jsonl.gz'))
    ap.add_argument('--record', default=None,
                    help='write an animated GIF of the run to this path')
    ap.add_argument('--every', type=int, default=3, help='record every Nth step')
    ap.add_argument('--no-fit-view', action='store_true',
                    help="don't reframe the GUI view at startup")
    ap.add_argument('--slow', type=float, default=0.0,
                    help='seconds to pause per step, for watching in the GUI '
                         '(0.05 is about real time). Does not change the simulation.')
    a = ap.parse_args()

    c = RemoteAPIClient()
    sim, simIK = c.require('sim'), c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)
    if not a.no_fit_view and fit_gui_view(sim):
        print('  GUI view framed on the workcell')

    pilot = Pilot(sim, simIK, a.log, slow=a.slow, record=a.record, every=a.every)
    ok, o = pilot.run()
    sim.stopSimulation()

    print()
    print('  goal steps reached : %s' % [t[0] for t in pilot.tracker.transitions])
    print('  total steps        : %d' % pilot.steps)
    print('  E_joint            : %.2f rad' % pilot.energy)
    print('  cube disturbance   : %.4f m (during descend, before the gripper closed)' %
          pilot.cube_disturbance)
    print('  cube to pad centre : %.4f m' % o['derived']['cubeToPadXY'])
    rows, overall = fusion_headroom(a.log)
    print()
    print('  fusion headroom (joint displacement, one-at-a-time vs all-at-once):')
    for seg, seq, par, ratio in rows:
        print('    %-9s sequential %.3f rad  parallel %.3f rad  -> %.2fx' % (seg, seq, par, ratio))
    print('    %-9s %.2fx overall' % ('TOTAL', overall))
    print()
    print('  log                : %s' % a.log)
    print()
    print('PIL-01: %s' % ('SUCCESS — the task is reachable with primitives alone'
                          if ok else 'NOT SOLVED by the greedy controller (see the spec: this is '
                                     'not proof of infeasibility)'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
