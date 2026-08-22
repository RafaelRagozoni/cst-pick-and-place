"""Record a scripted pick-and-place trajectory to JSONL, for the offline SIM-03/SIM-06 tests.

This is a scripted *expert*, not the episode runner (SIM-07) and not the agent: it drives the tool
in Cartesian space with inverse kinematics, which the agent will not do -- the agent commands joint
velocities and must discover the behaviour. Its jobs are to give the offline tests a realistic
trajectory and to serve as the end-to-end check that the environment layer works.

Everything here is real since DEC-05 fixed the pedestal geometry: the arm genuinely approaches the
cube, the gripper closes on it, and the environment-side grasp rule attaches it because the physical
predicate holds. Nothing is teleported and gravity is never switched off.

    python3 record_trajectory.py            # needs CoppeliaSim open on the scene
"""
import json
import math
import os
import sys

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simconfig
from goals import GoalTracker, succeeded
from grasp_rule import GraspRule, set_gripper
from observations import Observer

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')
OUT = os.path.join(HERE, 'traj.jsonl')

HOVER = 0.22            # m above the table for the approach
GRASP_Z = 0.755         # m, fingertips straddling the cube
CARRY = 0.25            # m above the table while carrying
PLACE_Z = 0.80          # m, release height over the pad


def main():
    c = RemoteAPIClient()
    sim, simIK = c.require('sim'), c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)
    print('physics: %s' % simconfig.pin_physics(sim))

    ur5 = sim.getObject('/UR5')
    tip = sim.getObject('/UR5/tip')
    target = sim.getObject('/target')
    cube = sim.getObject('/Cube')
    pad = sim.getObject('/PlacePad')
    arm = [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
           if 'RG2' not in sim.getObjectAlias(j, 2)][:6]

    sim.setStepping(True)
    sim.startSimulation()
    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=True, simIK=simIK)
    tracker = GoalTracker()
    rec = []

    def run(n):
        o = None
        for _ in range(n):
            sim.step()
            o = obs.read()
            rec.append(o)
            fired = tracker.update(o)
            if fired:
                print('  goal step %-10s at t=%.2f s' % (fired, o['t']))
        return o

    env = simIK.createEnvironment()
    grp = simIK.createGroup(env)
    simIK.setGroupCalculation(env, grp, simIK.method_damped_least_squares, 0.05, 300)
    _, m, _ = simIK.addElementFromScene(env, grp, ur5, tip, target, simIK.constraint_pose)
    ikJ = [m[j] for j in arm]
    ikT, ikTip = m[target], m[tip]

    set_gripper(sim, True)
    run(40)
    sim.setObjectPose(target, sim.getObjectPose(tip, -1), -1)
    simIK.syncFromSim(env, [grp])

    def move(p, n=80):
        p0 = simIK.getObjectPose(env, ikTip, -1)[:3]
        for i in range(1, n + 1):
            a = i / n
            s = a * a * (3 - 2 * a)                     # smoothstep
            q = [p0[k] + (p[k] - p0[k]) * s for k in range(3)]
            sim.setObjectPosition(target, q, -1)
            sim.setObjectOrientation(target, [math.pi, 0, 0], -1)
            simIK.setObjectPose(env, ikT, sim.getObjectPose(target, -1), -1)
            simIK.handleGroup(env, grp, {'syncWorlds': False, 'allowError': True})
            for sj, ij in zip(arm, ikJ):
                sim.setJointTargetPosition(sj, simIK.getJointPosition(env, ij))
            sim.step()
            o = obs.read()
            rec.append(o)
            tracker.update(o)

    cp = sim.getObjectPosition(cube, -1)
    pp = sim.getObjectPosition(pad, -1)

    move([cp[0], cp[1], 0.72 + HOVER]); run(20)
    move([cp[0], cp[1], GRASP_Z], n=60); o = run(20)
    print('  at cube: eefToCube=%.3f m, cube undisturbed by %.4f m'
          % (o['derived']['eefToCube'], math.dist(sim.getObjectPosition(cube, -1), cp)))

    set_gripper(sim, False); o = run(90)
    print('  grasped: holding=%s, fingertip gap=%.4f m'
          % (o['innerSense']['gripper']['isHolding'], o['innerSense']['gripper']['width']))

    move([cp[0], cp[1], 0.72 + CARRY], n=60); run(20)
    move([pp[0], pp[1], 0.72 + CARRY], n=90); run(20)
    move([pp[0], pp[1], PLACE_Z], n=60); run(20)
    set_gripper(sim, True); o = run(150)

    print('  released: cube %.4f m from the pad centre, success=%s'
          % (o['derived']['cubeToPadXY'], succeeded(o)))
    print('  goal steps: %s' % [t[0] for t in tracker.transitions])

    with open(OUT, 'w') as f:
        for o in rec:
            f.write(json.dumps(o) + '\n')
    print('recorded %d observations -> %s' % (len(rec), OUT))
    sim.stopSimulation()


if __name__ == '__main__':
    main()
