"""The primitive action set, in the declarative record schema of cap4 4.4.1.

A habit is an ordered list of records `{action, joint, angle, speed, force, step}`. Records sharing a
`step` run in parallel; increasing `step` values run in sequence. The same schema is the motor
command, the pool representation, and the feature source for credit assignment -- so this module
defines the *records*, knows how to apply one to the simulator, and knows when a step is finished.
It does not know about habits, pools, or selection: that is the CST side (WP2).

A MOVE record means "rotate `joint` by `angle` radians at `speed` rad/s". The angle is **relative**
to where the joint was when the step started, and its sign is the direction; `speed` is a magnitude.
A step ends when perception shows every joint has turned through its angle (cap4 4.3.3: "a joint at
its commanded angle"). StepCompletion below is that rule, as a pure function of observations, so the
random baseline here and the PlanTracker on the CST side end a step the same way.

On the wire the angle is what is *still to go*: each cycle the sender passes the remaining angle,
and the actuator never turns a joint faster than would cover it in one tick. That lands a step on
its angle instead of overshooting by up to one tick of travel, and it keeps the bridge stateless.
StepCompletion.commands() produces exactly those records.

The primary repertoire is cap4's: joint rotations in either direction for each of the six joints,
plus gripper open/close -- **14 primitives**, no pre-built macros.

`force` is present in every record but frozen at GRIP_FORCE_N and never varied (DEC-02): with the
environment-side grasp rule, gripping force has no observable consequence, so letting mutation
explore it would inflate the search space for nothing. Unfreezing it is a one-line change here plus
one in the mutation operator.
"""
import math

from simconfig import JOINT_LIMIT

MOVE, GRAB, HOLD = 'MOVE', 'GRAB', 'HOLD'

PRIMITIVE_ANGLE = math.radians(1.0)   # rad, the rotation of one primitive joint move
JOINT_SPEED = 0.4        # rad/s; one 50 ms tick at this speed turns a joint ~1.1 deg (measured)
GRIP_FORCE_N = 20.0      # frozen, see DEC-02

# StepCompletion thresholds. Measured on this scene: a velocity-controlled joint reaches 95-99% of
# its commanded travel within the tick, and the RG2 moves its fingertips ~2.5 mm per tick, starting
# one tick after the command.
ANGLE_TOL = math.radians(0.1)     # rad, a joint this close to its angle has arrived
STALL_ANGLE = math.radians(0.01)  # rad per tick; slower than this the joint is blocked
GRIP_SETTLED = 0.0005             # m per tick; slower than this the fingers have stopped
GRIP_MIN_TICKS = 3                # the fingers start moving a tick late; never judge before this
STEP_TICK_CAP = 400               # backstop: no step runs longer than this


def move(joint, direction, angle=PRIMITIVE_ANGLE, speed=JOINT_SPEED, step=0):
    return {'action': MOVE, 'joint': int(joint), 'angle': direction * angle, 'speed': speed,
            'force': GRIP_FORCE_N, 'step': step}


def grab(opening, step=0):
    """opening=True releases. cap4: 'a GRAB with negative force expresses release'."""
    return {'action': GRAB, 'joint': -1, 'angle': 0.0, 'speed': 0.0,
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
    return 'move_j%d_%s' % (rec['joint'], 'pos' if rec['angle'] > 0 else 'neg')


def tick_velocity(rec, dt):
    """Joint velocity for one tick of a MOVE record whose `angle` is the angle still to go."""
    return math.copysign(min(abs(rec['speed']), abs(rec['angle']) / dt), rec['angle'])


def limit_velocity(v, q, dt, limit=JOINT_LIMIT):
    """Clip a tick's velocity so the joint does not pass +/-limit. A joint already outside may only
    move back in; a command toward the range is untouched, and nothing un-commanded ever moves."""
    if v > 0:
        return max(0.0, min(v, (limit - q) / dt))
    if v < 0:
        return min(0.0, max(v, (-limit - q) / dt))
    return 0.0


def joint_positions(obs):
    return [j['pos'] for j in obs['innerSense']['joints']]


def _width(obs):
    return obs['innerSense']['gripper']['width']


class StepCompletion:
    """Follows one habit step -- the records sharing a step index -- until it is over.

    Feed it the observation after every tick. Pure: it reads observation dicts and never touches the
    simulator, so it can be tested offline and ported as-is to the PlanTracker.

    A MOVE record is finished when its joint has turned through `angle` (within ANGLE_TOL) or has
    stopped turning, which is what a joint at its limit or pressed against the table does. A GRAB
    record is finished when the fingers stop moving -- on the cube, on each other, or fully open.
    The step is over when every record is finished.
    """

    def __init__(self, records, obs):
        self.records = list(records)
        self.q0 = joint_positions(obs)
        self.q_prev = self.q0
        self.w_prev = _width(obs)
        self.ticks = 0
        self.finished = [False] * len(self.records)
        self.stalled = [False] * len(self.records)

    def remaining(self, rec, obs):
        """Signed angle the record's joint still has to turn."""
        turned = joint_positions(obs)[rec['joint']] - self.q0[rec['joint']]
        return rec['angle'] - turned

    def commands(self, obs):
        """The records to send this tick: unfinished ones, MOVE angles replaced by what is left."""
        out = []
        for rec, done in zip(self.records, self.finished):
            if done:
                continue
            if rec['action'] == MOVE:
                rec = dict(rec, angle=self.remaining(rec, obs))
            out.append(rec)
        return out

    def update(self, obs):
        """Account for one more tick. Returns None while running, else 'done', 'stalled' or
        'timeout' -- 'stalled' when any MOVE ended by stopping rather than by arriving."""
        self.ticks += 1
        q, w = joint_positions(obs), _width(obs)
        for i, rec in enumerate(self.records):
            if self.finished[i]:
                continue
            if rec['action'] == MOVE:
                j = rec['joint']
                if abs(self.remaining(rec, obs)) <= ANGLE_TOL:
                    self.finished[i] = True
                elif self.ticks >= 2 and abs(q[j] - self.q_prev[j]) < STALL_ANGLE:
                    self.finished[i] = self.stalled[i] = True
            elif rec['action'] == GRAB:
                if self.ticks >= GRIP_MIN_TICKS and abs(w - self.w_prev) < GRIP_SETTLED:
                    self.finished[i] = True
            else:                                   # HOLD: one tick
                self.finished[i] = True
        self.q_prev, self.w_prev = q, w
        if all(self.finished):
            return 'stalled' if any(self.stalled) else 'done'
        if self.ticks >= STEP_TICK_CAP:
            return 'timeout'
        return None


class Actuator:
    """Applies command records to the simulator. One instance per session."""

    def __init__(self, sim, arm_joints):
        self.sim = sim
        self.arm = arm_joints
        self.dt = sim.getSimulationTimeStep()

    def use_velocity_control(self):
        """Switch the arm to velocity control. Must be called after every start: the joints are
        stored in position mode in the scene, and `speed` in the record schema is a velocity."""
        for j in self.arm:
            self.sim.setObjectInt32Param(j, self.sim.jointintparam_dynctrlmode,
                                         self.sim.jointdynctrl_velocity)

    def apply(self, records, q):
        """Apply one tick's worth of records. `q`: the arm's joint positions now (the latest
        observation's), needed because the joint limit is enforced here -- see simconfig.

        Joints not named by any record are commanded to zero velocity, not left free -- a stale
        velocity command would otherwise keep running after the habit that issued it ended.
        """
        from grasp_rule import set_gripper
        vel = [0.0] * len(self.arm)
        for rec in records:
            if rec['action'] == MOVE and 0 <= rec['joint'] < len(self.arm):
                j = rec['joint']
                vel[j] = limit_velocity(tick_velocity(rec, self.dt), q[j], self.dt)
            elif rec['action'] == GRAB:
                set_gripper(self.sim, rec['force'] < 0)
            # HOLD: issue no command; the zero-velocity default already holds position.
        for j, v in zip(self.arm, vel):
            self.sim.setJointTargetVelocity(j, v)
