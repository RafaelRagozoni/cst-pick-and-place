"""SIM-06: the pick-and-place goal step list, and the episode success test.

cap4 4.5 defines the task as four goal steps -- reach, grasp, transport, release -- tracked by a
planner-less TROCA-style step mechanism: the step advances when its predicate is met, and GoalMO is
re-emitted only on a real transition.

Every predicate here is a **pure function of one observation dict** (see observations.py). Nothing
in this file touches the simulator, so the whole goal layer can be replayed and tested offline
against a recorded trajectory -- which is exactly how its acceptance test runs.

Thresholds are DEC-04's starting values. `EPS_TASK` also appears in the proposal text, so changing
it means editing the paper too.
"""
import math

REACH_DIST = 0.05        # m, end-effector to cube
EPS_TASK = 0.05          # m, cube centre to pad centre (xy) for success
TRANSPORT_XY = 0.05      # m, held cube within this of the pad centre counts as "over the target"
TRANSPORT_MIN_LIFT = 0.03    # m above the table, so "over the pad" cannot fire while still resting
SETTLE_SPEED = 0.01      # m/s
SETTLE_STEPS = 10        # consecutive observations below SETTLE_SPEED before "settled"

STEPS = ('reach', 'grasp', 'transport', 'release')


# --- individual predicates ------------------------------------------------
def reached(obs):
    return obs['derived']['eefToCube'] <= REACH_DIST


def grasped(obs):
    return bool(obs['innerSense']['gripper']['isHolding'])


def transported(obs):
    d = obs['derived']
    return (grasped(obs) and d['cubeToPadXY'] <= TRANSPORT_XY
            and d['cubeHeightAboveTable'] >= TRANSPORT_MIN_LIFT)


def cube_speed(obs):
    return math.sqrt(sum(v * v for v in obs['vision']['cube']['vel']))


def on_pad(obs):
    d = obs['derived']
    return d['cubeToPadXY'] <= EPS_TASK and d['cubeHeightAboveTable'] > 0.0


def succeeded(obs):
    """Episode success: the cube is on the target zone and no longer held."""
    return on_pad(obs) and not grasped(obs)


class GoalTracker:
    """Advances through STEPS, firing each transition exactly once.

    `release` needs the cube to be *settled*, not merely touching the pad: a bouncing cube clips the
    pad on its first frame and would otherwise register success immediately.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.index = 0
        self._still = 0
        self.transitions = []

    @property
    def current(self):
        return STEPS[self.index] if self.index < len(STEPS) else 'done'

    def _released(self, obs):
        if not grasped(obs) and on_pad(obs) and cube_speed(obs) < SETTLE_SPEED:
            self._still += 1
        else:
            self._still = 0
        return self._still >= SETTLE_STEPS

    def update(self, obs):
        """Feed one observation. Returns the step name if a transition fired, else None."""
        if self.index >= len(STEPS):
            return None
        step = STEPS[self.index]
        met = {'reach': reached, 'grasp': grasped,
               'transport': transported, 'release': self._released}[step](obs)
        if not met:
            return None
        self.index += 1
        self.transitions.append((step, obs['t']))
        return step
