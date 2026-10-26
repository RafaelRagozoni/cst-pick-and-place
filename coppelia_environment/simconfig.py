"""SIM-08: pin the simulation settings the results depend on, and record them.

cap4's protocol compares each condition against C0 **pairwise**, which only means anything if a
seed reproduces a run. Two things have to hold: the placement must be a pure function of the seed
(SIM-02), and the physics must be reproducible. This module handles the second, and writes the
settings into the run log so a result can always be traced back to the configuration that produced
it -- "which engine was that run on?" should never be answered from memory.

Bullet 2.78 is CoppeliaSim's current default here, not a considered choice; it is pinned so it stays
the same across the grid rather than because it is the best engine. This install also ships MuJoCo
3.2.6, ODE, Newton, Vortex and Bullet 2.83. MuJoCo handles contact markedly better and is the
natural companion if grasping ever becomes real friction (see the parked physics upgrade) -- but
switching engines invalidates every run recorded under the old one, so it is a decision to make
once, deliberately, before the grid starts.

The engine *version* (2.78 vs 2.83) is chosen in the scene's dynamics dialog and is not exposed as
a parameter, so it cannot be pinned or read from here; it is saved in the scene, whose hash every
run.json's fingerprint records (tools/protocol.py), and the loaded plugin is visible in the
CoppeliaSim startup log. The engine's name and CoppeliaSim's version are read from the simulator
itself, so the handshake says what ran, not what this file expects.

Joint limits are pinned here too. The UR5 model's joints span [-360, +360] deg -- a real UR5 is
effectively unbounded -- and Bullet does not enforce a joint's interval under velocity control
anyway: measured, a wrist joint driven at 0.8 rad/s went to 917 deg with the interval set to
+/-180. So the limit is a constant, enforced by the actuator (actions.limit_velocity) and reported by
the observer as a margin (observations.py, for the Safety drive). Changing it means re-checking the
pilot: its solution reaches -151 deg on the shoulder.
"""
import math

TIMESTEP = 0.05
SOLVER_ITERATIONS = 100
JOINT_LIMIT = math.radians(180)     # rad, every arm joint is kept within +/- this
ENGINES = ('bullet', 'ode', 'vortex', 'newton', 'mujoco', 'physx')     # sim.physics_<name>


def pin_physics(sim):
    """Force engine and timestep, then read them back. Raises if they did not take."""
    sim.setInt32Param(sim.intparam_dynamic_engine, sim.physics_bullet)
    sim.setFloatParam(sim.floatparam_simulation_time_step, TIMESTEP)
    sim.setEngineInt32Param(sim.bullet_global_constraintsolvingiterations, -1, SOLVER_ITERATIONS)

    got = physics_signature(sim)
    if got['engine'] != sim.physics_bullet:
        raise RuntimeError('physics engine did not take: %r' % got)
    if abs(got['timestep'] - TIMESTEP) > 1e-9:
        raise RuntimeError('timestep did not take: %r' % got)
    return got


def physics_signature(sim):
    """What a run was actually executed with. Log this alongside the results."""
    try:
        iters = sim.getEngineInt32Param(sim.bullet_global_constraintsolvingiterations, -1)
    except Exception:
        iters = None
    engine = sim.getInt32Param(sim.intparam_dynamic_engine)
    return {
        'engine': engine,
        'engineName': engine_name(sim, engine),
        'timestep': sim.getFloatParam(sim.floatparam_simulation_time_step),
        'solverIterations': iters,
        'jointLimitDeg': math.degrees(JOINT_LIMIT),
    }


def engine_name(sim, engine):
    """The name of engine id `engine`, from the simulator's own sim.physics_* constants; None if it
    is none of ENGINES."""
    return next((n for n in ENGINES if getattr(sim, 'physics_' + n, None) == engine), None)


def simulator(sim):
    """The CoppeliaSim the bridge is connected to, as it reports itself (decoded as its own
    pythonLuaSetupAssistant.lua does)."""
    full = sim.getInt32Param(sim.intparam_program_full_version)
    return {'version': '%d.%d.%d' % (full // 1000000, full // 10000 % 100, full // 100 % 100),
            'revision': sim.getInt32Param(sim.intparam_program_revision), 'fullVersion': full}
