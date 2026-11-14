"""
Floor soccer for the robots: guard the goal, and clear the balloon when it
comes within their reach.

Used by chase.py --game soccer. This file only works out WHERE each robot should
go; chase.py does the driving and all the safety stops.

How the robots play (10 Nov rule: robots may cross the centre line and go up to
halfway into the people's half, never the half by the people's goal; people
still stay on their own side):
  - Strips: the arena is cut in two the long way. Cozmo has the back strip (the
    back post's half of the goal), MiP the front strip. Each strip runs from the
    robots' goal into the people's half, up to the reach line. A robot never
    leaves its own strip, so the two can't bump into each other. A robot playing
    alone (chase.py --only) covers the whole width and the whole goal.
  - Guarding: each robot slides along just in front of the goal line to stay
    between the balloon and its half of the goal.
  - Attacking (10 Nov): when the balloon is within reach and in a robot's strip,
    that robot gets behind it and pushes it at the people's goal. Both robots
    attack this way, each in its own strip, so either can score.
  - Robots stay inside the pink play area and behind their reach line.
"""

import math

import room as roomlib

REACH = 0.50           # robots may go this fraction of the way into the people's half (0 = centre line)
CENTRE_GAP = 0.10      # m: robots keep their middle this far (plus half their length) behind the reach line
EDGE_GAP = 0.20        # m: and this far (plus half their length) from the play area's edges.
                       # Matches chase.py's WALL_MARGIN, so a target is never in the zone chase.py
                       # pulls the robot back out of (they fought, and MiP ran over the border; 10 Nov)
LANE_GAP = 0.05        # m: and this far (plus half their size) from the line between the two lanes
CLEAR_MARGIN = 0.08    # m: balloon must be this far onto the robots' side before a robot goes out (was 0.10)
GET_BEHIND = 0.12      # m: a clearing robot lines up this far behind the balloon (plus radii; was 0.15)
PUSH_THROUGH = 0.36    # m: then drives this far past the balloon's middle to push it (was 0.30)
BALLOON_RADIUS = 0.154 # m: half the measured balloon (30.8 cm, 10 Nov); chase.py passes the saved size
LANES = {"cozmo": "back", "mip": "front"}   # back = top of the camera picture (small y)
STRIP_HOLD = 0.05      # m: an attacking robot keeps going till the balloon is this far into the other strip


def unit(dx, dy):
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-9 else (0.0, 0.0)


class Guard:
    def __init__(self, robots_defend="right", goal_width=roomlib.GOAL_WIDTH, players=None):
        self.robots_defend = robots_defend
        self.goal_width = goal_width
        self.clearing = set()        # robots out attacking the balloon
        # A robot playing alone (e.g. chase.py --only mip) gets the whole side and goal.
        self.solo = players[0] if players and len(players) == 1 else None
        # 13 Nov: a robot whose strip doesn't have the balloon stops where it is instead of
        # driving back to its pink square (it went back and forth a lot). At a serve (after a
        # goal or "Out!", until "Play!") the robots still go back to their squares.
        self.serving = True              # set by chase.py from the scoreboard's moments

    # -------------------------------------------------------------- geometry
    def sign(self):
        """+1 if the robots' goal is at the right end (x = width), -1 if at the left."""
        return 1 if self.robots_defend == "right" else -1

    def half_size(self, robot):
        return robot.get("length", 0.10) / 2

    def lane(self, name, depth):
        """(y_low, y_high) of a robot's strip. Playing alone, the whole width."""
        if name == self.solo:
            return 0.0, depth
        return (0.0, depth / 2) if LANES.get(name, "back") == "back" else (depth / 2, depth)

    def reach_line(self, width):
        """x of the furthest line the robots may go to: REACH of the way into the people's half."""
        return width / 2 - self.sign() * REACH * width / 2

    def keep_inside(self, name, x, y, robot, width, depth):
        """Clamp a target to the robot's own lane on the robots' half, allowing for its size."""
        r = self.half_size(robot)
        edge, centre = EDGE_GAP + r, CENTRE_GAP + r
        line = self.reach_line(width)
        if self.robots_defend == "right":
            x = min(max(x, line + centre), width - edge)
        else:
            x = min(max(x, edge), line - centre)
        y_lo, y_hi = self.lane(name, depth)
        side = max(robot.get("length", 0.10), robot.get("width", 0.08)) / 2   # it may be facing any way
        y_lo = y_lo + (EDGE_GAP + r if y_lo == 0 else LANE_GAP + side)
        y_hi = y_hi - (EDGE_GAP + r if y_hi == depth else LANE_GAP + side)
        return x, min(max(y, y_lo), y_hi)

    def guard_line_x(self, width):
        """How far out from the goal line a guarding robot stands: its own soccer spot."""
        x = roomlib.goals(width, 1, self.goal_width)[self.robots_defend][0]
        return x - self.sign() * (roomlib.EDGE + roomlib.SOCCER_SPOT / 2)   # the taped square; keep_inside pulls it in

    def goal_part(self, name, depth):
        """The part of the goal mouth (y range) a robot guards: the half in its lane."""
        _, y0, y1 = roomlib.goals(1, depth, self.goal_width)[self.robots_defend]
        if name == self.solo:
            return y0, y1
        mid = (y0 + y1) / 2
        return (y0, mid) if LANES.get(name, "back") == "back" else (mid, y1)

    # ----------------------------------------------------------------- roles
    def on_robots_side(self, bx, width, margin):
        """Is the balloon within the robots' reach (past the reach line by `margin`)?"""
        line = self.reach_line(width)
        return (bx > line + margin) if self.robots_defend == "right" else (bx < line - margin)

    def should_attack(self, name, balloon, width, depth):
        """Attack when the balloon is within reach and its middle is in this robot's strip."""
        going = name in self.clearing
        y_lo, y_hi = self.lane(name, depth)
        hold = STRIP_HOLD if going else 0.0
        in_strip = y_lo - hold <= balloon["y"] <= y_hi + hold
        margin = -CLEAR_MARGIN if going else CLEAR_MARGIN   # keep going till it's well away
        return in_strip and self.on_robots_side(balloon["x"], width, margin)

    # --------------------------------------------------------------- targets
    def targets(self, balloon, robots, width, depth, balloon_radius=BALLOON_RADIUS):
        """{robot name: (x, y, role)} for every robot that's seen.
        balloon: {"x", "y"} floor spot. robots: {name: {"x", "y", "heading", "length", ...}}."""
        robots = {n: r for n, r in robots.items() if r.get("seen", True)}
        bx, by = balloon["x"], balloon["y"]
        self.clearing = {n for n in robots if self.should_attack(n, balloon, width, depth)}

        out = {}
        gx = roomlib.goals(width, depth, self.goal_width)[self.robots_defend][0]
        for name, robot in robots.items():
            if name in self.clearing:
                tx, ty, role = self.clear_target(robot, bx, by, width, depth, balloon_radius)
            elif not self.serving and self.solo is None and self.on_robots_side(bx, width, 0):
                tx, ty, role = robot["x"], robot["y"], "wait"   # in the other's strip: stay put
            else:
                y_lo, y_hi = self.goal_part(name, depth)
                aim = (y_lo + y_hi) / 2                   # middle of its half of the goal
                lx = self.guard_line_x(width)
                # stand where the line from the balloon to its half of the goal crosses the guard line
                t = (lx - bx) / (gx - bx) if abs(gx - bx) > 1e-6 else 2
                ty = by + t * (aim - by) if 0 <= t <= 1 else aim
                tx, role = lx, "guard"
            out[name] = (*self.keep_inside(name, tx, ty, robot, width, depth), role)
        return out

    def push_direction(self, bx, by, width, depth):
        """Unit vector from the balloon toward the middle of the people's goal."""
        ox = 0.0 if self.robots_defend == "right" else width   # the people's goal is at the other end
        return unit(ox - bx, depth / 2 - by)

    def clear_target(self, robot, bx, by, width, depth, balloon_radius):
        ux, uy = self.push_direction(bx, by, width, depth)       # direction to push the balloon
        reach = balloon_radius + self.half_size(robot)
        rx, ry = robot["x"] - bx, robot["y"] - by
        along = rx * ux + ry * uy                                # < 0 means the robot is behind it
        side = abs(-rx * uy + ry * ux)                           # how far off the push line
        if along < -reach * 0.5 and side < reach * 0.8:
            return bx + ux * PUSH_THROUGH, by + uy * PUSH_THROUGH, "push"
        return bx - ux * (reach + GET_BEHIND), by - uy * (reach + GET_BEHIND), "get behind"
