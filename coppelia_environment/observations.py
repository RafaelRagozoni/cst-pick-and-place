"""SIM-03: assemble the agent's observation from the simulator, once per control cycle.

This is the single place that reads the simulator for perception. Everything downstream -- the goal
predicates (SIM-06), the reward habits, the logger (SIM-07) -- consumes the dict this returns and
never touches `sim` itself. That keeps the goal predicates pure functions, testable offline against
a recorded trajectory with no simulator running.

Field names follow the innerSense / vision schema drafted in DemoCST-Habits/NewArchitecure.md so the
bridge (BRG-02) can serialise this dict directly instead of inventing a second schema.
"""
import math

from simconfig import JOINT_LIMIT

TABLE_TOP_Z = 0.72

# The salient-event dimensions of cap4 4.3 come from here: gripper state, contact flag and object
# displacement are what make first-contact and first-lift register as novelty. They are not optional.

# Contact is read from the physics engine's contact list, not from geometry. Geometric collision
# checks never fire here: the engine stops a link ~0.2 mm short of what it hits, so the meshes never
# overlap (measured: the wrist pressed against the pedestal for 50 steps, checkCollision false
# throughout). A distance check would work but costs 4-20 ms a call. The contact list is walked
# inside the simulator by this function, so the cost is one round trip (~0.6 ms) per cycle.
CONTACT_SCRIPT = 'observerContacts'
CONTACT_LUA = '''
function contacts(robot, others)
    -- For each shape in `others`: is any shape in `robot` in physical contact with it?
    local isRobot = {}
    for i = 1, #robot do isRobot[robot[i]] = true end
    local out = {}
    for k = 1, #others do
        local hit, i = false, 0
        while true do
            local pair = sim.getContactInfo(sim.handle_all, others[k], i)
            if pair == nil or #pair == 0 then break end
            local other = pair[1] == others[k] and pair[2] or pair[1]
            if isRobot[other] then hit = true break end
            i = i + 1
        end
        out[k] = hit
    end
    return out
end
'''


class Observer:
    """Reads one full observation per call. Construct once, after the simulation has started."""

    def __init__(self, sim, grasp_rule, manipulability=True, simIK=None):
        self.sim = sim
        self.simIK = simIK
        self.grasp = grasp_rule
        self.want_manip = manipulability
        self.ur5 = sim.getObject('/UR5')
        self.tip = sim.getObject('/UR5/tip')
        self.cube = sim.getObject('/Cube')
        self.pad = sim.getObject('/PlacePad')
        self.arm = [j for j in sim.getObjectsInTree(self.ur5, sim.sceneobject_joint)
                    if 'RG2' not in sim.getObjectAlias(j, 2)][:6]
        # Self-collision that can actually happen on this arm: the gripper folding back onto the
        # upper arm. Checking every link pair each cycle would cost ~30 extra round trips.
        self.rg2 = sim.getObject('/UR5/RG2')
        self.upper = [h for h in sim.getObjectsInTree(self.ur5, sim.sceneobject_shape)
                      if sim.getObjectAlias(h, 2).endswith(('link1_visible', 'link2_visible'))]
        self._prev_cube = None

        # The robot's shapes, listed once. Listed now, before anything is grasped: the grasp rule
        # parents a held cube into this tree, and it must not become "the robot".
        self.robot_shapes = sim.getObjectsInTree(self.ur5, sim.sceneobject_shape)
        # What the robot must not touch, for the Safety drive -- and last, the cube, for contact.
        # The arm's base and the pedestal are both static, so the base's seat on it never counts.
        self.touch_targets = [sim.getObject(n) for n in ('/Workbench', '/Pedestal', '/PlacePad')]
        self.touch_targets.append(self.cube)
        self._contact_script = self._install_contact_script()

        # Manipulability needs a kinematic model of the chain. Costs two extra round trips per
        # cycle (syncFromSim + computeGroupJacobian); set manipulability=False to drop it.
        self._ik = None
        if self.want_manip and simIK is not None:
            env = simIK.createEnvironment()
            grp = simIK.createGroup(env)
            tgt = sim.getObject('/target')
            simIK.addElementFromScene(env, grp, self.ur5, self.tip, tgt, simIK.constraint_pose)
            self._ik = (env, grp)

    # --- pieces ----------------------------------------------------------
    def _joint_limit_margin(self, q):
        """Radians from each joint to the nearer of +/-JOINT_LIMIT; 0 at the limit.

        A margin, not a 0-1 "proximity" measured from mid-range: at home the shoulder sits at
        -140 deg, so a proximity would already read 0.78 and the Safety drive would start high.
        How fast the drive rises as the margin shrinks is the Drive Generator's choice."""
        return [JOINT_LIMIT - abs(v) for v in q]

    def _hit(self, a, b):
        r = self.sim.checkCollision(a, b)
        return bool(r[0] if isinstance(r, (list, tuple)) else r)

    def _install_contact_script(self):
        """(Re)create the in-simulator contact function. A copy saved into the scene by accident
        is replaced, so the code that runs is always this file's."""
        sim = self.sim
        old = sim.getObject('/' + CONTACT_SCRIPT, {'noError': True})
        if old != -1:
            sim.removeObjects([old])
        h = sim.createScript(sim.scripttype_customization, CONTACT_LUA, 0, 'lua')
        sim.setObjectAlias(h, CONTACT_SCRIPT)
        sim.initScript(h)       # otherwise not callable until the next simulation pass
        return h

    def _contacts(self):
        """(robot touches table, pedestal or pad; robot touches the cube), from the physics engine.

        Cube contact is not the finger force sensors: closing on empty air loads them to ~6.7 N,
        as much as gripping does (grasp_rule.py), so a force threshold reports contact every time
        the gripper closes."""
        try:
            hit = self.sim.callScriptFunction('contacts', self._contact_script,
                                              self.robot_shapes, self.touch_targets)
        except Exception:
            # A script created while the simulation runs is destroyed by stopSimulation, which every
            # episode reset calls (unlike collections, which survive). Reinstall once and retry.
            self._contact_script = self._install_contact_script()
            hit = self.sim.callScriptFunction('contacts', self._contact_script,
                                              self.robot_shapes, self.touch_targets)
        return any(hit[:-1]), hit[-1]

    def _self_collision(self):
        return any(self._hit(self.rg2, h) for h in self.upper)

    def _manipulability(self):
        """sqrt(det(J J^T)) -- Yoshikawa's measure, 0 at a singularity. None if unavailable."""
        if self._ik is None:
            return None
        env, grp = self._ik
        try:
            self.simIK.syncFromSim(env, [grp])
            flat, _ = self.simIK.computeGroupJacobian(env, grp)
        except Exception:
            return None
        n = len(self.arm)
        rows = len(flat) // n
        if rows == 0:
            return None
        J = [flat[r * n:(r + 1) * n] for r in range(rows)]        # row major: rows=constraints
        # JJ^T, then determinant by Gaussian elimination (rows <= 6, so this is negligible)
        A = [[sum(J[a][k] * J[b][k] for k in range(n)) for b in range(rows)] for a in range(rows)]
        det = 1.0
        for i in range(rows):
            piv = max(range(i, rows), key=lambda r: abs(A[r][i]))
            if abs(A[piv][i]) < 1e-12:
                return 0.0
            if piv != i:
                A[i], A[piv] = A[piv], A[i]
                det = -det
            det *= A[i][i]
            for r in range(i + 1, rows):
                f = A[r][i] / A[i][i]
                for c in range(i, rows):
                    A[r][c] -= f * A[i][c]
        return math.sqrt(abs(det))

    # --- the observation -------------------------------------------------
    def read(self):
        sim = self.sim
        q = [sim.getJointPosition(j) for j in self.arm]
        qd = [sim.getJointVelocity(j) for j in self.arm]
        tau = [sim.getJointForce(j) for j in self.arm]
        eef = sim.getObjectPose(self.tip, -1)
        cube_p = sim.getObjectPosition(self.cube, -1)
        pad_p = sim.getObjectPosition(self.pad, -1)
        lin, _ = sim.getObjectVelocity(self.cube)[:2]
        g = self.grasp.update()
        env_contact, cube_contact = self._contacts()

        disp = 0.0 if self._prev_cube is None else math.dist(self._prev_cube, cube_p)
        self._prev_cube = list(cube_p)

        return {
            't': sim.getSimulationTime(),
            'innerSense': {
                'joints': [{'j': i, 'pos': q[i], 'vel': qd[i], 'torque': tau[i]} for i in range(6)],
                'eef': {'pos': eef[:3], 'quat': eef[3:]},
                'gripper': {
                    'width': g['fingertip_gap'],
                    'commanded_open': g['gripper_open'],
                    'isHolding': g['is_holding'],
                    'contactForce': list(g['contact_force']),
                    # The robot touching the cube -- any link, not only the fingers, so pushing
                    # the cube counts too. A held cube always counts: once attached it is pinned to
                    # the gripper and may stop producing contacts of its own.
                    'inContact': g['is_holding'] or cube_contact,
                },
                'jointLimitMargin': self._joint_limit_margin(q),
                'selfCollision': self._self_collision(),
                # Any arm link or the gripper touching the table, the pedestal or the pad.
                'envCollision': env_contact,
                'manipulability': self._manipulability(),
            },
            'vision': {
                'cube': {'pos': list(cube_p), 'vel': list(lin), 'visible': True},
                'pad': {'pos': list(pad_p), 'visible': True},
            },
            'derived': {
                'eefToCube': math.dist(eef[:3], cube_p),
                'cubeToPadXY': math.dist(cube_p[:2], pad_p[:2]),
                'cubeHeightAboveTable': cube_p[2] - TABLE_TOP_Z,
                'cubeDisplacement': disp,
            },
        }

    def reset(self):
        self._prev_cube = None
