"""SIM-06: the pick-and-place goal step list, and the episode success test.

cap4 4.5 defines the task as four goal steps -- reach, grasp, transport, release -- tracked by a
planner-less TROCA-style step mechanism: the step advances when its predicate is met, and GoalMO is
re-emitted only on a real transition.

Every predicate here is a **pure function of one observation dict** (see observations.py). Nothing
in this file touches the simulator, so the whole goal layer can be replayed and tested offline
against a recorded trajectory -- which is exactly how its acceptance test runs.

Episode success is not a predicate: it is the tracker reaching `done`, under the strict test S2
(BAS-01) that `GoalTracker` documents. S2 needs the history of the carry -- was the cube let go
over the pad, after being transported? -- which no single observation holds.

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
SUCCESS_TEST = 'S2'      # BAS-01; a new rule gets a new name, so runs under different rules never compare

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


def placed(obs):
    """The cube lies on the target zone and is not held. One observation, so a cube pushed or knocked
    onto the pad is placed too: this is not the success test (`GoalTracker.success` is)."""
    return on_pad(obs) and not grasped(obs)


class GoalTracker:
    """Advances through STEPS, firing each transition exactly once; `success` once all four fired.

    `release` is the strict success test S2 (BAS-01). It fires when, in this order:
      1. since the cube was last grasped, it was transported -- held over the pad and lifted;
      2. the gripper let go of it while it was still over the pad (`TRANSPORT_XY`; no lift needed,
         so lowering the cube onto the pad before opening counts);
      3. from then on, without being grasped again and without leaving the zone (`EPS_TASK`), the
         cube stayed below SETTLE_SPEED for SETTLE_STEPS consecutive observations.
    A cube pushed or knocked onto the pad, dropped beside it and nudged in, bouncing off it, or still
    falling past it is not a success. The rule S2 replaces -- `placed` in one observation -- counted
    all four, and ended the episode on the first frame a falling cube clipped the pad.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.index = 0
        self.transitions = []
        self._prev = None
        self._carried = False       # condition 1, for the carry in progress
        self._placing = False       # 1 and 2 held at the let-go, and 3 has not failed since
        self._still = 0

    @property
    def current(self):
        return STEPS[self.index] if self.index < len(STEPS) else 'done'

    @property
    def success(self):
        return self.index >= len(STEPS)

    def _track(self, obs):
        """Follow the carry and the placing it may end in, whatever step is current."""
        held = grasped(obs)
        was_held = self._prev is not None and grasped(self._prev)
        if held:
            self._carried = (self._carried and was_held) or transported(obs)
            self._placing = False
        elif was_held:                                   # let go on this observation
            self._placing = self._carried and self._prev['derived']['cubeToPadXY'] <= TRANSPORT_XY
        if self._placing and not on_pad(obs):
            self._placing = False                        # bounced, rolled or fell off the zone
        self._still = self._still + 1 if self._placing and cube_speed(obs) < SETTLE_SPEED else 0
        self._prev = obs

    def _released(self, obs):
        return self._placing and self._still >= SETTLE_STEPS

    def update(self, obs):
        """Feed one observation. Returns the step name if a transition fired, else None."""
        self._track(obs)
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
