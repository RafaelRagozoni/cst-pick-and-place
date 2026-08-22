"""Build a simple UR5 pick-and-place scene in CoppeliaSim.

Creates: workbench, UR5 (6-DoF) + RG2 gripper, red cube (object to pick),
green placement pad (target), and a camera viewpoint suitable for a figure.
Saves the scene to pick_and_place.ttt next to this file.

Run with CoppeliaSim already open (ZMQ remote API server is on by default):
    python3 build_scene.py
"""
import math
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

COP = '/home/rafael-ragozoni/CoppeliaSim_Edu_V4_10_0_rev0_Ubuntu24_04'
HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')

# --- scene layout (metres) --------------------------------------------------
TABLE_TOP_Z = 0.72          # height of the workbench surface
TABLE_SIZE = (1.20, 0.90, 0.04)
LEG = 0.06
ARM_BASE = (-0.30, 0.00, TABLE_TOP_Z)
# Pedestal geometry (DEC-05). The original 0.18 m x 0.30 m riser made the task IMPOSSIBLE: the
# upper-arm link collided with it on every approach to the tabletop, so 0 of 76 collision-free
# inverse-kinematics solutions existed for the grasp point. Measured collision-free fractions:
# 0.18x0.30 -> 0%, 0.10x0.30 -> 76%, 0.10x0.45 -> 100%, no pedestal -> 0% (link1 hits the table).
PEDESTAL = 0.45             # riser under the arm, so it works over the table
PEDESTAL_DIA = 0.10         # diameter -- the dominant factor; 0.18 blocks the shoulder
CUBE_SIZE = 0.05
CUBE_XY = (0.22, -0.22)     # where the cube starts
PAD_XY = (0.22, 0.24)       # where it must be placed
PAD_SIZE = (0.16, 0.16, 0.006)

# Home posture, in degrees -- the single source of truth for the episode start state (SIM-01).
# Solved by inverse kinematics so the tool points straight down with the tool centre point 30 cm
# above the table, midway between the cube start and the place pad, so the home favours neither.
# Verified collision-free against the cube, table, pad and pedestal.
# Re-derive with solve_home.py whenever the scene geometry changes -- it did for DEC-05.
# Keep positions AND targets equal to this: a mismatch makes the arm jump on startSimulation()
# and throw the cube off the table. See set_home.py.
HOME_Q_DEG = (103.3, -140.4, 119.1, -68.7, 90.0, 0.0)


def look_at(sim, cam, eye, at, up=(0, 0, 1)):
    """Aim a CoppeliaSim camera (it looks down its own -z axis, +y up)."""
    fwd = [a - e for a, e in zip(at, eye)]
    n = math.sqrt(sum(v * v for v in fwd))
    fwd = [v / n for v in fwd]
    z = [-v for v in fwd]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    n = math.sqrt(sum(v * v for v in x))
    x = [v / n for v in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    sim.setObjectMatrix(cam, [x[0], y[0], z[0], eye[0],
                              x[1], y[1], z[1], eye[1],
                              x[2], y[2], z[2], eye[2]], -1)


def main():
    client = RemoteAPIClient()
    sim = client.require('sim')

    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.closeScene()

    # --- workbench ----------------------------------------------------------
    top = sim.createPrimitiveShape(sim.primitiveshape_cuboid, list(TABLE_SIZE))
    sim.setObjectAlias(top, 'workbenchTop')
    sim.setObjectPosition(top, [0, 0, TABLE_TOP_Z - TABLE_SIZE[2] / 2], -1)
    sim.setShapeColor(top, None, sim.colorcomponent_ambient_diffuse, [0.72, 0.62, 0.48])

    parts = [top]
    leg_h = TABLE_TOP_Z - TABLE_SIZE[2]
    for sx in (-1, 1):
        for sy in (-1, 1):
            leg = sim.createPrimitiveShape(sim.primitiveshape_cuboid, [LEG, LEG, leg_h])
            sim.setObjectPosition(leg, [sx * (TABLE_SIZE[0] / 2 - LEG),
                                        sy * (TABLE_SIZE[1] / 2 - LEG),
                                        leg_h / 2], -1)
            sim.setShapeColor(leg, None, sim.colorcomponent_ambient_diffuse, [0.45, 0.38, 0.30])
            parts.append(leg)
    table = sim.groupShapes(parts)
    sim.setObjectAlias(table, 'Workbench')
    sim.setObjectInt32Param(table, sim.shapeintparam_static, 1)
    sim.setObjectInt32Param(table, sim.shapeintparam_respondable, 1)

    # --- pedestal: lifts the arm so it reaches the tabletop elbow-up --------
    ped = sim.createPrimitiveShape(sim.primitiveshape_cylinder,
                                   [PEDESTAL_DIA, PEDESTAL_DIA, PEDESTAL])
    sim.setObjectAlias(ped, 'Pedestal')
    sim.setObjectPosition(ped, [ARM_BASE[0], ARM_BASE[1], TABLE_TOP_Z + PEDESTAL / 2], -1)
    sim.setShapeColor(ped, None, sim.colorcomponent_ambient_diffuse, [0.35, 0.36, 0.40])
    sim.setObjectInt32Param(ped, sim.shapeintparam_static, 1)
    sim.setObjectInt32Param(ped, sim.shapeintparam_respondable, 1)

    # --- UR5 + RG2 gripper --------------------------------------------------
    ur5 = sim.loadModel(COP + '/models/robots/non-mobile/UR5.ttm')
    sim.setObjectPosition(ur5, [ARM_BASE[0], ARM_BASE[1], ARM_BASE[2] + PEDESTAL], -1)

    joints = sim.getObjectsInTree(ur5, sim.sceneobject_joint)
    connection = sim.getObject('./connection', {'proxy': ur5})

    rg2 = sim.loadModel(COP + '/models/components/grippers/RG2.ttm')
    sim.setObjectPose(rg2, sim.getObjectPose(connection, -1), -1)
    sim.setObjectParent(rg2, connection, True)

    # tool centre point: midpoint between the two fingertips, as a dummy on the chain
    lt = sim.getObject('./leftTouch', {'proxy': rg2})
    rt = sim.getObject('./rightTouch', {'proxy': rg2})
    pl = sim.getObjectPosition(lt, connection)
    pr = sim.getObjectPosition(rt, connection)
    tcp_local = [(a + b) / 2 for a, b in zip(pl, pr)]

    tip = sim.createDummy(0.02)
    sim.setObjectAlias(tip, 'tip')
    sim.setObjectParent(tip, connection, False)
    sim.setObjectPosition(tip, tcp_local, connection)
    sim.setObjectOrientation(tip, [0, 0, 0], connection)

    target = sim.createDummy(0.02)
    sim.setObjectAlias(target, 'target')
    sim.setObjectPose(target, sim.getObjectPose(tip, -1), -1)

    # --- object to pick -----------------------------------------------------
    cube = sim.createPrimitiveShape(sim.primitiveshape_cuboid, [CUBE_SIZE] * 3)
    sim.setObjectAlias(cube, 'Cube')
    sim.setObjectPosition(cube, [CUBE_XY[0], CUBE_XY[1], TABLE_TOP_Z + CUBE_SIZE / 2], -1)
    sim.setShapeColor(cube, None, sim.colorcomponent_ambient_diffuse, [0.85, 0.15, 0.12])
    sim.setObjectInt32Param(cube, sim.shapeintparam_static, 0)
    sim.setObjectInt32Param(cube, sim.shapeintparam_respondable, 1)
    sim.setShapeMass(cube, 0.1)

    # --- placement target ---------------------------------------------------
    pad = sim.createPrimitiveShape(sim.primitiveshape_cuboid, list(PAD_SIZE))
    sim.setObjectAlias(pad, 'PlacePad')
    sim.setObjectPosition(pad, [PAD_XY[0], PAD_XY[1], TABLE_TOP_Z + PAD_SIZE[2] / 2], -1)
    sim.setShapeColor(pad, None, sim.colorcomponent_ambient_diffuse, [0.15, 0.65, 0.25])
    sim.setObjectInt32Param(pad, sim.shapeintparam_static, 1)
    sim.setObjectInt32Param(pad, sim.shapeintparam_respondable, 1)

    # --- initial arm posture (elbow up, tool pointing down) ------------------
    q0 = [math.radians(a) for a in HOME_Q_DEG]
    for j, q in zip(joints, q0):
        sim.setJointPosition(j, q)
        sim.setJointTargetPosition(j, q)

    # --- viewpoint for the figure ------------------------------------------
    cam = sim.getObject('/DefaultCamera')
    look_at(sim, cam, eye=[1.05, -1.25, 1.55], at=[0.0, 0.0, 0.80])

    sim.saveScene(SCENE)

    print('joints:', joints)
    print('tip pose:', [round(v, 3) for v in sim.getObjectPose(tip, -1)])
    print('tcp offset in flange frame:', [round(v, 4) for v in tcp_local])
    print('saved:', SCENE)


if __name__ == '__main__':
    main()
