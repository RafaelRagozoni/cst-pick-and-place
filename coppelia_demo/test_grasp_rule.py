"""SIM-04 acceptance test for grasp_rule.GraspRule.

Run with CoppeliaSim already open on the scene:
    python3 test_grasp_rule.py

This file isolates the RULE: the cube is placed between the fingers directly, with gravity briefly
off, so the predicate is tested independently of whether the arm can reach anything. Keeping it that
way is deliberate -- it still catches a broken predicate even if the geometry regresses.

The end-to-end counterpart, where the arm genuinely approaches and grasps, is record_trajectory.py
(possible since DEC-05 fixed the pedestal).
"""
import os
import math, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coppeliasim_zmqremoteapi_client import RemoteAPIClient
from grasp_rule import GraspRule, set_gripper
sim=RemoteAPIClient(port=23000).require('sim')
sim.stopSimulation()
while sim.getSimulationState()!=sim.simulation_stopped: pass
sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))
ur5=sim.getObject('/UR5'); cube=sim.getObject('/Cube')
arm=[j for j in sim.getObjectsInTree(ur5,sim.sceneobject_joint) if 'RG2' not in sim.getObjectAlias(j,2)][:6]
sim.setStepping(True); sim.startSimulation()
rule=GraspRule(sim)
def run(n):
    for _ in range(n):
        sim.step(); st=rule.update()
    return st
set_gripper(sim,True); st=run(60)
print('T0 open, empty      : holding=%-5s gap=%.4f F=(%.1f,%.1f) seen=%s'%(st['is_holding'],st['fingertip_gap'],*st['contact_force'],st['detected']))

# --- negative: close on empty air --------------------------------------
set_gripper(sim,False); st=run(90)
neg_ok = not st['is_holding']
print('T1 close on NOTHING : holding=%-5s gap=%.4f F=(%.1f,%.1f) seen=%s  -> %s'%(st['is_holding'],st['fingertip_gap'],*st['contact_force'],st['detected'],'PASS' if neg_ok else 'FAIL'))

# --- positive: cube between the fingers ---------------------------------
# Gravity off for the placement phase only: the cube is dynamic and would free-fall out of the
# fingers long before the gripper (0.05 m/s) could close on it. This isolates the RULE; the
# physical approach is the arm's job and is currently blocked by the pedestal geometry.
G=sim.getArrayParam(sim.arrayparam_gravity)
sim.setArrayParam(sim.arrayparam_gravity,[0,0,0])
set_gripper(sim,True); run(80)
mid=[(a+b)/2 for a,b in zip(sim.getObjectPosition(rule.lt,-1), sim.getObjectPosition(rule.rt,-1))]
sim.setObjectPosition(cube, mid, -1)
sim.resetDynamicObject(cube)
st=run(20)
print('T2 cube placed      : holding=%-5s gap=%.4f seen=%s'%(st['is_holding'],st['fingertip_gap'],st['detected']))
set_gripper(sim,False); st=run(90)
pos_ok = st['is_holding']
print('T3 close on CUBE    : holding=%-5s gap=%.4f F=(%.1f,%.1f) -> %s'%(st['is_holding'],st['fingertip_gap'],*st['contact_force'],'PASS' if pos_ok else 'FAIL'))

# --- does it actually stay held while the arm moves? --------------------
before=sim.getObjectPosition(cube,-1)
sim.setJointTargetPosition(arm[0], sim.getJointPosition(arm[0])+math.radians(25))
st=run(120)
after=sim.getObjectPosition(cube,-1)
carried = math.dist(before,after)>0.05 and st['is_holding'] and sim.getObjectParent(cube)!=-1
print('T4 carry (arm moved): cube moved %.3f m, still held=%s -> %s'%(math.dist(before,after),st['is_holding'],'PASS' if carried else 'FAIL'))

# --- release ------------------------------------------------------------
sim.setArrayParam(sim.arrayparam_gravity,G)          # gravity back on: the cube must fall
z_before=sim.getObjectPosition(cube,-1)[2]           # measure BEFORE releasing, not after it lands
set_gripper(sim,True); st=run(120)
z_after=sim.getObjectPosition(cube,-1)[2]
rel_ok = (not st['is_holding']) and sim.getObjectParent(cube)==-1 and z_after<z_before-0.05
print('T5 open -> release  : holding=%-5s parent=%d  cube fell %.3f m -> %s'%(st['is_holding'],sim.getObjectParent(cube),z_before-z_after,'PASS' if rel_ok else 'FAIL'))
print('\nSIM-04 ACCEPTANCE: %s' % ('PASS' if (neg_ok and pos_ok and carried and rel_ok) else 'FAIL'))
sim.stopSimulation()
