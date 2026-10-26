"""Acceptance for the Safety drive's inputs: joint-limit margin, the enforced limit, collisions.

Needs CoppeliaSim. A clean trajectory staying quiet is checked offline, in test_observations.py; this
checks that the signals do fire when they should.

    python3 test_safety.py
"""
import math
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

from actions import ANGLE_TOL, Actuator, StepCompletion, joint_positions, move
from build_scene import HOME_Q_DEG, TABLE_TOP_Z
from episode import EpisodeReset
from grasp_rule import GraspRule
from observations import Observer
from simconfig import JOINT_LIMIT

TABLE_SPOT = (0.27, 0.0)     # m, as far out as the cube (0.57 m), between cube and pad: tool meets table
PEDESTAL_SPOT = (0.22, 0.0)  # m, straight below home: the wrist folds into the pedestal first
CRASH_Z = 0.68               # m, tool target below the table top


def main():
    c = RemoteAPIClient()
    sim, simIK = c.require('sim'), c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))
    sim.setStepping(True)
    sim.startSimulation()
    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=False)
    reset = EpisodeReset(sim, rule, obs)
    act = Actuator(sim, reset.arm)
    reset.on_start = act.use_velocity_control
    reset.reset(0, 0)
    reset.reset(0, 0)
    checks = []

    # --- at home: margins as expected, nothing hit -----------------------
    o = obs.read()
    want = [JOINT_LIMIT - math.radians(abs(d)) for d in HOME_Q_DEG]
    err = max(abs(a - b) for a, b in zip(o['innerSense']['jointLimitMargin'], want))
    checks.append(('home: margins are 180 deg - |q|', err < math.radians(0.5)))
    checks.append(('home: no collision', not o['innerSense']['envCollision']
                   and not o['innerSense']['selfCollision']))

    # --- the limit holds, and the joint can come back --------------------
    def run(habit, o):
        step = StepCompletion(habit, o)
        while True:
            act.apply(step.commands(o), joint_positions(o))
            sim.step()
            o = obs.read()
            res = step.update(o)
            if res is not None:
                return res, o

    res, o = run([move(5, 1, angle=math.radians(300))], o)
    q5 = joint_positions(o)[5]
    m5 = o['innerSense']['jointLimitMargin'][5]
    print('  wrist driven 300 deg toward +180: %s at %.2f deg, margin %.3f deg'
          % (res, math.degrees(q5), math.degrees(m5)))
    checks.append(('a joint stops at +180 deg', res == 'stalled' and abs(m5) <= ANGLE_TOL))
    res, o = run([move(5, -1, angle=math.radians(10))], o)
    print('  then 10 deg back: %s at %.2f deg' % (res, math.degrees(joint_positions(o)[5])))
    checks.append(('and can move back in', res == 'done'
                   and abs(joint_positions(o)[5] - (JOINT_LIMIT - math.radians(10))) <= ANGLE_TOL))

    # --- driving the tool down is a collision, with whatever it meets first ---
    # Inverse kinematics on position-controlled joints, as record_trajectory.py does: this checks
    # the collision signal, not the agent's ability to get there.
    names = ['Workbench', 'Pedestal', 'PlacePad']

    def crash(spot):
        reset.reset(0, 0)
        for j in reset.arm:
            sim.setObjectInt32Param(j, sim.jointintparam_dynctrlmode, sim.jointdynctrl_position)
        tip, target = sim.getObject('/UR5/tip'), sim.getObject('/target')
        env = simIK.createEnvironment()
        grp = simIK.createGroup(env)
        simIK.setGroupCalculation(env, grp, simIK.method_damped_least_squares, 0.05, 300)
        _, m, _ = simIK.addElementFromScene(env, grp, sim.getObject('/UR5'), tip, target,
                                            simIK.constraint_pose)
        ikJ = [m[j] for j in reset.arm]
        sim.setObjectPose(target, sim.getObjectPose(tip, -1), -1)
        simIK.syncFromSim(env, [grp])
        p0 = sim.getObjectPosition(tip, -1)
        n = 160
        for i in range(1, n + 1):
            a = i / n
            p = [p0[0] + (spot[0] - p0[0]) * a, p0[1] + (spot[1] - p0[1]) * a,
                 p0[2] + (CRASH_Z - p0[2]) * a]
            sim.setObjectPosition(target, p, -1)
            sim.setObjectOrientation(target, [math.pi, 0, 0], -1)
            simIK.setObjectPose(env, m[target], sim.getObjectPose(target, -1), -1)
            simIK.handleGroup(env, grp, {'syncWorlds': False, 'allowError': True})
            for sj, ij in zip(reset.arm, ikJ):
                sim.setJointTargetPosition(sj, simIK.getJointPosition(env, ij))
            sim.step()
            o = obs.read()
            if o['innerSense']['envCollision']:
                per = sim.callScriptFunction('contacts', obs._contact_script, obs.robot_shapes,
                                             obs.touch_targets)
                hit = [nm for nm, h in zip(names, per) if h]
                print('  tool driven down at %s: first collision with %s at tool z = %.3f m, '
                      'after %d clean steps' % (spot, hit, o['innerSense']['eef']['pos'][2], i - 1))
                return hit, o['innerSense']['eef']['pos'][2], i - 1
        print('  tool driven down at %s: no collision' % (spot,))
        return [], None, n

    hit, z, clean = crash(TABLE_SPOT)
    # Fully stretched down this far out, the wrist also grazes the pedestal: either is a collision.
    checks.append(('tool into the table is a collision', 'Workbench' in hit))
    checks.append(('and not before the tool gets there',
                   z is not None and z < TABLE_TOP_Z + 0.04 and clean > 50))
    hit, z, clean = crash(PEDESTAL_SPOT)
    checks.append(('wrist folding into the pedestal is one', hit == ['Pedestal'] and clean > 50))
    sim.stopSimulation()

    ok = True
    for name, good in checks:
        print('  %-40s %s' % (name, 'PASS' if good else 'FAIL'))
        ok &= bool(good)
    print('\nSAFETY ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
