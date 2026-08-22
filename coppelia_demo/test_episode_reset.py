"""SIM-02 acceptance: deterministic reset and paired placement.

Part 1 runs offline (pure sampling). Part 2 needs CoppeliaSim open on the scene.

    python3 test_episode_reset.py
"""
import math
import sys
import time

from episode import (sample_cube, EpisodeReset, CUBE_Z, MIN_CUBE_PAD_GAP, TABLE_MARGIN)
from build_scene import HOME_Q_DEG, TABLE_SIZE, PAD_XY


def part1_sampling():
    print('--- part 1: placement sampling (offline) ---')
    ok = True

    # Repeatability: the same (seed, episode) must give the same pose, every time.
    a = [sample_cube(7, i, 'annulus') for i in range(25)]
    b = [sample_cube(7, i, 'annulus') for i in range(25)]
    same = (a == b)
    print('  same seed, same sequence      : %s' % ('PASS' if same else 'FAIL'))
    ok &= same

    # Pairing: two *conditions* are just two runs at the same seed. They must agree episode by
    # episode -- this is what makes the C0-vs-Cx comparisons paired.
    c0 = [sample_cube(7, i, 'annulus') for i in range(25)]
    c3 = [sample_cube(7, i, 'annulus') for i in range(25)]
    paired = (c0 == c3)
    print('  two conditions, same seed     : %s' % ('PASS' if paired else 'FAIL'))
    ok &= paired

    # Different seeds must actually differ, or the "independent seeds" in the protocol are a lie.
    d = [sample_cube(8, i, 'annulus') for i in range(25)]
    differs = (a != d)
    print('  different seed, different seq : %s' % ('PASS' if differs else 'FAIL'))
    ok &= differs

    # Episodes within a run must vary, otherwise randomisation is not happening.
    varied = len(set((round(x, 6), round(y, 6)) for x, y, _ in a)) > 20
    print('  episodes vary within a run    : %s' % ('PASS' if varied else 'FAIL'))
    ok &= varied

    # Constraints hold for every sample.
    hx = TABLE_SIZE[0] / 2 - TABLE_MARGIN
    hy = TABLE_SIZE[1] / 2 - TABLE_MARGIN
    bad = [p for p in [sample_cube(s, i, 'annulus') for s in range(6) for i in range(40)]
           if abs(p[0]) > hx or abs(p[1]) > hy or math.dist(p[:2], PAD_XY) < MIN_CUBE_PAD_GAP]
    print('  on table, clear of the pad    : %s (%d violations of 240)'
          % ('PASS' if not bad else 'FAIL', len(bad)))
    ok &= not bad

    fixed = all(sample_cube(s, i) == (0.22, -0.22, 0.0) for s in range(4) for i in range(5))
    print("  mode='fixed' really is fixed  : %s" % ('PASS' if fixed else 'FAIL'))
    ok &= fixed
    return ok


def part2_reset():
    print('\n--- part 2: simulator reset (needs CoppeliaSim) ---')
    import os
    from coppeliasim_zmqremoteapi_client import RemoteAPIClient
    from grasp_rule import GraspRule
    from observations import Observer

    c = RemoteAPIClient()
    sim = c.require('sim')
    simIK = c.require('simIK')
    sim.stopSimulation()
    while sim.getSimulationState() != sim.simulation_stopped:
        pass
    sim.loadScene(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pick_and_place.ttt'))
    sim.setStepping(True)
    sim.startSimulation()

    rule = GraspRule(sim)
    obs = Observer(sim, rule, manipulability=False)
    ep = EpisodeReset(sim, rule, obs, mode='annulus')
    ok = True

    # A reset must land the world exactly where sampling says it should.
    info = ep.reset(7, 3)
    x, y, yaw = info['cube']
    cp = sim.getObjectPosition(ep.cube, -1)
    placed = math.dist(cp, [x, y, CUBE_Z]) < 1e-3
    print('  cube at the sampled pose      : %s (%.5f m off)'
          % ('PASS' if placed else 'FAIL', math.dist(cp, [x, y, CUBE_Z])))
    ok &= placed

    q = [math.degrees(sim.getJointPosition(j)) for j in ep.arm]
    home_ok = max(abs(a - b) for a, b in zip(q, HOME_Q_DEG)) < 0.5
    print('  arm back at HOME_Q_DEG        : %s (max %.3f deg off)'
          % ('PASS' if home_ok else 'FAIL', max(abs(a - b) for a, b in zip(q, HOME_Q_DEG))))
    ok &= home_ok

    gripper_open = obs.read()['innerSense']['gripper']['width'] > 0.05
    print('  gripper open after reset      : %s' % ('PASS' if gripper_open else 'FAIL'))
    ok &= gripper_open

    # An episode can end while the cube is still held. The next reset must clear it -- both the
    # simulator's parenting (which stopSimulation reverts by itself) and GraspRule's `held`, which
    # would otherwise leak a stale is_holding=True into the next episode's first observation.
    sim.setObjectParent(ep.cube, rule.attach, True)
    rule.held = ep.cube
    for _ in range(5):
        sim.step()
    ep.reset(7, 4)
    detached = sim.getObjectParent(ep.cube) == -1 and rule.held is None \
        and not obs.read()['innerSense']['gripper']['isHolding']
    print('  stale hold cleared on reset   : %s' % ('PASS' if detached else 'FAIL'))
    ok &= detached

    # Same episode index twice must give an identical world -- the ARM as well as the cube. An
    # earlier version of this check compared only the cube, which is trivially reproducible, and
    # would have passed while the arm landed in a slightly different state every time.
    def world():
        return (sim.getObjectPosition(ep.cube, -1),
                [sim.getJointPosition(j) for j in ep.arm])

    ep.reset(7, 11)
    c1, q1 = world()
    ep.reset(7, 99)
    ep.reset(7, 11)
    c2, q2 = world()
    dc = math.dist(c1, c2)
    dq = max(abs(a - b) for a, b in zip(q1, q2))
    repeat = dc < 1e-9 and dq < 1e-9
    print('  replaying an episode is exact : %s (cube %.2e m, joints %.2e rad)'
          % ('PASS' if repeat else 'FAIL', dc, dq))
    ok &= repeat

    t0 = time.time()
    for i in range(10):
        ep.reset(7, i)
    dt = (time.time() - t0) / 10
    print('  reset cost                    : %.3f s each' % dt)

    sim.stopSimulation()
    return ok


if __name__ == '__main__':
    a = part1_sampling()
    b = part2_reset()
    print('\nSIM-02 ACCEPTANCE: %s' % ('PASS' if (a and b) else 'FAIL'))
    raise SystemExit(0 if (a and b) else 1)
