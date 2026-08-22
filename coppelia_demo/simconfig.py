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
a settable parameter, so it cannot be pinned from here; the loaded plugin is visible in the
CoppeliaSim startup log.
"""
TIMESTEP = 0.05
SOLVER_ITERATIONS = 100


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
    return {
        'engine': sim.getInt32Param(sim.intparam_dynamic_engine),
        'engineName': 'bullet',
        'timestep': sim.getFloatParam(sim.floatparam_simulation_time_step),
        'solverIterations': iters,
    }
