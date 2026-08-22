"""Run the UR5 pick-and-place demo and capture figures for the paper.

Sequence: approach -> descend -> close gripper -> lift -> transfer -> descend
-> release -> retreat. The arm is driven in Cartesian space: each control step
solves inverse kinematics (simIK, damped least squares) for the tool pose and
commands the six joint position controllers.

Usage (CoppeliaSim must be running):
    python3 pick_and_place.py
Figures are written to figures/.
"""
import math
import os
import subprocess
import time

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')
FIGDIR = os.path.join(HERE, 'figures')

TABLE = 0.72
CUBE = 0.05
GRASP_Z = TABLE + CUBE / 2 + 0.005     # fingertips straddling the cube
HOVER_Z = TABLE + 0.22
CUBE_XY = (0.22, -0.22)
PAD_XY = (0.22, 0.24)

SEED_Q = [math.radians(a) for a in (80, -90, 85, -85, 90, 0)]
DOWN = [math.pi, 0, 0]                 # tool z-axis pointing at the table


class Demo:
    def __init__(self):
        client = RemoteAPIClient()
        self.sim = sim = client.require('sim')
        self.simIK = client.require('simIK')

        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            time.sleep(0.05)
        sim.loadScene(SCENE)

        self.ur5 = sim.getObject('/UR5')
        self.tip = sim.getObject('/UR5/tip')
        self.target = sim.getObject('/target')
        self.cube = sim.getObject('/Cube')
        self.attach = sim.getObject('/UR5/RG2/attachPoint')

        self.arm = [j for j in sim.getObjectsInTree(self.ur5, sim.sceneobject_joint)
                    if 'RG2' not in sim.getObjectAlias(j, 2)][:6]

        # start from a posture with the tool already pointing down
        for j, q in zip(self.arm, SEED_Q):
            sim.setJointPosition(j, q)
            sim.setJointTargetPosition(j, q)
        sim.setObjectPose(self.target, sim.getObjectPose(self.tip, -1), -1)

        self._setup_ik()
        self.win = self._find_window()

    def _setup_ik(self):
        simIK, sim = self.simIK, self.sim
        self.env = simIK.createEnvironment()
        self.grp = simIK.createGroup(self.env)
        simIK.setGroupCalculation(self.env, self.grp,
                                  simIK.method_damped_least_squares, 0.05, 200)
        _, simToIk, _ = simIK.addElementFromScene(
            self.env, self.grp, self.ur5, self.tip, self.target, simIK.constraint_pose)
        self.ikJoints = [simToIk[j] for j in self.arm]
        self.ikTarget = simToIk[self.target]
        self.ikTip = simToIk[self.tip]
        # The IK environment is kept as a *kinematic* model of the arm: it is seeded once
        # from the scene and thereafter advanced by IK alone. Re-syncing it from the running
        # simulation every step would feed the position controllers' tracking lag back into
        # the solver, which makes it chase its own error and diverge.
        simIK.syncFromSim(self.env, [self.grp])

    # --- capture -----------------------------------------------------------
    def _find_window(self):
        try:
            tree = subprocess.run(['xwininfo', '-root', '-tree'], env={'DISPLAY': ':1'},
                                  capture_output=True, text=True, timeout=20).stdout
            for line in tree.splitlines():
                if 'coppeliasim' in line.lower() and '0x' in line:
                    return line.split()[0]
        except Exception as e:
            print('window lookup failed:', e)
        return None

    def shot(self, name):
        os.makedirs(FIGDIR, exist_ok=True)
        path = os.path.join(FIGDIR, name + '.png')
        if not self.win:
            return
        subprocess.run(['import', '-window', self.win, path],
                       env={'DISPLAY': ':1'}, timeout=30)
        print('  captured', path)

    # --- motion ------------------------------------------------------------
    def gripper(self, opened, hold=1.2):
        self.sim.setInt32Signal('RG2_open', 1 if opened else 0)
        self.step_for(hold)

    def log(self, stage):
        c = self.sim.getObjectPosition(self.cube, -1)
        t = self.sim.getObjectPosition(self.tip, -1)
        print('  [%-9s] cube=%s tip=%s gap=%.3f' % (
            stage, [round(v, 3) for v in c], [round(v, 3) for v in t], math.dist(c, t)))

    def step_for(self, seconds):
        n = max(1, int(seconds / self.sim.getSimulationTimeStep()))
        for _ in range(n):
            self.sim.step()

    def move_to(self, pos, seconds=2.0, yaw=0.0):
        """Cartesian move: interpolate the tool pose, solve IK each step."""
        sim, simIK = self.sim, self.simIK
        dt = sim.getSimulationTimeStep()
        n = max(2, int(seconds / dt))
        p0 = simIK.getObjectPose(self.env, self.ikTip, -1)[:3]
        for i in range(1, n + 1):
            a = i / n
            s = a * a * (3 - 2 * a)                     # smoothstep: ease in/out
            p = [p0[k] + (pos[k] - p0[k]) * s for k in range(3)]
            sim.setObjectPosition(self.target, p, -1)
            sim.setObjectOrientation(self.target, [DOWN[0], DOWN[1], yaw], -1)
            simIK.setObjectPose(self.env, self.ikTarget,
                                sim.getObjectPose(self.target, -1), -1)
            res = simIK.handleGroup(self.env, self.grp,
                                    {'syncWorlds': False, 'allowError': True})
            if isinstance(res, (list, tuple)):
                res = res[0]
            if res != simIK.result_success:
                err = math.dist(simIK.getObjectPose(self.env, self.ikTip, -1)[:3], p)
                print('  ik did not converge (res=%s, residual=%.4f m)' % (res, err))
            for simj, ikj in zip(self.arm, self.ikJoints):
                sim.setJointTargetPosition(simj, simIK.getJointPosition(self.env, ikj))
            sim.step()

    def run(self):
        sim = self.sim
        sim.setStepping(True)
        sim.startSimulation()
        self.gripper(True, 0.8)
        self.log('start')
        self.shot('01_scene')

        print('approach'); self.move_to([CUBE_XY[0], CUBE_XY[1], HOVER_Z], 2.0)
        self.log('hover')
        print('descend');  self.move_to([CUBE_XY[0], CUBE_XY[1], GRASP_Z], 1.5)
        self.log('at cube')
        self.shot('02_approach')

        print('grasp')
        self.gripper(False, 1.2)
        self.log('closed')
        if math.dist(sim.getObjectPosition(self.cube, -1),
                     sim.getObjectPosition(self.tip, -1)) > 0.05:
            print('  !! cube is not between the fingers - grasp failed')
        sim.setObjectParent(self.cube, self.attach, True)   # rigid attach (CoppeliaSim's
        self.step_for(0.3)                                  # recommended way to hold)
        self.shot('03_grasp')

        print('lift');     self.move_to([CUBE_XY[0], CUBE_XY[1], HOVER_Z], 1.5)
        print('transfer'); self.move_to([PAD_XY[0], PAD_XY[1], HOVER_Z], 2.5)
        self.shot('04_transfer')

        print('place');    self.move_to([PAD_XY[0], PAD_XY[1], GRASP_Z + 0.006], 1.5)
        print('release')
        sim.setObjectParent(self.cube, -1, True)
        self.gripper(True, 1.0)
        self.shot('05_release')

        print('retreat');  self.move_to([PAD_XY[0], PAD_XY[1], HOVER_Z], 1.5)
        self.step_for(1.0)
        self.shot('06_done')

        cube_p = sim.getObjectPosition(self.cube, -1)
        pad_p = sim.getObjectPosition(sim.getObject('/PlacePad'), -1)
        err = math.dist(cube_p[:2], pad_p[:2])
        print('cube final: %s' % [round(v, 3) for v in cube_p])
        print('placement error (xy): %.1f mm  -> %s' % (err * 1000,
              'PLACED' if err < 0.05 and cube_p[2] > TABLE else 'FAILED'))

        sim.setStepping(False)


if __name__ == '__main__':
    Demo().run()
