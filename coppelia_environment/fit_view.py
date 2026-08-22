"""Point the CoppeliaSim GUI view at the workcell.

The scene's saved camera pose does not survive the GUI: CoppeliaSim writes its own view state back
over programmatic changes to /DefaultCamera, so `setObjectMatrix` + `saveScene` does not stick and
the view can end up below the table looking at nothing. `sim.cameraFitToView` goes through the view
itself, which does work.

    python3 fit_view.py            # frame the whole cell
    python3 fit_view.py --cube     # zoom in on the cube and the gripper
"""
import argparse

from coppeliasim_zmqremoteapi_client import RemoteAPIClient


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cube', action='store_true', help='frame just the cube and the pad')
    a = ap.parse_args()

    sim = RemoteAPIClient().require('sim')
    names = ['/Cube', '/PlacePad'] if a.cube else ['/Workbench', '/UR5', '/Cube', '/PlacePad']
    handles = [sim.getObject(n) for n in names]
    sim.cameraFitToView(0, handles)          # 0 == the main view
    cam = sim.getObject('/DefaultCamera')
    print('view fitted to %s' % ', '.join(names))
    print('camera now at %s' % [round(v, 3) for v in sim.getObjectPosition(cam, -1)])


if __name__ == '__main__':
    main()
