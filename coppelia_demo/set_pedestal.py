"""DEC-05: rebuild the pedestal in the saved scene and raise the arm onto it.

The original 0.18 m x 0.30 m riser made the task impossible -- the upper-arm link collided with it
on every approach to the tabletop, so no collision-free inverse-kinematics solution to the grasp
point existed at all. Geometry now comes from build_scene.py (PEDESTAL, PEDESTAL_DIA).

The scene is edited in place rather than rebuilt from build_scene.py, because the saved scene also
contains the Ground plane and FigureCam that snapshot.py adds for the paper figure, and a full
rebuild would drop them.

After running this, HOME_Q_DEG is stale -- the arm base has moved. Run, in order:
    python3 set_pedestal.py
    python3 solve_home.py        # prints the new HOME_Q_DEG; paste it into build_scene.py
    python3 set_home.py          # applies and verifies it
"""
import os

from coppeliasim_zmqremoteapi_client import RemoteAPIClient

from build_scene import ARM_BASE, PEDESTAL, PEDESTAL_DIA, TABLE_TOP_Z

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, 'pick_and_place.ttt')


def main():
    sim = RemoteAPIClient().require('sim')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(SCENE)

    old = sim.getObject('/Pedestal')
    print('old pedestal at %s' % [round(v, 3) for v in sim.getObjectPosition(old, -1)])
    sim.removeObjects([old])

    ped = sim.createPrimitiveShape(sim.primitiveshape_cylinder,
                                   [PEDESTAL_DIA, PEDESTAL_DIA, PEDESTAL])
    sim.setObjectAlias(ped, 'Pedestal')
    sim.setObjectPosition(ped, [ARM_BASE[0], ARM_BASE[1], TABLE_TOP_Z + PEDESTAL / 2], -1)
    sim.setShapeColor(ped, None, sim.colorcomponent_ambient_diffuse, [0.35, 0.36, 0.40])
    sim.setObjectInt32Param(ped, sim.shapeintparam_static, 1)
    sim.setObjectInt32Param(ped, sim.shapeintparam_respondable, 1)

    ur5 = sim.getObject('/UR5')
    sim.setObjectPosition(ur5, [ARM_BASE[0], ARM_BASE[1], TABLE_TOP_Z + PEDESTAL], -1)

    sim.saveScene(SCENE)
    print('pedestal %.2f m dia x %.2f m tall; arm base at z=%.3f' %
          (PEDESTAL_DIA, PEDESTAL, TABLE_TOP_Z + PEDESTAL))
    print('saved:', SCENE)
    print('HOME_Q_DEG is now stale -- run solve_home.py, then set_home.py')


if __name__ == '__main__':
    main()
