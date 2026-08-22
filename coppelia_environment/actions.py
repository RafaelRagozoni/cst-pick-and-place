"""The primitive action set, in the declarative record schema of cap4 4.4.1.

A habit is an ordered list of records `{action, joint, speed, force, step}`. Records sharing a
`step` run in parallel; increasing `step` values run in sequence. The same schema is the motor
command, the pool representation, and the feature source for credit assignment -- so this module
defines the *records*, and knows how to apply one to the simulator. It does not know about habits,
pools, or selection: that is the CST side (WP2).

The primary repertoire is cap4's: joint rotations in either direction for each of the six joints,
plus gripper open/close -- **14 primitives**, no pre-built macros.

`force` is present in every record but frozen at GRIP_FORCE_N and never varied (DEC-02): with the
environment-side grasp rule, gripping force has no observable consequence, so letting mutation
explore it would inflate the search space for nothing. Unfreezing it is a one-line change here plus
one in the mutation operator.
"""
MOVE, GRAB, HOLD = 'MOVE', 'GRAB', 'HOLD'

JOINT_SPEED = 0.4        # rad/s, the magnitude of one primitive joint rotation
GRIP_FORCE_N = 20.0      # frozen, see DEC-02


def move(joint, direction, speed=JOINT_SPEED, step=0):
    return {'action': MOVE, 'joint': int(joint), 'speed': direction * speed,
            'force': GRIP_FORCE_N, 'step': step}


def grab(opening, step=0):
    """opening=True releases. cap4: 'a GRAB with negative force expresses release'."""
    return {'action': GRAB, 'joint': -1, 'speed': 0.0,
            'force': -GRIP_FORCE_N if opening else GRIP_FORCE_N, 'step': step}


def primitive_repertoire():
    """The 14 single-record habits the agent starts from, all at zero fitness."""
    out = []
    for j in range(6):
        for d in (+1, -1):
            out.append([move(j, d)])
    out.append([grab(True)])
    out.append([grab(False)])
    return out


def record_id(rec):
    """Stable name for a record, used as the habit id in logs."""
    if rec['action'] == GRAB:
        return 'grab_open' if rec['force'] < 0 else 'grab_close'
    return 'move_j%d_%s' % (rec['joint'], 'pos' if rec['speed'] > 0 else 'neg')


class Actuator:
    """Applies command records to the simulator. One instance per session."""

    def __init__(self, sim, arm_joints):
        self.sim = sim
        self.arm = arm_joints

    def use_velocity_control(self):
        """Switch the arm to velocity control. Must be called after every start: the joints are
        stored in position mode in the scene, and `speed` in the record schema is a velocity."""
        for j in self.arm:
            self.sim.setObjectInt32Param(j, self.sim.jointintparam_dynctrlmode,
                                         self.sim.jointdynctrl_velocity)

    def apply(self, records):
        """Apply one step's worth of records (those sharing the lowest `step` value).

        Joints not named by any record are commanded to zero velocity, not left free -- a stale
        velocity command would otherwise keep running after the habit that issued it ended.
        """
        from grasp_rule import set_gripper
        vel = [0.0] * len(self.arm)
        for rec in records:
            if rec['action'] == MOVE and 0 <= rec['joint'] < len(self.arm):
                vel[rec['joint']] = rec['speed']
            elif rec['action'] == GRAB:
                set_gripper(self.sim, rec['force'] < 0)
            # HOLD: issue no command; the zero-velocity default already holds position.
        for j, v in zip(self.arm, vel):
            self.sim.setJointTargetVelocity(j, v)
