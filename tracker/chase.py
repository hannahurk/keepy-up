"""
Chase the balloon: listens to tracker.py and drives the robots.

    python chase.py --dry-run            # no robots, just print what they'd do
    python chase.py                      # Cozmo and MiP
    python chase.py --only cozmo         # just one robot
    python chase.py --game soccer --dry-run   # floor soccer: guard the goal (see guard.py)

Cozmo plays the left half of the room and MiP the right half. Whichever
robot's half the balloon is over moves to the floor spot under it. The
other robot waits where it is.

In floor soccer (--game soccer) the robots guard their goal instead. Their half
is cut in two the long way: Cozmo has the back strip and back half of the goal,
MiP the front. When the balloon is within reach (up to halfway into the people's
half) and in a robot's strip, that robot pushes it at the people's goal. Each
stays in its own strip. See guard.py.

Robots always stay inside the pink play area (the 4 tape crosses): targets are
kept inside it, allowing for each robot's size, and a robot found outside it
drives straight back in before doing anything else.

Safety: every robot stops at once if
  - it, or the balloon, hasn't been seen for half a second
  - it's hidden from the camera under the balloon (it waits there)
  - no message has come from the tracker for half a second
  - you press Ctrl+C
Children aren't tracked yet, so keep a grown-up watching and keep speeds low.
"""

import argparse
import asyncio
import json
import math
import os
import signal
import time

import robots as robotlib
from guard import Guard
from soccer import MOMENT_PORT
import room as roomlib
from room import play_on_mac, wrap_degrees

LOST_AFTER = 0.5     # seconds
ARRIVED = 0.20       # metres: close enough to the balloon's spot (keepy uppy chasing)
ARRIVED_GUARD = 0.06 # metres: close enough to a soccer guard / push target
ARRIVED_BACK = 0.03  # metres: close enough when driving back inside the play area
MIN_FORWARD = 0.03   # m/s: slowest forward speed asked for (MiP ignores anything under 0.02)
WALL_MARGIN = 0.20   # metres: stay this far inside the taped square
SWITCH_MARGIN = 0.10 # metres: balloon must cross this far past the middle to hand over
TURN_ONLY = 35       # degrees: turn on the spot before driving if more off than this
SLOW_DOWN = 0.50     # metres: start easing off this far from the target (was 0.6)
KEEP_APART = 0.35   # metres (middle to middle): closer than this, the robot that isn't
                    # going for the balloon won't drive toward the other one
KEEP_APART_HARD = 0.20  # metres: closer than this, neither drives toward the other
NEAR_EDGE = 0.30     # metres: closer than this to the border, drive slowly
EDGE_SPEED = 0.30    # m/s: top speed near the border (less sliding past the tape)
# Missed push (12 Nov): a push that lasted MISS_MIN_PUSH s or more and left the balloon
# within MISS_MOVE of where it was plays the "miss" sound, at most every MISS_EVERY s.
MISS_MIN_PUSH = 1.0  # seconds
MISS_MOVE = 0.05     # metres
MISS_EVERY = 5.0     # seconds
FACE_TOLERANCE = 15  # degrees: at its square, a guarding robot turns until it faces the people's goal this closely


class Chaser:
    def __init__(self, drivers, max_speed, max_turn, game="keepy-up", robots_defend="right"):
        self.drivers = drivers           # {"cozmo": driver, "mip": driver}
        # one robot playing alone covers the whole robots' side; two split it into lanes
        self.guard = Guard(robots_defend, players=list(drivers)) if game == "soccer" else None
        self.max_speed = max_speed
        self.max_turn = max_turn
        self.active = None               # which robot is chasing
        self.last_message = 0
        self.clockwise = False           # set from each tracker message
        self.status = {}                 # last status logged for each robot
        self.job = {}                    # each robot's job on the last message (push, guard...)
        self.push_from = {}              # robot: (when, balloon x, y) as its push started
        self.last_miss = float("-inf")
        self.last_moment = {}            # when the robots last reacted to each kind of game moment
        self.paused = False              # set by "pause" / "resume" from the launcher

    def log_status(self, name, status):
        """Print a robot's status when it changes, so a game log shows why a robot
        did or didn't move (e.g. never seen by the camera, waiting to keep apart)."""
        if self.status.get(name) != status:
            self.status[name] = status
            print(f"{time.strftime('%H:%M:%S')} [{name}] {status}", flush=True)

    def pick_active(self, balloon_x, width):
        mid = width / 2
        if self.active == "cozmo" and balloon_x < mid + SWITCH_MARGIN:
            return "cozmo"
        if self.active == "mip" and balloon_x > mid - SWITCH_MARGIN:
            return "mip"
        return "cozmo" if balloon_x < mid else "mip"

    @staticmethod
    def edge_gap(robot):
        """How far a robot's middle must stay from the play area's edges."""
        return max(WALL_MARGIN, robot.get("length", 0.1) / 2 + 0.05)

    def target_for(self, name, bx, by, width, depth, robot=None):
        """The balloon's floor spot, kept inside this robot's half of the play area."""
        m = self.edge_gap(robot or {})
        mid = width / 2
        lo, hi = (m, mid - WALL_MARGIN / 2) if name == "cozmo" else (mid + WALL_MARGIN / 2, width - m)
        return min(max(bx, lo), hi), min(max(by, m), depth - m)

    @staticmethod
    def near_edge(robot, width, depth):
        return min(robot["x"], width - robot["x"], robot["y"], depth - robot["y"]) < NEAR_EDGE

    def back_inside(self, robot, width, depth):
        """If the robot has strayed too near or past the play area's edge, the
        nearest safe point inside to drive back to. Otherwise None."""
        m = self.edge_gap(robot)
        x, y = robot["x"], robot["y"]
        safe = (min(max(x, m), width - m), min(max(y, m), depth - m))
        if math.hypot(x - safe[0], y - safe[1]) > 0.04:
            return safe
        return None

    def steer(self, robot, target, arrived=ARRIVED):
        """Forward speed and turn rate to head for the target. `arrived`: how close
        counts as there. It must be smaller than how far off the robot can be, or it
        never moves (that's what kept MiP stuck outside its zone)."""
        dx, dy = target[0] - robot["x"], target[1] - robot["y"]
        dist = math.hypot(dx, dy)
        if dist < arrived:
            return 0.0, 0.0, dist
        error = wrap_degrees(math.degrees(math.atan2(dy, dx)) - robot["heading"])
        turn = max(-self.max_turn, min(self.max_turn, error * 2.0))
        if self.clockwise:
            turn = -turn  # heading goes up clockwise here, but drive() turns + = anticlockwise
        if abs(error) > TURN_ONLY:
            return 0.0, turn, dist
        forward = self.max_speed * min(1.0, dist / SLOW_DOWN) * math.cos(math.radians(error))
        forward = max(forward, min(MIN_FORWARD, self.max_speed))   # creep, don't stall just short
        return forward, turn, dist

    async def handle(self, msg):
        self.last_message = time.monotonic()
        if self.paused:
            self.push_from = {}              # a pause isn't a miss
            for name in self.drivers:
                self.log_status(name, "paused")
            await self.stop_all()
            return
        room, balloon = msg["room"], msg["balloon"]
        self.clockwise = room.get("clockwise", False)
        if not balloon["seen"]:
            self.push_from = {}
            self.active = None
            for name in self.drivers:
                self.log_status(name, "stopped: balloon not seen")
            await self.stop_all()
            return
        self.active = self.pick_active(balloon["x"], room["width"])
        soccer = None
        if self.guard:
            radius = (room.get("balloon_size") or 0.36) / 2   # sent by the tracker (measured with F)
            soccer = self.guard.targets(balloon, msg["robots"], room["width"], room["depth"], radius)

        for name, driver in self.drivers.items():
            robot = msg["robots"].get(name)
            if getattr(driver, "lost", False):          # MiP's Bluetooth is reconnecting by itself
                self.log_status(name, "stopped: Bluetooth reconnecting")
                continue
            if not robot or not robot["seen"] or robot.get("hidden"):
                self.log_status(name, "stopped: hidden under the balloon" if robot and robot.get("hidden")
                                else "stopped: camera can't see it")
                await driver.stop()   # lost, or hidden under the balloon: don't drive blind
                continue
            back = self.back_inside(robot, room["width"], room["depth"])
            if back is not None:  # outside the pink area: come back in first
                self.log_status(name, "driving back inside the safety zone")
                forward, turn, _ = self.steer(robot, back, ARRIVED_BACK)
                await (driver.stop() if forward == 0 and turn == 0 else driver.drive(forward, turn))
                continue
            if soccer is not None:
                if name not in soccer:
                    self.log_status(name, "stopped: no soccer job")
                    await driver.stop()
                    continue
                target = soccer[name][:2]
                arrived = ARRIVED_GUARD
                job = soccer[name][2]
            elif name != self.active:
                self.log_status(name, "waiting: balloon is in the other robot's half")
                await driver.stop()
                continue
            else:
                target = self.target_for(name, balloon["x"], balloon["y"], room["width"], room["depth"], robot)
                arrived = ARRIVED
                job = "chase"
            forward, turn, dist = self.steer(robot, target, arrived)
            if job == "guard" and forward == 0 and turn == 0:
                turn = self.face_people_goal(robot, room["width"], room["depth"])   # 13 Nov
            if self.must_wait(name, robot, target, msg["robots"], soccer, balloon):
                forward = 0.0          # keep apart: may turn on the spot, but not drive closer
                self.log_status(name, f"{job}: waiting, too close to the other robot")
            else:
                self.log_status(name, job + (" (there)" if forward == 0 and turn == 0 else ""))
            if job in ("push", "chase") and self.job.get(name) != job and hasattr(driver, "going_for_it"):
                driver.going_for_it()          # Cozmo: a quiet "vroom" as he sets off after it
            if job == "push" and self.job.get(name) != "push":
                self.push_from[name] = (time.monotonic(), balloon["x"], balloon["y"])
            elif job != "push" and name in self.push_from:
                self.check_miss(name, balloon)
            self.job[name] = job
            if self.near_edge(robot, room["width"], room["depth"]):
                forward = min(forward, EDGE_SPEED)
            if forward == 0 and turn == 0:
                await driver.stop()
            else:
                await driver.drive(forward, turn)

    def face_people_goal(self, robot, width, depth):
        """Turn rate to face the middle of the people's goal (0 once facing it closely enough)."""
        side = "left" if self.guard.robots_defend == "right" else "right"
        gx, y0, y1 = roomlib.goals(width, depth)[side]
        error = wrap_degrees(math.degrees(math.atan2((y0 + y1) / 2 - robot["y"], gx - robot["x"])) - robot["heading"])
        if abs(error) <= FACE_TOLERANCE:
            return 0.0
        turn = max(-self.max_turn, min(self.max_turn, error * 2.0))
        return -turn if self.clockwise else turn

    def check_miss(self, name, balloon):
        """A push just ended: if the balloon hardly moved, the robot missed it."""
        start, x, y = self.push_from.pop(name)
        now = time.monotonic()
        if (now - start >= MISS_MIN_PUSH and math.hypot(balloon["x"] - x, balloon["y"] - y) < MISS_MOVE
                and now - self.last_miss >= MISS_EVERY):
            self.last_miss = now
            print(f"{time.strftime('%H:%M:%S')} [{name}] missed the balloon", flush=True)
            play_on_mac("miss")

    def priority(self, name, robots, soccer, balloon):
        """Who gets right of way when the robots are close: the one going for the
        balloon, then the one nearer the balloon. A robot that's reconnecting (frozen)
        has none, so the other doesn't wait behind it (12 Nov)."""
        if getattr(self.drivers.get(name), "lost", False):
            return (False, -math.inf)
        r = robots[name]
        going = (soccer[name][2] in ("push", "get behind")) if soccer and name in soccer else (name == self.active)
        near = -math.hypot(r["x"] - balloon["x"], r["y"] - balloon["y"])
        return (going, near)

    def must_wait(self, name, robot, target, robots, soccer, balloon):
        """Keep apart: True if this robot should not drive forward right now, because
        it would head toward the other robot while they're close."""
        for other_name, other in robots.items():
            if other_name == name or other.get("x") is None or not (other.get("seen") or other.get("hidden")):
                continue
            ox, oy = other["x"] - robot["x"], other["y"] - robot["y"]
            gap = math.hypot(ox, oy)
            if gap >= KEEP_APART:
                continue
            tx, ty = target[0] - robot["x"], target[1] - robot["y"]
            if tx * ox + ty * oy <= 0:
                continue                  # heading away from the other robot: fine
            if gap < KEEP_APART_HARD:
                return True
            if other_name in self.drivers and \
                    self.priority(name, robots, soccer, balloon) > self.priority(other_name, robots, soccer, balloon):
                continue                  # this one has right of way
            return True
        return False

    async def react(self, moment):
        """A game moment from soccer.py (goal, out, play...): each robot says something.
        The same moment again within 2 s is skipped ("Out!" can repeat quickly)."""
        if self.guard and moment == "play":
            self.guard.serving = False         # play on: a robot waits where it is
        elif self.guard and (moment in ("out", "stuck", "new_game") or moment.endswith(("_goal", "_win"))):
            self.guard.serving = True          # a serve: robots go back to their squares
        if moment in ("pause", "resume"):      # from the launcher's p key
            self.paused = moment == "pause"
            print(f"{time.strftime('%H:%M:%S')} {'paused' if self.paused else 'resumed'}", flush=True)
            if self.paused:
                await self.stop_all()
            return
        now = time.monotonic()
        if now - self.last_moment.get(moment, -9) < 2.0:
            return
        self.last_moment[moment] = now
        print(f"{time.strftime('%H:%M:%S')} moment: {moment}", flush=True)
        for name, driver in self.drivers.items():
            try:
                await driver.play(moment)
            except Exception as e:          # a sound must never stop the game
                print(f"[{name}] couldn't play '{moment}': {e.__class__.__name__}")

    async def stop_all(self):
        for d in self.drivers.values():
            await d.stop()

    async def watchdog(self):
        """Stops everything if the tracker goes quiet."""
        while True:
            await asyncio.sleep(0.1)
            if self.last_message and time.monotonic() - self.last_message > LOST_AFTER:
                await self.stop_all()


async def main():
    p = argparse.ArgumentParser(description="Drive the robots toward the balloon.")
    p.add_argument("--url", default="ws://localhost:8765", help="Where tracker.py is streaming")
    p.add_argument("--dry-run", action="store_true", help="Don't connect to robots, just print")
    p.add_argument("--only", choices=["cozmo", "mip"], help="Use just one robot")
    p.add_argument("--max-speed", type=float, default=0.10, help="Top speed in m/s (Cozmo's max is about 0.2)")
    p.add_argument("--max-turn", type=float, default=60, help="Top turn rate in degrees per second")
    p.add_argument("--game", choices=["keepy-up", "soccer"], default="keepy-up")
    p.add_argument("--start-paused", action="store_true",
                   help="Wait for 'resume' (from the launcher) before driving, e.g. while Cozmo is moved off his charger")
    p.add_argument("--robots-defend", choices=["left", "right"], default="right",
                   help="Soccer: which end's goal the robots guard")
    args = p.parse_args()

    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidHandshake

    # Ctrl+C, or the window being closed (TERM/HUP), cancels this task so the
    # 'finally' below always stops the robots' wheels before exiting.
    me = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        asyncio.get_running_loop().add_signal_handler(sig, me.cancel)

    # Safety: if whatever started this program goes away (e.g. the launcher crashed),
    # stop the robots instead of playing on with nobody watching the screen.
    parent = os.getppid()

    async def watch_parent():
        while True:
            await asyncio.sleep(0.5)
            if os.getppid() != parent:
                print("The program that started me has closed: stopping the robots.", flush=True)
                me.cancel()
                return
    asyncio.ensure_future(watch_parent())

    names = [args.only] if args.only else ["cozmo", "mip"]
    kinds = {"cozmo": robotlib.Cozmo, "mip": robotlib.MiP}
    drivers = {n: (robotlib.DryRun(n) if args.dry_run else kinds[n](n)) for n in names}
    for d in drivers.values():
        await d.connect()

    chaser = Chaser(drivers, args.max_speed, args.max_turn, args.game, args.robots_defend)
    chaser.paused = args.start_paused
    dog = asyncio.create_task(chaser.watchdog())
    if args.game == "soccer":    # game moments from soccer.py, so the robots can react with sounds
        class Moments(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                asyncio.ensure_future(chaser.react(data.decode(errors="ignore").strip()))
        try:
            await asyncio.get_running_loop().create_datagram_endpoint(
                Moments, local_addr=("127.0.0.1", MOMENT_PORT))
        except OSError:
            print("Can't listen for game moments (port in use): playing without robot sounds.")
    try:
        while True:
            try:
                async with connect(args.url) as ws:
                    print(f"Listening to {args.url}. Ctrl+C to stop.")
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "positions":
                            await chaser.handle(msg)
            except (OSError, ConnectionClosed, InvalidHandshake) as e:
                await chaser.stop_all()
                print(f"Can't reach the tracker ({e.__class__.__name__}). Is tracker.py running? Retrying...")
                await asyncio.sleep(2)
    finally:
        dog.cancel()
        for d in drivers.values():
            await d.stop()
            await d.close()
        print("Robots stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
