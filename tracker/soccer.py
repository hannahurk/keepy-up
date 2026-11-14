"""
Floor soccer referee: listens to tracker.py, spots goals and keeps score.

    python soccer.py                         # robots defend the right goal, people the left
    python soccer.py --robots-defend left
    python soccer.py --first-serve robots    # this game starts with the robots serving

It plays like air hockey: people roll the balloon along the floor and try to
get it into the robots' goal while defending their own, and the robots do the
same. People stay behind their own goal line, outside the arena, and reach in to hit or
tap the balloon with their hands and arms (13 Nov); the robots may go up to halfway into the people's
half (never the half by the people's goal). Goals are worked out from the 4 floor crosses (see
tape_guide.py --game soccer), so there's nothing extra to click.

How a game goes:
  1. Serve: nobody kicks. People hit or tap the balloon with their hands and arms from
     behind their goal line, and the robots push it with their bodies. A new game always starts with the people
     serving from their side, toward the robots. After a goal, the team that
     scored gets the balloon and serves from their own side, toward the other
     team. When the balloon has sat on the floor on that side for a moment, the
     scoreboard says "Play!". (For the robots' serve, a person puts the balloon
     down on the robots' side.)
  2. A goal counts as soon as the balloon, rolling on the floor from inside the arena,
     touches the pink goal line between the two pink posts (decided 12-13 Nov). Coming
     back in through the goal, or a serve put down on the line, doesn't count. Rolling
     out of the camera's view through the goal mouth also counts.
  3. After a goal, or if the balloon leaves the play area anywhere else, play
     stops until the next serve. After the balloon goes out, the team whose
     side it went out on serves.
  4. Stuck: if the balloon doesn't move for 10 seconds (somewhere nobody can reach),
     it's served again by the team whose side it's on.
  5. The first goal wins the game. Then n in the game window (or R here) starts a new game.

Keys in the scoreboard window:
  SPACE pause / resume    R new game (reset the score)    K serve again    Q quit

This only referees and keeps score; chase.py --game soccer drives the robots.
Nothing is saved.
"""

import argparse
import socket
import json
import math
import threading
import time

import cv2
import numpy as np

import room as roomlib

WINDOW = "Floor soccer"
ON_FLOOR = 0.60       # m: balloon centre below this counts as rolling on the floor
KICKOFF_HOLD = 1.0    # s: balloon must sit on the floor inside the play area this long
GOAL_SHOW = 3.0       # s: how long "GOAL!" stays up
LOST_NEAR_GOAL = 0.35  # m: lost from view this close to a goal mouth counts as a goal
LOST_AFTER = 0.5      # s
WIN_SCORE = 1         # first team to this many goals wins (13 Nov: the first goal wins; was 5)
# Near miss (12 Nov): the balloon's middle comes within NEAR_GOAL of a goal line, between
# the posts (give or take NEAR_POSTS), then leaves without a goal: "So close!" sound.
NEAR_GOAL = 0.30      # m
NEAR_POSTS = 0.10     # m
NEAR_EVERY = 5.0      # s: at most one near-miss sound this often
STUCK_AFTER = 10.0    # s: a balloon that hasn't moved this long in play is served again (13 Nov:
STUCK_MOVE = 0.03     # m   a strip between the kids' reach and the robots' limit, and the robots'
                      #     own corners, are places nobody can reach)
OUT_HOLD = 0.5        # s: the balloon must stay outside the arena this long before "Out!" (12 Nov:
                      # on the edge tape it flickered in and out: 6 calls in 40 s)
COMMAND_PORT = 8767   # the launcher (play_soccer.py) sends "pause" / "resume" / "new_game" here
MOMENT_PORT = 8766    # game moments (goal, out, play...) go to chase.py here, so the robots
                      # can react. Local to this Mac only; nothing is sent if no robots listen.
KICKOFF_ANY = "Put the balloon down on either side to serve"


class Referee:
    """Game rules. Feed it tracker messages; it keeps the score and the state."""

    def __init__(self, robots_defend="right", goal_width=roomlib.GOAL_WIDTH, win_score=WIN_SCORE,
                 first_serve="people"):
        self.win_score = win_score
        self.first_serve = first_serve   # who serves at the start of a game (normally the people)
        self.winner = None
        self.robots_defend = robots_defend
        self.goal_width = goal_width
        self.score = {"people": 0, "robots": 0}
        self.state = "kickoff"       # kickoff (serve) -> play -> goal / out -> kickoff
        self.paused = False
        self.kicks_off = first_serve # "people", "robots" or None (either side). New games: people first
        self.message = self.kickoff_message()
        self.on_spot_since = None
        self.until = 0
        self.last_seen = None        # (x, y, when) while in play
        self.events = []             # printed by the caller
        self.moments = []            # "play", "out", "robots_goal"... sent to the robots by the caller
        self.near = None             # balloon near a goal: "in", "out", or None until play starts
        self.new_game_hint = "Press R for a new game"
        self.countdown = None        # "Get ready...", "1", "2", "3", "START!" (from the game window)
        self.countdown_until = 0
        self.last_near = float("-inf")
        self.out_since = None        # when the balloon was first seen outside the arena
        self.was_inside = False      # last time it was seen, the balloon was inside, clear of the goal lines
        self.still = None            # (x, y, since) where the balloon has been sitting still

    def scorer(self, side):
        """Who scores when the balloon goes into the goal at this end."""
        return "people" if side == self.robots_defend else "robots"

    def half(self, team, width):
        """x range of a team's own half: the half with the goal they defend."""
        defends = self.robots_defend if team == "robots" else ("left" if self.robots_defend == "right" else "right")
        return (0, width / 2) if defends == "left" else (width / 2, width)

    def kickoff_message(self):
        if self.kicks_off == "people":
            return "People's balloon: put the balloon down on your side"
        if self.kicks_off == "robots":
            return "Robot's balloon: put the balloon down on the robots' side"
        return KICKOFF_ANY

    def new_game(self):
        self.score = {"people": 0, "robots": 0}
        self.state, self.on_spot_since, self.kicks_off, self.winner = "kickoff", None, self.first_serve, None

    def say(self, msg):
        self.message = msg
        self.events.append(msg)

    def near_miss(self, near, now):
        """Track the balloon near a goal; when it came close and leaves without going in,
        it's a near miss. A serve that starts near a goal doesn't count until it has left."""
        if self.near is None:
            self.near = "start" if near else "out"
        elif near and self.near == "out":
            self.near = "in"
        elif not near:
            if self.near == "in" and now - self.last_near >= NEAR_EVERY:
                self.last_near = now
                self.moments.append("near_miss")
            self.near = "out"

    def goal(self, side, now):
        self.near = None             # it went in: not a near miss
        self.was_inside = False
        team = self.scorer(side)
        self.score[team] += 1
        self.state, self.until = "goal", now + GOAL_SHOW
        self.kicks_off = team        # the team that scored gets the balloon
        if self.score[team] < self.win_score:
            self.moments.append(f"{team}_goal")
        self.say(f"GOAL for the {team}!  People {self.score['people']} - {self.score['robots']} Robots")
        if self.score[team] >= self.win_score:
            self.moments.append(f"{team}_win")
            self.state = "won"
            self.winner = team
            self.say(f"The {team} win {self.score[team]} - {min(self.score.values())}!  {self.new_game_hint}")

    def update(self, msg, now):
        room, b = msg["room"], msg["balloon"]
        width, depth = room["width"], room["depth"]
        goals = roomlib.goals(width, depth, self.goal_width)
        if self.paused:
            return

        if self.state == "won":
            return                   # game over until R starts a new one
        if self.state in ("goal", "out") and now >= self.until:
            self.state, self.on_spot_since = "kickoff", None
            self.say(self.kickoff_message())

        if self.state == "kickoff":
            # The balloon has to be down on the floor, on the serving team's half
            # (or anywhere inside the area if either team may serve).
            x0, x1 = self.half(self.kicks_off, width) if self.kicks_off else (0, width)
            on_spot = (b["seen"] and b["height"] is not None and b["height"] < ON_FLOOR
                       and x0 <= b["x"] <= x1 and 0 <= b["y"] <= depth)
            if not on_spot:
                self.on_spot_since = None
            elif self.on_spot_since is None:
                self.on_spot_since = now
            elif now - self.on_spot_since >= KICKOFF_HOLD:
                self.state, self.last_seen, self.near, self.was_inside, self.still = "play", None, None, False, None
                self.say("Play!")
                self.moments.append("play")
            return

        if self.state != "play":
            return

        if b["seen"]:
            x, y = b["x"], b["y"]
            self.last_seen = (x, y, now)
            low = b["height"] is not None and b["height"] < ON_FLOOR
            r = (room.get("balloon_size") or 0.31) / 2   # a goal as soon as its edge touches the line
            over_side = None
            for side, (gx, y0, y1) in goals.items():
                over = x - r <= gx if side == "left" else x + r >= gx
                if over and low and y0 <= y <= y1:
                    over_side = side
            # 13 Nov: only a balloon rolling in from inside the arena scores. One that reappears
            # at the line (carried back in through the goal) or is put down on it at a serve doesn't.
            if over_side and self.was_inside:
                self.goal(over_side, now)
                return
            self.was_inside = over_side is None and 0 <= x <= width and 0 <= y <= depth
            if self.still is None or math.hypot(x - self.still[0], y - self.still[1]) > STUCK_MOVE:
                self.still = (x, y, now)
            elif now - self.still[2] >= STUCK_AFTER:
                # Nobody can reach it: serve again from the side it's on.
                self.still, self.near, self.was_inside = None, None, False
                self.state, self.until = "out", now + 2.0
                people_half = (x < width / 2) == (self.robots_defend == "right")
                self.kicks_off = "people" if people_half else "robots"
                self.say("Stuck! " + ("People's balloon" if people_half else "Robot's balloon"))
                self.moments.append("stuck")
                return
            # leaving the zone counts once it's NEAR_POSTS further out, so a wobble doesn't
            near_zone = NEAR_GOAL + (NEAR_POSTS if self.near == "in" else 0)
            self.near_miss(any(abs(x - gx) < near_zone and y0 - NEAR_POSTS <= y <= y1 + NEAR_POSTS
                               for gx, y0, y1 in goals.values()), now)
            outside = low and not (0 <= x <= width and 0 <= y <= depth)
            if not outside:
                self.out_since = None
            elif self.out_since is None:
                self.out_since = now
            if outside and now - self.out_since >= OUT_HOLD:
                self.out_since = None
                self.near_miss(False, now)   # went out right by a goal: that was a near miss
                self.near = None
                self.state, self.until, self.was_inside = "out", now + 2.0, False
                # The team whose side the balloon went out on serves.
                side = "left" if x < width / 2 else "right"
                self.kicks_off = "robots" if side == self.robots_defend else "people"
                whose = "people's" if self.kicks_off == "people" else "robots'"
                self.say(f"Out on the {whose} side! " + ("People's balloon" if self.kicks_off == "people" else "Robot's balloon"))
                self.moments.append("out")
            return

        # Not seen: if it vanished at a goal mouth, it rolled out through the goal.
        if self.last_seen and now - self.last_seen[2] > LOST_AFTER:
            x, y, _ = self.last_seen
            for side, (gx, y0, y1) in goals.items():
                if abs(x - gx) < LOST_NEAR_GOAL and y0 - 0.1 <= y <= y1 + 0.1:
                    self.goal(side, now)
                    return
            self.last_seen = None
            self.was_inside = False          # lost for a while: it must be seen inside again to score
            self.near = None                 # and coming back into view isn't a near miss
            self.say("Lost the balloon. Keep playing, or press K to serve again")


# ------------------------------------------------------------------ scoreboard

def draw(ref, msg, connected):
    W, H = 1280, 720
    img = np.full((H, W, 3), (30, 30, 30), np.uint8)

    def centred(txt, y, scale, color, thick=2):
        (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        cv2.putText(img, txt, ((W - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    centred("Floor soccer", 70, 1.4, (200, 200, 200))
    centred(f"People  {ref.score['people']}  -  {ref.score['robots']}  Robots", 200, 2.6, (255, 255, 255), 5)
    colour = {"play": (80, 220, 80), "goal": (0, 215, 255), "out": (0, 140, 255), "won": (255, 200, 0)}.get(ref.state, (200, 200, 200))
    status = "Paused (SPACE to resume)" if ref.paused else ref.message
    scale, thick = 1.1, 2
    if ref.countdown and time.time() < ref.countdown_until:   # Get ready... 1, 2, 3, START!
        status, colour = ref.countdown, (80, 220, 80)
        if ref.countdown != "Get ready...":
            scale, thick = 2.2, 5
    else:
        ref.countdown = None
    if not connected:
        status, colour, scale, thick = "Waiting for tracker.py...", (0, 0, 255), 1.1, 2
    centred(status, 300 if scale > 2 else 290, scale, colour, thick)

    # little map of the pitch, seen from above (back at the top)
    if msg:
        width, depth = msg["room"]["width"], msg["room"]["depth"]
        s = min(1000 / width, 330 / depth)
        ox, oy = (W - width * s) / 2, 340
        P = lambda x, y: (int(ox + x * s), int(oy + y * s))
        cv2.rectangle(img, P(0, 0), P(width, depth), (255, 0, 255), 2)
        cv2.line(img, P(width / 2, 0), P(width / 2, depth), (90, 90, 90), 1)
        for side, (gx, y0, y1) in roomlib.goals(width, depth, ref.goal_width).items():
            cv2.line(img, P(gx, y0), P(gx, y1), (80, 220, 80), 6)
            team = "Robots" if side == ref.robots_defend else "People"
            tx = P(gx, 0)[0] + (8 if side == "left" else -95)
            cv2.putText(img, team, (tx, P(0, (y0 + y1) / 2)[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (80, 220, 80), 1, cv2.LINE_AA)
        for name, r in msg["robots"].items():
            if r["seen"]:
                cv2.circle(img, P(r["x"], r["y"]), 9, (255, 200, 0), -1)
                cv2.putText(img, name, (P(r["x"], r["y"])[0] + 12, P(r["x"], r["y"])[1] + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 1, cv2.LINE_AA)
        b = msg["balloon"]
        if b["seen"]:
            cv2.circle(img, P(b["x"], b["y"]), 14, (0, 230, 255), -1)
    keys = "" if ref.new_game_hint.startswith("Press n") else "    SPACE pause   R new game   K serve again   Q quit"
    first = "First goal wins" if ref.win_score == 1 else f"First to {ref.win_score} wins"
    cv2.putText(img, f"{first}{keys}", (20, H - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1, cv2.LINE_AA)
    return img


def listen(url, latest):
    """Keep the newest tracker message in latest["msg"], reconnecting as needed."""
    from websockets.sync.client import connect
    while not latest["stop"]:
        try:
            with connect(url) as ws:
                latest["connected"] = True
                for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "positions":
                        latest["msg"] = msg
                    if latest["stop"]:
                        return
        except OSError:
            pass
        except Exception:
            pass
        latest["connected"] = False
        time.sleep(1)


def main():
    p = argparse.ArgumentParser(description="Referee floor soccer and keep score.")
    p.add_argument("--url", default="ws://localhost:8765", help="Where tracker.py is streaming")
    p.add_argument("--robots-defend", choices=["left", "right"], default="right")
    p.add_argument("--goal-width", type=float, default=roomlib.GOAL_WIDTH, help="Goal mouth in metres")
    p.add_argument("--win", type=int, default=WIN_SCORE, help="Goals needed to win")
    p.add_argument("--first-serve", choices=["people", "robots"], default="people",
                   help="Who serves first in each game (normally the people)")
    p.add_argument("--no-keys", action="store_true",
                   help="Ignore the keyboard: the game window (play_soccer.py) is in charge. 12 Nov: typing"
                        " while this window was in front pressed R (new game) and space (pause)")
    args = p.parse_args()

    ref = Referee(args.robots_defend, args.goal_width, args.win, args.first_serve)
    if args.no_keys:
        ref.new_game_hint = "Press n in the game window for a new game"
    moments_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    commands_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        commands_in.bind(("127.0.0.1", COMMAND_PORT))
        commands_in.setblocking(False)
    except OSError:
        commands_in = None              # another scoreboard has it: keys still work
    latest = {"msg": None, "connected": False, "stop": False}
    threading.Thread(target=listen, args=(args.url, latest), daemon=True).start()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    print(__doc__)
    last_t = None
    try:
        while True:
            msg = latest["msg"]
            if msg and msg["t"] != last_t:
                last_t = msg["t"]
                ref.update(msg, time.time())
            for e in ref.events:
                print(time.strftime("%H:%M:%S"), e)
            ref.events.clear()
            while commands_in:               # commands from the launcher
                try:
                    command = commands_in.recv(64).decode(errors="ignore").strip()
                except (BlockingIOError, OSError):
                    break
                if command == "get_ready":    # held until the game window's 1-2-3 countdown
                    ref.paused = True
                    ref.countdown, ref.countdown_until = "Get ready...", float("inf")
                elif command.startswith("count "):
                    ref.countdown = command[6:]
                    ref.countdown_until = time.time() + 1.5 if command[6:].startswith("START") else float("inf")
                elif command in ("pause", "resume"):
                    ref.paused = command == "pause"
                    print("Paused" if ref.paused else "Resumed", flush=True)
                elif command == "new_game":
                    ref.new_game()
                    ref.say("New game. " + ref.kickoff_message())
                    ref.moments.append("new_game")
            if any(m.endswith("_win") for m in ref.moments):
                roomlib.play_on_mac("goal", "win")   # the winning goal: goal sound, then win sound
            elif any(m.endswith("_goal") for m in ref.moments):
                roomlib.play_on_mac("goal")          # every other goal
            elif "near_miss" in ref.moments or "out" in ref.moments:
                # a near miss, "Out!", or both (out right beside a post): one after the other
                roomlib.play_on_mac(*[m for m in ("near_miss", "out") if m in ref.moments])
            for m in ref.moments:            # tell the robots (chase.py), if it's listening
                try:
                    moments_out.sendto(m.encode(), ("127.0.0.1", MOMENT_PORT))
                except OSError:
                    pass
            ref.moments.clear()
            cv2.imshow(WINDOW, draw(ref, msg, latest["connected"]))
            key = cv2.waitKey(30) & 0xFF
            if args.no_keys:
                key = 255                    # a display only: keys are ignored
            if key == ord("q"):
                break
            if key == ord(" "):
                ref.paused = not ref.paused
                print("Paused" if ref.paused else "Resumed")
            if key == ord("r"):
                ref.new_game()
                ref.say("New game. " + ref.kickoff_message())
                ref.moments.append("new_game")
            if key == ord("k") and ref.state != "won":
                ref.state, ref.on_spot_since = "kickoff", None
                ref.say(ref.kickoff_message())
    finally:
        latest["stop"] = True
        cv2.destroyAllWindows()
        print(f"Final score: People {ref.score['people']} - {ref.score['robots']} Robots")


if __name__ == "__main__":
    main()
