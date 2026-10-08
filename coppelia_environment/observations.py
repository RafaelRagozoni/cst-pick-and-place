"""SIM-03: assemble the agent's observation from the simulator, once per control cycle.

This is the single place that reads the simulator for perception. Everything downstream -- the goal
predicates (SIM-06), the reward habits, the logger (SIM-07) -- consumes the dict this returns and
never touches `sim` itself. That keeps the goal predicates pure functions, testable offline against
a recorded trajectory with no simulator running.

Field names follow the innerSense / vision schema drafted in DemoCST-Habits/NewArchitecure.md so the
bridge (BRG-02) can serialise this dict directly instead of inventing a second schema.
"""
import math

TABLE_TOP_Z = 0.72

# The salient-event dimensions of cap4 4.3 come from here: gripper state, contact flag and object
# displacement are what make first-contact and first-lift register as novelty. They are not optional.


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
        self.limits = [sim.getJointInterval(j) for j in self.arm]
        # Self-collision that can actually happen on this arm: the gripper folding back onto the
        # upper arm. Checking every link pair each cycle would cost ~30 extra round trips.
        self.rg2 = sim.getObject('/UR5/RG2')
        self.upper = [h for h in sim.getObjectsInTree(self.ur5, sim.sceneobject_shape)
                      if sim.getObjectAlias(h, 2).endswith(('link1_visible', 'link2_visible'))]
        self._prev_cube = None

        # The robot as one collision entity: every collidable shape in the arm and gripper, added
        # one by one rather than as a tree. A tree collection is re-evaluated on every query, so a
        # cube attached by the grasp rule would join it, and "the robot touches the cube" would
        # become true by membership instead of by contact. Created once; collections made while
        # the simulation runs survive stopSimulation (measured), so episode resets keep it valid.
        self.robot = sim.createCollection(0)
        for h in sim.getObjectsInTree(self.ur5, sim.sceneobject_shape):
            if sim.getObjectSpecialProperty(h) & sim.objectspecialproperty_collidable:
                sim.addItemToCollection(self.robot, sim.handle_single, h, 0)

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
    def _joint_limit_proximity(self, q):
        """0 = mid-range, 1 = at a limit.

        NOTE: this UR5 model reports an interval of (-360, 720) deg on every joint, so the
        "mid-range" it measures from is an arbitrary 180 deg and the number is **meaningless**, not
        merely small -- measured up to 0.588 on a normal trajectory. The field is kept so the schema
        matches the design, but it carries no usable information until real limits are imposed
        (a real UR5 is +/-360 deg, i.e. genuinely unbounded, so the honest options are to drop the
        field or to impose a self-chosen workspace limit and measure against that)."""
        out = []
        for v, (cyclic, iv) in zip(q, self.limits):
            if cyclic or iv[1] - iv[0] <= 0:
                out.append(0.0)
                continue
            mid = (iv[0] + iv[1]) / 2
            half = (iv[1] - iv[0]) / 2
            out.append(min(1.0, abs(v - mid) / half))
        return out

    def _hit(self, a, b):
        r = self.sim.checkCollision(a, b)
        return bool(r[0] if isinstance(r, (list, tuple)) else r)

    def _touching_cube(self):
        """Any part of the robot geometrically touching the cube.

        Not the finger force sensors: closing on empty air loads them to ~6.7 N, as much as
        gripping does (grasp_rule.py), so a force threshold reports contact every time the gripper
        closes. Measured over a scripted grasp: this check is false for all 50 steps of closing on
        air, and true from the fingers meeting the cube until the release."""
        return self._hit(self.robot, self.cube)

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
                    # The robot touching the cube -- any link, not only the fingers -- so pushing
                    # the cube counts as contact too.
                    'inContact': self._touching_cube(),
                },
                'jointLimitProximity': self._joint_limit_proximity(q),
                'selfCollision': self._self_collision(),
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
