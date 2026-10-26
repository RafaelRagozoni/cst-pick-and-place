"""Watch episodes of a run log in the CoppeliaSim window, at a followable speed.

    python3 tools/replay.py runs/<batch>/s1 --ep 5                 # one episode
    python3 tools/replay.py runs/<batch>/s1 --ep 100-119           # twenty in a row
    python3 tools/replay.py runs/<batch>/s1 --every 1000 --speed 4 # 0, 1000, 2000... at 4x
    python3 tools/replay.py runs/<batch>/s1 --ep 0 --ep 950-952 --every 100

A replay, not a re-run: no physics. Every step puts the arm joints, the cube and the fingers where
the log says they were, so what you see is what happened, even though Bullet would not repeat the
run. 1x is real time (20 steps/s, 25 s per 500-step episode). A panel shows episode, step, habit,
goal and drives.

Two approximations, both cosmetic: the log keeps the cube's position but not its rotation, so the
cube keeps its starting yaw; and it keeps the gripper's opening, not its finger joints, so the
fingers are posed from a table the replay measures at start-up (close the gripper once, record the
finger poses at each opening).
"""
import argparse
import bisect
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(os.path.dirname(HERE), 'coppelia_environment')
sys.path.insert(0, HERE)
sys.path.insert(0, ENV)
import runlog                                       # noqa: E402

FRAME_LUA = '''
sim = require 'sim'
local simUI = nil
local ui = nil

function frame(arm, q, cube, cubePose, shapes, poses, base, text)
    -- Returns nil, or the Lua error: callScriptFunction alone only says "error in script function".
    local ok, err = pcall(function()
        for i = 1, #arm do sim.setJointPosition(arm[i], q[i]) end
        sim.setObjectPose(cube, cubePose, -1)
        for i = 1, #shapes do sim.setObjectPose(shapes[i], poses[i], base) end
        if ui then simUI.setLabelText(ui, 1, text) end
    end)
    if not ok then return tostring(err) end
end

function makePanel()
    local ok, m = pcall(require, 'simUI')
    if not ok then return false end
    local made, h = pcall(m.create, [[<ui title="Replay" closeable="false" resizable="true"
        placement="relative" position="20,20" size="560,110" layout="vbox">
        <label id="1" text="" word-wrap="true" /></ui>]])
    if not made then return false end
    simUI, ui = m, h
    return true
end
'''


def parse_selection(eps, every):
    singles, ranges = set(), []
    for e in eps or []:
        if '-' in e:
            a, b = e.split('-')
            ranges.append((int(a), int(b)))
        else:
            singles.add(int(e))

    def wanted(ep):
        return (ep in singles or any(a <= ep <= b for a, b in ranges)
                or (every and ep % every == 0))
    return wanted


def collect(log, wanted, limit):
    chosen = []
    for ep, recs, summ in runlog.episodes(log):
        if wanted(ep):
            chosen.append((ep, [r for r in recs if not r.get('done')], summ))
            print('  loaded episode %d' % ep, flush=True)
            if len(chosen) >= limit:
                print('  (stopping at --max %d episodes)' % limit)
                break
    return chosen


def calibrate_fingers(sim, rule, base, shapes):
    """Close the gripper on nothing, with physics, and record the finger poses at each opening."""
    from grasp_rule import set_gripper
    set_gripper(sim, True)
    sim.setStepping(True)
    sim.startSimulation()
    for _ in range(60):
        sim.step()
    set_gripper(sim, False)
    table, last = [], None
    for _ in range(80):
        sim.step()
        w = rule.fingertip_gap()
        table.append((w, [sim.getObjectPose(h, base) for h in shapes]))
        if last is not None and abs(w - last) < 1e-5:
            break
        last = w
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        time.sleep(0.01)
    table.sort(key=lambda t: t[0])
    return [t[0] for t in table], [t[1] for t in table]


def yaw_quat(yaw):
    return [0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('run', help='run folder (s1), or a log file')
    ap.add_argument('--ep', action='append', help='an episode (5) or a range (100-119); repeatable')
    ap.add_argument('--every', type=int, help='every Nth episode: 0, N, 2N, ...')
    ap.add_argument('--speed', type=float, default=1.0, help='1 = real time (20 steps/s)')
    ap.add_argument('--max', type=int, default=50, help='episodes at most')
    ap.add_argument('--keep-open', action='store_true',
                    help='leave the window open at the end until Enter')
    a = ap.parse_args()
    if not a.ep and not a.every:
        ap.error('say which episodes: --ep 5, --ep 100-119, --every 1000')

    (label, log, _), = runlog.find_logs([a.run])
    print('reading %s' % log, flush=True)
    chosen = collect(log, parse_selection(a.ep, a.every), a.max)
    if not chosen:
        raise SystemExit('none of those episodes is in the log (yet)')

    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from simprocess import SimProcess
    from grasp_rule import GraspRule
    with SimProcess(gui=True) as proc:
        sim = RemoteAPIClient(port=proc.rpc_port).require('sim')
        sim.loadScene(os.path.join(ENV, 'pick_and_place.ttt'))
        for setting, value in (('intparam_idle_fps', 0),          # redraw as frames arrive
                               ('boolparam_browser_visible', False),  # more room for the scene
                               ('boolparam_hierarchy_visible', False)):
            try:
                (sim.setInt32Param if setting.startswith('int') else sim.setBoolParam)(
                    getattr(sim, setting), value)
            except Exception:
                pass
        ur5 = sim.getObject('/UR5')
        arm = [j for j in sim.getObjectsInTree(ur5, sim.sceneobject_joint)
               if 'RG2' not in sim.getObjectAlias(j, 2)][:6]
        cube = sim.getObject('/Cube')
        base = sim.getObject('/UR5/RG2')
        # Parents before children: a parent set after its child would carry the child along.
        shapes = sorted(sim.getObjectsInTree(base, sim.sceneobject_shape, 1),
                        key=lambda h: len(sim.getObjectAlias(h, 2).split('/')))
        widths, poses = calibrate_fingers(sim, GraspRule(sim), base, shapes)
        print('finger table: %d openings, %.4f to %.4f m' % (len(widths), widths[0], widths[-1]))

        script = sim.createScript(sim.scripttype_customization, FRAME_LUA, 0, 'lua')
        sim.initScript(script)
        panel = sim.callScriptFunction('makePanel', script)

        def show(r, ep, summ, n_steps):
            o = r['obs']
            q = [j['pos'] for j in o['innerSense']['joints']]
            w = o['innerSense']['gripper']['width']
            k = min(bisect.bisect_left(widths, w), len(widths) - 1)
            cube_pose = list(o['vision']['cube']['pos']) + yaw_quat((summ or {}).get('cube_start', [0, 0, 0])[2])
            d = r.get('drives') or {}
            text = ('episode %d · step %d/%d · %s\nhabit %s · goal %s (%s) · stage %s\n'
                    'drives: curiosity %.2f  task %.2f  safety %.2f  effort %.2f'
                    % (ep, r['step'], n_steps, 'SUCCESS' if (summ or {}).get('success') else 'no success',
                       r.get('habit_id'), r.get('goal'), r.get('goalSource'), r.get('goal_step'),
                       d.get('curiosity', 0), d.get('task', 0), d.get('safety', 0), d.get('effort', 0)))
            err = sim.callScriptFunction('frame', script, arm, q, cube, cube_pose, shapes, poses[k],
                                         base, text)
            if err:
                raise RuntimeError('replay frame failed in the simulator: %s' % err)
            return text

        dt = 0.05 / a.speed
        for ep, recs, summ in chosen:
            print('episode %d: %d steps, %s, stages %s' % (
                ep, len(recs), 'SUCCESS' if (summ or {}).get('success') else 'no success',
                (summ or {}).get('goalsReached') or 'none'), flush=True)
            t0 = t_next = time.time()
            for r in recs:
                text = show(r, ep, summ, len(recs))
                t_next += dt
                time.sleep(max(0.0, t_next - time.time()))
            rate = len(recs) / max(time.time() - t0, 1e-9)
            print('  played at %.0f steps/s (asked %.0f)%s' % (
                rate, 1 / dt, '' if rate > 0.9 / dt else ' -- the window cannot keep up'),
                flush=True)
            if not panel:
                print('  ' + text.replace('\n', ' | '))
            time.sleep(1.0)
        if a.keep_open:
            input('done: press Enter to close the window ')


if __name__ == '__main__':
    main()
