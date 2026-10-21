"""SIM-08 / BAS-01: what the handshake says about the simulator comes from the simulator.

Offline, no CoppeliaSim: a fake `sim` with the constants and parameters the real one has (the ids
are CoppeliaSim 4.10's). test_bridge.py checks the same against the live one.

    python3 test_simconfig.py
"""
import simconfig

FAILS = []


class FakeSim:
    physics_bullet, physics_ode, physics_vortex, physics_newton, physics_mujoco = 0, 1, 2, 3, 4
    intparam_dynamic_engine, intparam_program_full_version, intparam_program_revision = 10, 11, 12
    floatparam_simulation_time_step = 20
    bullet_global_constraintsolvingiterations = 30

    def __init__(self, engine, full=4100000, revision=0):
        self.ints = {10: engine, 11: full, 12: revision}

    def getInt32Param(self, k):
        return self.ints[k]

    def getFloatParam(self, k):
        return 0.05

    def getEngineInt32Param(self, k, obj):
        return 100


def check(name, ok):
    print('  %-60s %s' % (name, 'PASS' if ok else 'FAIL'))
    if not ok:
        FAILS.append(name)


def main():
    check('Bullet is named bullet', simconfig.physics_signature(FakeSim(0))['engineName'] == 'bullet')
    check('MuJoCo is named mujoco, not bullet',
          simconfig.physics_signature(FakeSim(4))['engineName'] == 'mujoco')
    check('an id that is no engine has no name', simconfig.engine_name(FakeSim(0), 9) is None)
    check('physx, absent from this sim, is skipped, not an error',
          simconfig.engine_name(FakeSim(0), 5) is None)
    s = simconfig.simulator(FakeSim(0, full=4100000, revision=0))
    check('4100000 rev 0 is 4.10.0 rev 0', s == {'version': '4.10.0', 'revision': 0,
                                                 'fullVersion': 4100000})
    check('4090102 is 4.9.1', simconfig.simulator(FakeSim(0, full=4090102))['version'] == '4.9.1')
    print('\nsimconfig: %s' % ('PASS' if not FAILS else 'FAIL (%d)' % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
