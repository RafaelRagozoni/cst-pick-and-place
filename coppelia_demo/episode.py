"""SIM-02: deterministic episode reset and seeded object placement.

cap4 4.5 requires every condition to see the *same* sequence of cube and target poses, so the
C0-vs-Cx comparisons are **paired** rather than independent -- the Mann-Whitney tests in the
protocol assume that pairing. The placement therefore depends only on `(run_seed, episode_index)`
and never on the condition, the wall clock, or anything the agent did.

Placement policy follows DEC-04:
  * target zone  -- FIXED. cap4 4.5 permits "fixed or mildly randomised"; habits are open-loop
    joint-space programs, so randomising both ends puts first success much further away.
  * cube pose    -- FIXED for the WP3 gate (cap5 requires the gate to run "on a fixed cube pose"),
    with a seeded annulus available for WP4.

`sample_cube()` is a pure function: same inputs, same output, no simulator involved, so the pairing
property can be tested without standing up CoppeliaSim.

The annulus bounds are geometric -- on the table, clear of the pad -- and, since DEC-05 fixed the
pedestal, they have been **verified against the arm's reachable workspace**: 40 of 40 sampled poses
are reachable collision-free (2026-08-18). Re-run that check if the geometry changes again; before
DEC-05 nothing on the tabletop was reachable at all.
"""
import math

import numpy as np

from build_scene import HOME_Q_DEG, TABLE_TOP_Z, TABLE_SIZE, CUBE_SIZE, CUBE_XY, PAD_XY, ARM_BASE
from grasp_rule import set_gripper

CUBE_Z = TABLE_TOP_Z + CUBE_SIZE / 2
TABLE_MARGIN = 0.08          # m, keep the cube off the table edge
MIN_CUBE_PAD_GAP = 0.15      # m, the cube must not start on the target zone

# Annulus about the arm base, used only in mode='annulus'. Verified reachable post-DEC-05.
REACH_R_MIN = 0.45
REACH_R_MAX = 0.62
REACH_THETA = (math.radians(-55), math.radians(10))


def _rng(run_seed, episode_index):
    """Independent, reproducible stream per episode. Deliberately excludes the condition."""
    return np.random.default_rng(np.random.SeedSequence([int(run_seed), int(episode_index)]))


def sample_cube(run_seed, episode_index, mode='fixed'):
    """Return (x, y, yaw) for the cube. Pure function -- no simulator, no globals."""
    if mode == 'fixed':
        return (CUBE_XY[0], CUBE_XY[1], 0.0)
    if mode != 'annulus':
        raise ValueError('unknown placement mode: %r' % mode)

    rng = _rng(run_seed, episode_index)
    half_x = TABLE_SIZE[0] / 2 - TABLE_MARGIN
    half_y = TABLE_SIZE[1] / 2 - TABLE_MARGIN
    for _ in range(500):                       # rejection sampling; the region is generous
        r = math.sqrt(rng.uniform(REACH_R_MIN ** 2, REACH_R_MAX ** 2))   # area-uniform
        th = rng.uniform(*REACH_THETA)
        x = ARM_BASE[0] + r * math.cos(th)
        y = ARM_BASE[1] + r * math.sin(th)
        if abs(x) > half_x or abs(y) > half_y:
            continue
        if math.dist((x, y), PAD_XY) < MIN_CUBE_PAD_GAP:
            continue
        return (x, y, float(rng.uniform(-math.pi, math.pi)))
    raise RuntimeError('could not place the cube: annulus and table bounds do not intersect')


class EpisodeReset:
    """Puts the world back to a reproducible start state. Construct once per session."""

    def __init__(self, sim, grasp_rule, observer=None, mode='fixed', settle_steps=10,
                 on_start=None):
        self.sim = sim
        self.grasp = grasp_rule
        self.observer = observer
        self.mode = mode
        self.settle_steps = settle_steps
        # Called after startSimulation, before the settle steps. The runner uses it to establish
        # velocity control, so every episode settles under the same control regime.
        self.on_start = on_start
        self.ur5 = sim.getObject('/UR5')
        self.cube = sim.getObject('/Cube')
        self.pad = sim.getObject('/PlacePad')
        self.arm = [j for j in sim.getObjectsInTree(self.ur5, sim.sceneobject_joint)
                    if 'RG2' not in sim.getObjectAlias(j, 2)][:6]

    def reset(self, run_seed, episode_index):
        sim = self.sim
        # An episode can end while the cube is still attached. stopSimulation() below does revert
        # the parenting on its own (verified), so this call is not what frees the cube -- it is
        # what clears GraspRule's internal `held`, which would otherwise report is_holding=True
        # into the first observation of the next episode.
        self.grasp.reset()

        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            pass

        # Poses are written while STOPPED. Dynamic objects are restored to their scene-stored pose
        # on stop, so anything written mid-run would be silently discarded.
        x, y, yaw = sample_cube(run_seed, episode_index, self.mode)
        sim.setObjectPosition(self.cube, [x, y, CUBE_Z], -1)
        sim.setObjectOrientation(self.cube, [0.0, 0.0, yaw], -1)
        sim.setObjectPosition(self.pad, [PAD_XY[0], PAD_XY[1], TABLE_TOP_Z + 0.003], -1)
        for j, deg in zip(self.arm, HOME_Q_DEG):
            sim.setJointPosition(j, math.radians(deg))
            sim.setJointTargetPosition(j, math.radians(deg))

        sim.setStepping(True)
        sim.startSimulation()

        # Establish the control regime BEFORE settling, then zero every target velocity. Both
        # matter for reproducibility: the joints' control mode persists across episodes, so without
        # this the first episode of a run settled in whatever mode the previous run left behind
        # (position control on a freshly loaded scene, velocity control afterwards) and diverged
        # from every later episode, which were bit-exact.
        if self.on_start is not None:
            self.on_start()
        for j in self.arm:
            sim.setJointTargetVelocity(j, 0.0)

        # The RG2 script closes the gripper whenever no signal is set, and only the property API
        # reaches it -- the legacy sim.setInt32Signal is inert in 4.10.
        set_gripper(sim, True)
        for _ in range(self.settle_steps):
            sim.step()

        if self.observer is not None:
            self.observer.reset()
        return {'cube': (x, y, yaw), 'pad': tuple(PAD_XY), 'seed': run_seed, 'episode': episode_index}
