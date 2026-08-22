"""Pose the UR5 at the grasp and render a still image of the scene for the paper.

No dynamics: the arm is posed purely kinematically (inverse kinematics in a
simIK environment, applied to the joints), which is all an illustrative figure
of the target application needs. The frame is rendered off-screen through a
vision sensor, so it carries none of the CoppeliaSim GUI chrome.
"""
import math
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')
FIGDIR = os.path.join(HERE, 'figures')
RES = [1600, 1200]

TABLE = 0.72
CUBE_XY = (0.22, -0.22)
GRASP = [CUBE_XY[0], CUBE_XY[1], TABLE + 0.028]   # fingers straddling the cube
SEED_Q = [80, -90, 85, -85, 90, 0]                # tool already pointing down
# Re-framed for the DEC-05 geometry: the arm base sits 15 cm higher on the new pedestal, and the
# old framing cut both the base and the mount out of the top of the picture.
EYE = [1.25, -1.45, 2.15]      # steep 3/4 view: keeps the floor, not the sky, behind the cell
AT = [-0.02, -0.03, 0.95]

client = RemoteAPIClient()
sim = client.require('sim')
simIK = client.require('simIK')

sim.stopSimulation()
while sim.getSimulationState() != sim.simulation_stopped:
    pass
sim.loadScene(SCENE)

ur5 = sim.getObject('/UR5')
tip = sim.getObject('/UR5/tip')
target = sim.getObject('/target')
arm = [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
       if 'RG2' not in sim.getObjectAlias(j, 2)][:6]

for j, q in zip(arm, SEED_Q):
    sim.setJointPosition(j, math.radians(q))
sim.setObjectPose(target, sim.getObjectPose(tip, -1), -1)

# --- inverse kinematics: walk the tool from the seed pose down to the grasp --
env = simIK.createEnvironment()
grp = simIK.createGroup(env)
simIK.setGroupCalculation(env, grp, simIK.method_damped_least_squares, 0.05, 200)
_, simToIk, _ = simIK.addElementFromScene(env, grp, ur5, tip, target, simIK.constraint_pose)
ikJoints = [simToIk[j] for j in arm]
ikTarget, ikTip = simToIk[target], simToIk[tip]
simIK.syncFromSim(env, [grp])

p0 = simIK.getObjectPose(env, ikTip, -1)[:3]
for i in range(1, 61):                    # small steps keep IK on the elbow-up branch
    s = i / 60
    p = [p0[k] + (GRASP[k] - p0[k]) * s for k in range(3)]
    sim.setObjectPosition(target, p, -1)
    sim.setObjectOrientation(target, [math.pi, 0, 0], -1)   # tool pointing down
    simIK.setObjectPose(env, ikTarget, sim.getObjectPose(target, -1), -1)
    simIK.handleGroup(env, grp, {'syncWorlds': False, 'allowError': True})

for simj, ikj in zip(arm, ikJoints):
    sim.setJointPosition(simj, simIK.getJointPosition(env, ikj))
for alias in ('/UR5/RG2/leftJoint[0]', '/UR5/RG2/rightJoint[0]'):
    sim.setJointPosition(sim.getObject(alias), math.radians(-10))   # fingers open

print('tool at %s (target %s)' % ([round(v, 3) for v in sim.getObjectPosition(tip, -1)],
                                  [round(v, 3) for v in GRASP]))


# --- render -----------------------------------------------------------------
def look_at(obj, eye, at, up=(0, 0, 1)):
    """Aim a vision sensor: it looks along its +z axis."""
    n = math.dist(at, eye)
    z = [(a - e) / n for a, e in zip(at, eye)]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    n = math.sqrt(sum(v * v for v in x))
    x = [v / n for v in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    sim.setObjectMatrix(obj, [x[0], y[0], z[0], eye[0],
                              x[1], y[1], z[1], eye[1],
                              x[2], y[2], z[2], eye[2]], -1)


# the stock floor is only 5x5 m and its edge would show as black sky in the frame
ground = sim.createPrimitiveShape(sim.primitiveshape_cuboid, [24.0, 24.0, 0.01])
sim.setObjectAlias(ground, 'Ground')
sim.setObjectPosition(ground, [0, 0, -0.008], -1)
sim.setShapeColor(ground, None, sim.colorcomponent_ambient_diffuse, [0.82, 0.82, 0.84])
sim.setObjectInt32Param(ground, sim.shapeintparam_static, 1)
sim.setObjectInt32Param(ground, sim.shapeintparam_respondable, 0)

# Far clipping raised from 8 m: with the camera pulled back for the DEC-05 geometry, the 24 m
# ground plane ran past the old far plane and left a black band across the top of the frame.
cam = sim.createVisionSensor(2, [RES[0], RES[1], 0, 0],
                             [0.01, 25.0, math.radians(50), 0.1, 0, 0, 0, 0, 0, 0, 0])
sim.setObjectAlias(cam, 'FigureCam')
sim.setExplicitHandling(cam, 1)
look_at(cam, EYE, AT)

sim.setStepping(True)
sim.startSimulation()
sim.step()                                # one step only: nothing moves noticeably
sim.handleVisionSensor(cam)
img, res = sim.getVisionSensorImg(cam)
sim.stopSimulation()

os.makedirs(FIGDIR, exist_ok=True)
out = os.path.join(FIGDIR, 'coppelia_pick_and_place.png')
sim.saveImage(img, res, 0, out, -1)
print('wrote', out, res)

# The cropped variant is what the thesis includes (as coppelia-scene.png). It used to be produced
# by hand, which meant the figure in the paper could silently drift from the scene; the margins are
# fixed here so `python3 snapshot.py` regenerates exactly what cap4 shows.
CROP = (60, 55, 60, 55)          # left, top, right, bottom, in pixels
try:
    from PIL import Image

    im = Image.open(out)
    w, h = im.size
    crop = im.crop((CROP[0], CROP[1], w - CROP[2], h - CROP[3]))
    cropped = os.path.join(FIGDIR, 'coppelia_pick_and_place_crop.png')
    crop.save(cropped)
    print('wrote', cropped, crop.size)
    paper = os.path.join(HERE, '..', 'Qualificação_Rafael_Ragazoni_Conrado__Gudwin_',
                         'coppelia-scene.png')
    if os.path.isdir(os.path.dirname(paper)):
        crop.save(paper)
        print('wrote', os.path.normpath(paper), '(the figure cap4 includes)')
except ImportError:
    print('Pillow not available: cropped figure not regenerated')
