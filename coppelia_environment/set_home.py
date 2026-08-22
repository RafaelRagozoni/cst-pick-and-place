"""SIM-01: put the scene into a clean, reproducible episode start state.

The scene as saved was unusable as an episode start: its stored joint *positions* were the
IK-solved grasp pose left behind by snapshot.py, while its stored joint *target* positions
were still build_scene.py's q0. On startSimulation() the position controllers drove the arm
from one posture to the other and threw the cube off the table -- silently, since nothing
errors. pick_and_place.py hid the bug by overwriting all six joints before starting.

A second defect surfaced while verifying the first: the stock UR5 model ships a threaded child
script ("This is a threaded script, and is just an example!") that runs a canned three-waypoint
motion on every simulation start, driving the arm to [90,90,-90,90,90,90] and onward. It would
fight every command the agent sends, so it is removed here. The RG2 gripper script is kept -- it
implements the gripper.

This script removes that demo script, writes HOME_Q_DEG (defined in build_scene.py, the single
source of truth) to both the positions and the targets, opens the fingers, saves the scene, and
then verifies the fix by stepping the simulation with no commands at all.

Run with CoppeliaSim already open on the scene:
    python3 set_home.py
"""
import math
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

from build_scene import HOME_Q_DEG, TABLE_TOP_Z

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')

IDLE_STEPS = 100               # acceptance test length
MAX_CUBE_DRIFT = 0.001         # m
MAX_JOINT_VEL = 0.01           # rad/s
MAX_JOINT_DRIFT = 0.02         # rad, per joint, away from the home posture
MAX_TIP_DRIFT = 0.01           # m
MIN_FINGER_GAP = 0.05          # m, fingertips apart == gripper open at home


def arm_joints(sim, ur5):
    return [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
            if 'RG2' not in sim.getObjectAlias(j, 2)][:6]


def remove_demo_scripts(sim):
    """Drop the UR5 model's canned demo motion script. Keep the RG2 gripper script."""
    ur5 = sim.getObject('/UR5')
    removed = []
    for h in sim.getObjectsInTree(ur5):
        alias = sim.getObjectAlias(h, 2)
        if 'RG2' in alias:
            continue
        if sim.getObjectType(h) == sim.sceneobject_script:
            removed.append(alias)
            sim.removeObjects([h])
    return removed


def apply_home(sim):
    """Write the home posture to the arm's positions AND targets.

    The RG2 finger joints are deliberately NOT touched. They form a closed-loop linkage, and
    forcing setJointPosition on its members leaves the mechanism inconsistent -- doing so jammed
    the fingers at a 4.5 mm gap instead of the linkage's natural 54.5 mm. Gripper state at the
    start of an episode is the RG2 script's business, driven by the RG2_open signal, which the
    episode runner sets at reset (SIM-02/SIM-07).
    """
    ur5 = sim.getObject('/UR5')
    for j, deg in zip(arm_joints(sim, ur5), HOME_Q_DEG):
        sim.setJointPosition(j, math.radians(deg))
        sim.setJointTargetPosition(j, math.radians(deg))


def verify(sim):
    """Load the saved scene, run it with no commands, and report whether it holds still."""
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)

    ur5 = sim.getObject('/UR5')
    cube = sim.getObject('/Cube')
    tip = sim.getObject('/UR5/tip')
    arm = arm_joints(sim, ur5)

    leftover = [sim.getObjectAlias(h, 2) for h in sim.getObjectsInTree(ur5)
                if sim.getObjectType(h) == sim.sceneobject_script
                and 'RG2' not in sim.getObjectAlias(h, 2)]
    print('  demo scripts left:', leftover or 'none')

    pos = [round(sim.getJointPosition(j), 4) for j in arm]
    tgt = [round(sim.getJointTargetPosition(j), 4) for j in arm]
    print('  stored positions:', pos)
    print('  stored targets  :', tgt)
    mismatch = max(abs(p - t) for p, t in zip(pos, tgt))
    print('  max |position - target| = %.5f rad' % mismatch)

    home = [math.radians(d) for d in HOME_Q_DEG]
    before = sim.getObjectPosition(cube, -1)
    tip_before = sim.getObjectPosition(tip, -1)
    sim.setStepping(True)
    sim.startSimulation()
    # The RG2 script closes the gripper unless RG2_open is set, so the episode runner must set it
    # at every reset (SIM-02/SIM-07). It MUST go through the property API: in CoppeliaSim 4.10 the
    # legacy sim.setInt32Signal writes a namespace the script's getIntProperty never reads, so the
    # call silently does nothing. Measured: property API gives 0.105 m open / 0.005 m closed;
    # setInt32Signal leaves the gripper closed whatever you pass.
    sim.setIntProperty(sim.handle_scene, 'signal.RG2_open', 1)
    for _ in range(IDLE_STEPS):
        sim.step()
    after = sim.getObjectPosition(cube, -1)
    vel = [abs(sim.getJointVelocity(j)) for j in arm]
    tp = sim.getObjectPosition(tip, -1)
    M = sim.getObjectMatrix(tip, -1)
    sim.stopSimulation()

    lt, rt = sim.getObject('/UR5/RG2/leftTouch'), sim.getObject('/UR5/RG2/rightTouch')
    fingertip_gap = math.dist(sim.getObjectPosition(lt, -1), sim.getObjectPosition(rt, -1))
    q_end = [sim.getJointPosition(j) for j in arm]
    q_drift = max(abs(a - b) for a, b in zip(q_end, home))
    tip_drift = math.dist(tip_before, tp)
    drift = math.dist(before, after)
    print('  cube before     :', [round(v, 4) for v in before])
    print('  cube after %3d  : %s' % (IDLE_STEPS, [round(v, 4) for v in after]))
    print('  cube drift      : %.5f m   (limit %.3f)' % (drift, MAX_CUBE_DRIFT))
    print('  max joint |vel| : %.5f rad/s (limit %.3f)' % (max(vel), MAX_JOINT_VEL))
    print('  tip             : %s  tool-down %.3f  clearance %.3f m'
          % ([round(v, 3) for v in tp], -M[10], tp[2] - TABLE_TOP_Z))
    print('  arm drift       : %.5f rad  (limit %.3f)' % (q_drift, MAX_JOINT_DRIFT))
    print('  tip drift       : %.5f m    (limit %.3f)' % (tip_drift, MAX_TIP_DRIFT))
    print('  fingertip gap   : %.4f m    (open, min %.3f)' % (fingertip_gap, MIN_FINGER_GAP))

    # The arm must be checked explicitly: an earlier version of this test watched only the cube
    # and passed while the arm quietly wandered off to the demo script's waypoint.
    ok = (drift <= MAX_CUBE_DRIFT and max(vel) <= MAX_JOINT_VEL and mismatch < 1e-4
          and q_drift <= MAX_JOINT_DRIFT and tip_drift <= MAX_TIP_DRIFT and -M[10] > 0.98
          and fingertip_gap >= MIN_FINGER_GAP)
    print('  ACCEPTANCE: %s' % ('PASS' if ok else 'FAIL'))
    return ok


def main():
    sim = RemoteAPIClient().require('sim')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)

    print('home posture (deg):', HOME_Q_DEG)
    print('removed demo scripts:', remove_demo_scripts(sim) or 'none')
    apply_home(sim)
    sim.saveScene(SCENE)
    print('saved:', SCENE)

    print('verifying...')
    raise SystemExit(0 if verify(sim) else 1)


if __name__ == '__main__':
    main()
