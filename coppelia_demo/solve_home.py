"""Solve HOME_Q_DEG for the scene's current geometry, by inverse kinematics.

The home posture depends on where the arm base is, so it has to be re-derived whenever the scene
geometry changes (DEC-05 changed the pedestal, which moved the base 15 cm up). Keeping this as a
script rather than a one-off means the constant can always be regenerated instead of guessed.

Home is chosen as: tool pointing straight down, tool centre point HOVER_M above the table, midway
between the cube start and the place pad so it favours neither.

    python3 solve_home.py        # prints the constant to paste into build_scene.py
"""
import math
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')
HOVER_M = 0.30                       # metres above the table top
SEED_DEG = [80, -90, 85, -85, 90, 0]  # a known elbow-up, tool-down branch to start IK from


def wrap(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def main():
    c = RemoteAPIClient()
    sim, simIK = c.require('sim'), c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)

    ur5 = sim.getObject('/UR5')
    tip = sim.getObject('/UR5/tip')
    target = sim.getObject('/target')
    cube = sim.getObject('/Cube')
    pad = sim.getObject('/PlacePad')
    arm = [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
           if 'RG2' not in sim.getObjectAlias(j, 2)][:6]

    cp = sim.getObjectPosition(cube, -1)
    pp = sim.getObjectPosition(pad, -1)
    goal = [(cp[0] + pp[0]) / 2, (cp[1] + pp[1]) / 2, 0.72 + HOVER_M]
    print('home tip goal: %s' % [round(v, 3) for v in goal])

    for j, d in zip(arm, SEED_DEG):
        sim.setJointPosition(j, math.radians(d))
    sim.setObjectPose(target, sim.getObjectPose(tip, -1), -1)

    env = simIK.createEnvironment()
    grp = simIK.createGroup(env)
    simIK.setGroupCalculation(env, grp, simIK.method_damped_least_squares, 0.05, 200)
    _, m, _ = simIK.addElementFromScene(env, grp, ur5, tip, target, simIK.constraint_pose)
    ikJ = [m[j] for j in arm]
    ikT, ikTip = m[target], m[tip]
    simIK.syncFromSim(env, [grp])

    p0 = simIK.getObjectPose(env, ikTip, -1)[:3]
    for i in range(1, 81):                       # small steps keep IK on the elbow-up branch
        s = i / 80
        p = [p0[k] + (goal[k] - p0[k]) * s for k in range(3)]
        sim.setObjectPosition(target, p, -1)
        sim.setObjectOrientation(target, [math.pi, 0, 0], -1)
        simIK.setObjectPose(env, ikT, sim.getObjectPose(target, -1), -1)
        simIK.handleGroup(env, grp, {'syncWorlds': False, 'allowError': True})

    q = [simIK.getJointPosition(env, j) for j in ikJ]
    for j, v in zip(arm, q):
        sim.setJointPosition(j, v)
    qd = [round(math.degrees(wrap(v)), 1) for v in q]
    qd[5] = 0.0                                  # wrist roll is free about the tool axis

    for j, d in zip(arm, qd):
        sim.setJointPosition(j, math.radians(d))
    tp = sim.getObjectPosition(tip, -1)
    M = sim.getObjectMatrix(tip, -1)
    print('tip        : %s  (err %.4f m from goal)' % ([round(v, 4) for v in tp],
                                                       math.dist(tp, goal)))
    print('tool-down  : %.4f  (1.0 = straight down)' % -M[10])
    print('clearance  : %.3f m above the table top' % (tp[2] - 0.72))
    print('dist to cube: %.3f m' % math.dist(tp, cp))
    print('\nHOME_Q_DEG = (%s)' % ', '.join('%.1f' % v for v in qd))


if __name__ == '__main__':
    main()
