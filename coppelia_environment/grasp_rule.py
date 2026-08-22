"""SIM-04: the environment-layer grasp rule.

The agent never grasps. It only opens and closes the gripper; the *environment* decides when the
object becomes attached, from a physical predicate. That split is what keeps the C1 ablation
meaningful: the agent still has to discover positioning and closing at the right moment, but a
grasp that fails does so for the agent's reasons, not because contact physics needed tuning.

This is CoppeliaSim's own recommended pattern -- the RG2 model ships it as commented-out code and
the parts it needs (attachPoint, attachProxSensor) are already in the scene.

Deliberately transport-agnostic: a plain object with plain methods, so whichever bridge wins
(DEC-03) is a thin wrapper over this rather than a rewrite.
"""
import math

GRIPPER_SIGNAL = 'signal.RG2_open'

# Thresholds, measured on this scene 2026-08-18 (see the notes for the raw numbers):
#   fingertip gap  open 0.1054 m | closed on nothing 0.0045 m | holding a 5 cm cube ~0.05 m
#   force sensors  0.45 N at rest | ~8 N closed on nothing | ~7 N closed on the cube
# Force does NOT discriminate: closing on empty air loads the sensors as much as gripping does,
# because the fingers press against their own linkage. The discriminating signals are the
# proximity sensor (checked against the specific graspable shape, never handle_all -- against
# handle_all it detects the gripper's own fingers) and the fingertip gap.
MIN_OBJECT_GAP = 0.02          # m, fingertips further apart than this => something is in between
MIN_CONTACT_FORCE = 1.0        # N, per finger, confirms the fingers are actually loaded


def set_gripper(sim, opened):
    """Command the gripper.

    Must go through the property API: in CoppeliaSim 4.10 sim.setInt32Signal writes a namespace
    the RG2 script's getIntProperty never reads, so the legacy call silently does nothing.
    """
    sim.setIntProperty(sim.handle_scene, GRIPPER_SIGNAL, 1 if opened else 0)


def gripper_commanded_open(sim):
    return bool(sim.getIntProperty(sim.handle_scene, GRIPPER_SIGNAL, {'noError': True}) or 0)


class GraspRule:
    """Attaches/detaches graspable shapes according to physics. Call update() once per step."""

    def __init__(self, sim, graspable=('/Cube',)):
        self.sim = sim
        self.attach = sim.getObject('/UR5/RG2/attachPoint')
        self.prox = sim.getObject('/UR5/RG2/attachProxSensor')
        self.lfs = sim.getObject('/UR5/RG2/leftForceSensor')
        self.rfs = sim.getObject('/UR5/RG2/rightForceSensor')
        self.lt = sim.getObject('/UR5/RG2/leftTouch')
        self.rt = sim.getObject('/UR5/RG2/rightTouch')
        self.graspable = [sim.getObject(a) for a in graspable]
        self.held = None

    # --- observations ----------------------------------------------------
    def fingertip_gap(self):
        return math.dist(self.sim.getObjectPosition(self.lt, -1),
                         self.sim.getObjectPosition(self.rt, -1))

    def contact_forces(self):
        out = []
        for h in (self.lfs, self.rfs):
            r = self.sim.readForceSensor(h)
            f = r[1] if isinstance(r, (list, tuple)) and len(r) > 1 else [0, 0, 0]
            out.append(math.sqrt(sum(v * v for v in f)))
        return out

    def detected(self):
        """Which graspable shape the proximity sensor sees, if any."""
        for h in self.graspable:
            r = self.sim.checkProximitySensor(self.prox, h)
            hit = r[0] if isinstance(r, (list, tuple)) else r
            if hit:
                return h
        return None

    # --- the rule --------------------------------------------------------
    def update(self):
        """Apply the attach/detach rule for this step. Returns the observable grasp state."""
        sim = self.sim
        opened = gripper_commanded_open(sim)
        gap = self.fingertip_gap()
        fl, fr = self.contact_forces()
        seen = self.detected()

        if self.held is not None:
            if opened:                                   # opening always releases
                sim.setObjectParent(self.held, -1, True)
                # Re-register with the physics engine: a shape that has just been reparented stays
                # kinematically pinned until it is reset, so without this the released cube hangs
                # in mid-air instead of falling.
                sim.resetDynamicObject(self.held)
                self.held = None
        elif not opened and seen is not None and gap > MIN_OBJECT_GAP \
                and fl > MIN_CONTACT_FORCE and fr > MIN_CONTACT_FORCE:
            sim.setObjectParent(seen, self.attach, True)
            self.held = seen

        return {'is_holding': self.held is not None, 'held': self.held,
                'gripper_open': opened, 'fingertip_gap': gap,
                'contact_force': (fl, fr), 'detected': seen}

    def reset(self):
        """Release anything held. Call at every episode reset."""
        if self.held is not None:
            self.sim.setObjectParent(self.held, -1, True)
            self.sim.resetDynamicObject(self.held)
            self.held = None
