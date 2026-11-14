"""
Keepy Up tracker: watches the room through the webcam, finds each robot (by its
AprilTag, or by the coloured tape on top) and the balloon, and streams their
positions over a WebSocket.

Robot tape: a green patch on top of each robot, plus a smaller piece at the
front: pink for Cozmo, blue for MiP. The front piece says which robot it is and
which way it faces. A tag, when the camera can read it, wins over the tape.

    python tracker.py                    # webcam 0, stream on ws://localhost:8765
    python tracker.py --tune             # adjust the balloon colour sliders
    python tracker.py --yolo ../../ball-detector/yolov8s-oiv7.pt   # find the balloon with YOLO instead
    python tracker.py --source photo.jpg --once                    # test on one picture

Run floor_setup.py first. Pictures are processed in memory and never saved
(except the one test picture with --once).

Every message (about 15 a second) looks like this. Positions are in metres,
heading in degrees (0 = toward cross 2, 90 = toward the back wall):

  {"type": "positions", "t": 1730412345.12, "room": {"width": 3, "depth": 3, "clockwise": true, "balloon_size": 0.327},
   "robots": {"cozmo": {"id": 1, "x": 0.8, "y": 1.2, "heading": 90.0, "seen": true, "age": 0.03},
              "mip":   {"id": 2, "x": null, "y": null, "heading": null, "seen": false, "age": null}},
   "balloon": {"x": 1.4, "y": 1.6, "height": 1.1, "seen": true, "age": 0.03}}

"seen" turns false when something hasn't been seen for half a second. The last
known position is kept so listeners can still show it. A robot hidden right under
the balloon keeps its last spot for up to 2 seconds with "hidden": true.

Keys in the preview window: Q = quit, F = measure the balloon (rest it on the floor first),
T = show/hide colour sliders, S = save sliders.
"""

import argparse
import asyncio
import json
import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import room as roomlib

LOST_AFTER = 0.5  # seconds without a sighting before "seen" goes false
HIDDEN_HOLD = 2.0  # seconds a robot hidden under the balloon keeps its last spot
MEASURE_FRAMES = 15  # readings averaged when measuring the balloon on the floor
WINDOW = "Keepy Up tracker"
SLIDERS = "Balloon colour"


# ---------------------------------------------------------------- tag finding

class TagFinder:
    """Finds tag36h11 AprilTags. Uses pupil-apriltags, or OpenCV if that isn't installed."""

    def __init__(self, decimate):
        try:
            from pupil_apriltags import Detector
            self.kind = "pupil-apriltags"
            self.detector = Detector(families="tag36h11", nthreads=4, quad_decimate=decimate,
                                     refine_edges=1, decode_sharpening=0.25)
        except ImportError:
            self.kind = "opencv"
            params = cv2.aruco.DetectorParameters()
            params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
            self.detector = cv2.aruco.ArucoDetector(
                cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11), params)

    def find(self, gray):
        """Returns {tag_id: 4x2 corners}. For both libraries corners[0] and
        corners[1] are the tag's top edge (the FRONT arrow on the printout)."""
        found = {}
        if self.kind == "pupil-apriltags":
            for d in self.detector.detect(gray):
                if d.decision_margin > 20:
                    found[d.tag_id] = np.array(d.corners, dtype=float)
        else:
            corners, ids, _ = self.detector.detectMarkers(gray)
            if ids is not None:
                for c, i in zip(corners, ids.ravel()):
                    found[int(i)] = c.reshape(4, 2).astype(float)
        return found


def robot_pose(room, corners, tag_height, heading_offset, tag_forward=0.0):
    """Room (x, y, heading) of a robot's middle from its tag's corners."""
    center = corners.mean(axis=0)
    front = (corners[0] + corners[1]) / 2
    back = (corners[2] + corners[3]) / 2
    c = room.to_floor(*center, tag_height)
    f = room.to_floor(*front, tag_height)
    b = room.to_floor(*back, tag_height)
    if c is None or f is None or b is None:
        return None
    heading = math.degrees(math.atan2(f[1] - b[1], f[0] - b[0])) + heading_offset
    h = math.radians(heading)
    x, y = c[0] - tag_forward * math.cos(h), c[1] - tag_forward * math.sin(h)
    return x, y, roomlib.wrap_degrees(heading)


def robot_outline(room, x, y, heading, info, pad=0.0):
    """Pixel outline of a robot's box (floor to top), grown by `pad` metres on every side."""
    corners = roomlib.robot_corners(x, y, heading, info["length"] + 2 * pad, info["width"] + 2 * pad)
    floor = [room.to_pixel(cx, cy, 0) for cx, cy in corners]
    top = [room.to_pixel(cx, cy, info["height"] + pad) for cx, cy in corners]
    return floor, top


def robots_mask(shape, room, poses, robots):
    """White wherever a robot is in the picture, so the balloon search can skip it."""
    mask = np.zeros(shape[:2], np.uint8)
    for name, (x, y, heading) in poses.items():
        info = next(i for i in robots.values() if i["name"] == name)
        floor, top = robot_outline(room, x, y, heading, info, pad=0.03)
        cv2.fillConvexPoly(mask, cv2.convexHull(np.int32(floor + top)), 255)
    return mask


# ------------------------------------------------------ colour robot finding

def hsv_mask(hsv, rng):
    lo, hi = rng["lo"], rng["hi"]
    if lo[0] <= hi[0]:
        return cv2.inRange(hsv, np.array(lo), np.array(hi))
    return cv2.inRange(hsv, np.array(lo), np.array([179, hi[1], hi[2]])) | \
        cv2.inRange(hsv, np.array([0, lo[1], lo[2]]), np.array(hi))


class ColourRobotFinder:
    """Finds robots by coloured tape on top: a green patch, plus a smaller piece
    at the front (pink = Cozmo, blue = MiP). The front piece says which robot it
    is and which way it faces. Long floor tape lines are ignored by their shape."""

    MIN_GREEN = 40          # px: smallest green patch that counts
    MAX_GREEN = 2500        # px: robot tape is about 300-700 px from a 6 ft ceiling; bigger is something else
    MIN_FRONT = 6           # px: smallest front piece that counts
    OUTSIDE = 0.30          # m: ignore green patches further than this outside the play area

    def __init__(self, robots, colours):
        self.robots = robots                      # tag -> info
        self.colours = colours
        self.by_front = {info.get("front_colour"): info for info in robots.values() if info.get("front_colour")}

    def small_pieces(self, mask, biggest):
        """Keep compact blobs; drop long thin ones (floor tape lines) and big ones."""
        n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
        keep = np.zeros_like(mask)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if area < self.MIN_FRONT or area > biggest or max(w, h) > 4 * max(1, min(w, h)):
                continue
            keep[lab == i] = 255
        return keep

    def find(self, frame, room, last=None):
        """{name: (x, y, heading)} in room metres. `last`: {name: (x, y, heading)} from
        moments ago, used when a front piece is hidden."""
        hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (3, 3), 0), cv2.COLOR_BGR2HSV)
        kernel = np.ones((3, 3), np.uint8)
        green = cv2.morphologyEx(hsv_mask(hsv, self.colours["green"]), cv2.MORPH_OPEN, kernel)
        n, lab, st, cen = cv2.connectedComponentsWithStats(green)
        patches = [(i, st[i][4], cen[i]) for i in range(1, n) if self.MIN_GREEN <= st[i][4] <= self.MAX_GREEN]
        if not patches:
            return {}
        biggest = 4 * max(a for _, a, _ in patches)
        fronts = {c: self.small_pieces(hsv_mask(hsv, self.colours[c]), biggest) for c in self.by_front}

        found, unknown, score = {}, [], {}
        for i, area, (gx, gy) in sorted(patches, key=lambda p: -p[1]):
            r = int(math.sqrt(area / math.pi) * 2.2) + 4      # look this far round the patch
            ring = np.zeros_like(green)
            cv2.circle(ring, (int(gx), int(gy)), r, 255, -1)
            best = None
            for colour, mask in fronts.items():
                near = cv2.bitwise_and(mask, ring)
                count = int(cv2.countNonZero(near))
                if count >= self.MIN_FRONT and (best is None or count > best[1]):
                    m = cv2.moments(near, binaryImage=True)
                    best = (colour, count, (m["m10"] / m["m00"], m["m01"] / m["m00"]))
            if best is None:
                unknown.append((gx, gy))
                continue
            info = self.by_front[best[0]]
            pose = self.pose(room, info, (gx, gy), best[2])
            if not pose or not self.in_play(room, pose):
                continue
            # Two patches that both look like the same robot: prefer the one near where it
            # was moments ago, otherwise the one with the clearer front piece.
            name = info["name"]
            near = -math.hypot(pose[0] - last[name][0], pose[1] - last[name][1]) if last and name in last else 0
            s = (near, best[1])
            if name not in found or s > score[name]:
                found[name], score[name] = pose, s

        # A patch whose front piece is hidden: give it to the missing robot that was nearest.
        for gx, gy in unknown:
            for info in self.robots.values():
                name = info["name"]
                if name in found or not last or name not in last:
                    continue
                spot = room.to_floor(gx, gy, info["tag_height"])
                lx, ly, lh = last[name]
                if spot and self.in_play(room, spot) and math.hypot(spot[0] - lx, spot[1] - ly) < 0.30:
                    found[name] = (spot[0], spot[1], lh)
                    break
        return found

    def in_play(self, room, spot):
        """Robots only play inside the taped area; green things elsewhere in the room don't count."""
        m = self.OUTSIDE
        return -m <= spot[0] <= room.width + m and -m <= spot[1] <= room.depth + m

    @staticmethod
    def pose(room, info, green_px, front_px):
        h = info["tag_height"]
        c = room.to_floor(*green_px, h)
        f = room.to_floor(*front_px, h)
        if c is None or f is None:
            return None
        heading = math.degrees(math.atan2(f[1] - c[1], f[0] - c[0])) + info.get("heading_offset", 0)
        rad = math.radians(heading)
        fwd = info.get("marker_forward", 0.0)
        return c[0] - fwd * math.cos(rad), c[1] - fwd * math.sin(rad), roomlib.wrap_degrees(heading)


# ------------------------------------------------------------ balloon finding

class ColourBalloonFinder:
    """Finds the biggest round blob of the balloon's colour."""

    def __init__(self, hsv):
        self.lo = list(hsv["lo"])
        self.hi = list(hsv["hi"])

    def mask(self, frame):
        hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (7, 7), 0), cv2.COLOR_BGR2HSV)
        lo, hi = self.lo, self.hi
        if lo[0] <= hi[0]:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        else:  # hue wraps round (red): two ranges
            m = cv2.inRange(hsv, np.array(lo), np.array([179, hi[1], hi[2]])) | \
                cv2.inRange(hsv, np.array([0, lo[1], lo[2]]), np.array(hi))
        kernel = np.ones((5, 5), np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel)
        return cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)

    def find(self, frame, skip=None):
        """The balloon's oval in the picture: ((x, y), (width, height), angle), or None.
        `skip` is a mask of places to ignore (where the robots are)."""
        mask = self.mask(frame)
        if skip is not None:
            mask = cv2.bitwise_and(mask, cv2.bitwise_not(skip))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in contours:
            area = cv2.contourArea(c)
            if area < 150:
                continue
            (x, y), r = cv2.minEnclosingCircle(c)
            roundness = area / (math.pi * r * r)
            if roundness < 0.45:
                continue
            if best is None or area > best[1]:
                best = (c, area)
        if best is None:
            return None
        hull = cv2.convexHull(best[0])  # fills in any bit a hand is covering
        return cv2.fitEllipse(hull) if len(hull) >= 5 else None

    def settings(self):
        return {"lo": self.lo, "hi": self.hi}


class YoloBalloonFinder:
    """Finds the balloon with a YOLOv8 Open Images model (has a 'Balloon' class)."""

    def __init__(self, model_path, conf):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        names = {v.lower(): k for k, v in self.model.names.items()}
        if "balloon" not in names:
            raise SystemExit(f"{model_path} has no 'Balloon' class. Use an Open Images (-oiv7) model.")
        self.cls = names["balloon"]
        self.conf = conf

    def find(self, frame, skip=None):
        r = self.model.predict(frame, classes=[self.cls], conf=self.conf, verbose=False)[0]
        boxes = [b for b in r.boxes if skip is None or
                 not skip[int((b.xyxy[0][1] + b.xyxy[0][3]) / 2), int((b.xyxy[0][0] + b.xyxy[0][2]) / 2)]]
        if not boxes:
            return None
        x1, y1, x2, y2 = max(boxes, key=lambda b: float(b.conf)).xyxy[0].tolist()
        return ((x1 + x2) / 2, (y1 + y2) / 2), (x2 - x1, y2 - y1), 0.0


# ----------------------------------------------------------------- state

class Smoother:
    """Simple smoothing so positions don't jitter. Resets after a gap."""

    def __init__(self, amount):
        self.amount = amount
        self.value = None
        self.when = 0

    def update(self, value, now):
        if self.value is None or now - self.when > LOST_AFTER:
            self.value = list(value)
        else:
            self.value = [self.amount * old + (1 - self.amount) * new for old, new in zip(self.value, value)]
        self.when = now
        return self.value


class State:
    def __init__(self, room, robots):
        self.lock = threading.Lock()
        self.room = room
        self.balloon_size = None        # m, sent so chase.py knows how big the balloon is
        self.robots = {
            info["name"]: {"id": int(tag), "x": None, "y": None, "heading": None, "when": None,
                           "really_seen": None, "hidden": False,
                           "size": {k: info[k] for k in ("length", "width", "height")}}
            for tag, info in robots.items()
        }
        self.balloon = {"x": None, "y": None, "height": None, "when": None}
        self.measuring = None  # list of balloon-size readings while F is measuring
        self.balloon_smooth = Smoother(0.5)

    def message(self):
        now = time.time()

        def freshness(when):
            age = None if when is None else round(now - when, 3)
            return {"seen": age is not None and age < LOST_AFTER, "age": age}

        with self.lock:
            robots = {
                name: {"id": r["id"], "x": r["x"], "y": r["y"], "heading": r["heading"],
                       "hidden": r["hidden"], **r["size"], **freshness(r["when"])}
                for name, r in self.robots.items()
            }
            b = self.balloon
            balloon = {"x": b["x"], "y": b["y"], "height": b["height"], **freshness(b["when"])}
        return {
            "type": "positions",
            "t": round(now, 3),
            "room": {"width": self.room.width, "depth": self.room.depth,
                     "clockwise": self.room.clockwise, "balloon_size": self.balloon_size},
            "robots": robots,
            "balloon": balloon,
        }


# ----------------------------------------------------------- WebSocket server

def start_server(state, host, port, rate):
    """Runs the WebSocket server in a background thread (the camera window needs the main thread)."""
    from websockets.asyncio.server import broadcast, serve

    clients = set()

    async def handler(ws):
        clients.add(ws)
        print(f"Listener connected ({len(clients)} now)")
        try:
            await ws.wait_closed()
        finally:
            clients.discard(ws)
            print(f"Listener left ({len(clients)} now)")

    async def run():
        async with serve(handler, host, port):
            print(f"Streaming positions on ws://{host}:{port}")
            while True:
                if clients:
                    broadcast(clients, json.dumps(state.message()))
                await asyncio.sleep(1 / rate)

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True).start()


# ------------------------------------------------------------------ drawing

def label(frame, msg, at, color):
    cv2.putText(frame, msg, at, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
    cv2.putText(frame, msg, at, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_floor(frame, room):
    for x in np.arange(0, room.width + 1e-6, 0.5):
        cv2.line(frame, room.to_pixel(x, 0), room.to_pixel(x, room.depth), (60, 120, 60), 1)
    for y in np.arange(0, room.depth + 1e-6, 0.5):
        cv2.line(frame, room.to_pixel(0, y), room.to_pixel(room.width, y), (60, 120, 60), 1)
    mid = room.width / 2
    cv2.line(frame, room.to_pixel(mid, 0), room.to_pixel(mid, room.depth), (255, 140, 0), 2)


def make_sliders(finder):
    cv2.namedWindow(SLIDERS, cv2.WINDOW_NORMAL)
    for i, ch in enumerate("HSV"):
        top = 179 if ch == "H" else 255
        cv2.createTrackbar(f"{ch} low", SLIDERS, finder.lo[i], top, lambda _: None)
        cv2.createTrackbar(f"{ch} high", SLIDERS, finder.hi[i], top, lambda _: None)


def read_sliders(finder):
    for i, ch in enumerate("HSV"):
        finder.lo[i] = cv2.getTrackbarPos(f"{ch} low", SLIDERS)
        finder.hi[i] = cv2.getTrackbarPos(f"{ch} high", SLIDERS)


# --------------------------------------------------------------------- main

def hidden_under_balloon(blob, room, robots, state, fresh, now):
    """A robot right under the balloon is hidden from the ceiling camera. Keep its
    last spot for a little while and mark it hidden, instead of losing it."""
    (u, v), (a, b), ang = blob
    rad = math.radians(ang)
    with state.lock:
        for info in robots.values():
            r = state.robots[info["name"]]
            if info["name"] in fresh or r["really_seen"] is None or now - r["really_seen"] > HIDDEN_HOLD:
                continue
            px, py = room.to_pixel(r["x"], r["y"], info["height"])
            dx, dy = px - u, py - v
            along = dx * math.cos(rad) + dy * math.sin(rad)
            across = -dx * math.sin(rad) + dy * math.cos(rad)
            if (along / (a / 2 * 1.1)) ** 2 + (across / (b / 2 * 1.1)) ** 2 <= 1:
                r.update(when=now, hidden=True)


def process(frame, room, robots, tags, balloon_finder, state, args, draw, colour_robots=None):
    now = time.time()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    found = tags.find(gray)
    poses, how = {}, {}
    for tag_id, corners in found.items():
        info = robots.get(str(tag_id))
        if info:
            pose = robot_pose(room, corners, info["tag_height"], info["heading_offset"], info["tag_forward"])
            if pose:
                poses[info["name"]], how[info["name"]] = pose, "tag"
    with state.lock:
        recent = {name: (r["x"], r["y"], r["heading"]) for name, r in state.robots.items()
                  if r["when"] and now - r["when"] < LOST_AFTER}
    if colour_robots:  # coloured tape: used for any robot whose tag wasn't read
        for name, pose in colour_robots.find(frame, room, recent).items():
            if name not in poses:
                poses[name], how[name] = pose, "tape"
    fresh = dict(poses)
    for name, pose in recent.items():  # robots seen moments ago still count, so a missed frame doesn't unmask them
        poses.setdefault(name, pose)
    # Look for the balloon before drawing on the picture, skipping where the robots are.
    blob = balloon_finder.find(frame, robots_mask(frame.shape, room, poses, robots))
    if draw:
        draw_floor(frame, room)

    for tag_id, corners in found.items():
        info = robots.get(str(tag_id))
        if draw and not info:
            cv2.polylines(frame, [corners.astype(int)], True, (120, 120, 120), 2)
            label(frame, f"unknown tag {tag_id}", tuple(corners[0].astype(int)), (160, 160, 160))
        elif draw and info["name"] in fresh:
            cv2.polylines(frame, [corners.astype(int)], True, (0, 255, 0), 2)

    for info in robots.values():
        if info["name"] not in fresh:
            continue
        x, y, heading = fresh[info["name"]]
        with state.lock:
            state.robots[info["name"]].update(
                x=round(x, 3), y=round(y, 3), heading=round(heading, 1), when=now,
                really_seen=now, hidden=False)
        if draw:
            floor, top = robot_outline(room, x, y, heading, info)
            cv2.polylines(frame, [np.int32(floor)], True, (255, 200, 0), 1)
            cv2.polylines(frame, [np.int32(top)], True, (255, 200, 0), 2)
            for a, b in zip(floor, top):
                cv2.line(frame, a, b, (255, 200, 0), 1)
            c = room.to_pixel(x, y, info["height"])
            rad = math.radians(heading)
            tip = room.to_pixel(x + 0.25 * math.cos(rad), y + 0.25 * math.sin(rad), info["height"])
            cv2.arrowedLine(frame, c, tip, (0, 255, 0), 3, tipLength=0.3)
            label(frame, f"{info['name']} ({x:.2f}, {y:.2f}) {heading:.0f} deg [{how[info['name']]}]",
                  (c[0] + 12, c[1] - 12), (0, 255, 0))

    if blob and state.measuring is not None:
        size = room.ball_size_on_floor(blob)
        if size:
            state.measuring.append(size)
    if blob:
        (u, v), axes, ang = blob
        r = max(axes) / 2
        pos = room.sphere_position(blob, args.balloon_size)
        if pos and -1 < pos[2] < 5:
            bx, by, bh = state.balloon_smooth.update((pos[0], pos[1], max(0.0, pos[2])), now)
            with state.lock:
                state.balloon.update(x=round(bx, 3), y=round(by, 3), height=round(bh, 2), when=now)
            hidden_under_balloon(blob, room, robots, state, fresh, now)
            if draw:
                cv2.ellipse(frame, blob, (0, 200, 255), 2)
                spot = room.to_pixel(bx, by, 0)
                cv2.drawMarker(frame, spot, (0, 200, 255), cv2.MARKER_TILTED_CROSS, 24, 2)
                cv2.line(frame, (int(u), int(v)), spot, (0, 200, 255), 1)
                label(frame, f"balloon ({bx:.2f}, {by:.2f}) {bh:.2f} m up", (int(u + r) + 8, int(v)), (0, 200, 255))
    return found


def main():
    p = argparse.ArgumentParser(description="Find the robots and balloon and stream their positions.")
    p.add_argument("--source", default="0", help="Webcam number, or a video or picture file")
    p.add_argument("--room", default=str(roomlib.ROOM_FILE), help="Settings file from floor_setup.py")
    p.add_argument("--host", default="0.0.0.0", help="Network address to stream on (0.0.0.0 = any)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--rate", type=float, default=15, help="Messages per second")
    p.add_argument("--balloon-size", type=float, default=None,
                   help="Balloon width in metres (default 0.36 until measured). Or rest it on the floor and press F to measure")
    p.add_argument("--yolo", help="Find the balloon with this YOLO model instead of by colour")
    p.add_argument("--conf", type=float, default=0.25, help="YOLO confidence")
    p.add_argument("--decimate", type=float, default=1.0,
                   help="Tag search shrink factor. 1 = full detail (best for small tags), 2 = faster")
    p.add_argument("--no-tape", action="store_true",
                   help="Don't look for the coloured tape on the robots (tags only)")
    p.add_argument("--tune", action="store_true", help="Show balloon colour sliders")
    p.add_argument("--no-window", action="store_true", help="Don't show the preview window")
    p.add_argument("--once", action="store_true", help="Process one picture, print the message and stop")
    args = p.parse_args()

    settings = roomlib.load_settings(args.room)
    room = roomlib.Room(settings)
    if args.balloon_size is None:
        args.balloon_size = settings.get("balloon_size", 0.36)   # same guess as chase.py and guard.py until measured with F
    robots = roomlib.robot_settings(settings)
    tags = TagFinder(args.decimate)
    colour_robots = None if args.no_tape else ColourRobotFinder(
        robots, {**roomlib.DEFAULT_MARKER_HSV, **settings.get("marker_hsv", {})})
    if args.yolo:
        balloon_finder = YoloBalloonFinder(args.yolo, args.conf)
    else:
        balloon_finder = ColourBalloonFinder(settings.get("balloon_hsv", roomlib.DEFAULT_BALLOON_HSV))
    state = State(room, robots)
    state.balloon_size = args.balloon_size
    print(f"Robots: tags ({tags.kind}){'' if args.no_tape else ' and coloured tape'}. Balloon: {'YOLO' if args.yolo else 'colour'}. "
          f"Camera {room.camera_height:.2f} m up.")

    still = Path(args.source).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    if args.once:
        frame = cv2.imread(args.source) if still else roomlib.open_camera(args.source).read()[1]
        if frame is None:
            raise SystemExit(f"Could not read {args.source}")
        process(frame, room, robots, tags, balloon_finder, state, args, draw=True, colour_robots=colour_robots)
        print(json.dumps(state.message(), indent=2))
        out = Path("tracker_check.jpg")
        cv2.imwrite(str(out), frame)
        print(f"Saved {out.resolve()}")
        return

    start_server(state, args.host, args.port, args.rate)
    picture = cv2.imread(args.source) if still else None
    cap = None if still else roomlib.open_camera(args.source)
    tuning = False
    if args.tune and not args.yolo:
        make_sliders(balloon_finder)
        tuning = True

    frames, fps_time, fps = 0, time.time(), 0.0
    try:
        while True:
            if still:
                frame = picture.copy()
                time.sleep(1 / 30)
            else:
                ok, frame = cap.read()
                if not ok:
                    print("Camera stopped sending pictures.")
                    break
            draw = not args.no_window
            if tuning:
                read_sliders(balloon_finder)
                clean = frame.copy()
            process(frame, room, robots, tags, balloon_finder, state, args, draw, colour_robots)

            frames += 1
            if time.time() - fps_time >= 1:
                fps = frames / (time.time() - fps_time)
                frames, fps_time = 0, time.time()
            if not draw:
                continue
            if state.measuring is not None:
                if len(state.measuring) >= MEASURE_FRAMES:
                    args.balloon_size = float(np.median(state.measuring))
                    settings["balloon_size"] = round(args.balloon_size, 3)
                    state.balloon_size = args.balloon_size
                    roomlib.save_settings(settings, args.room)
                    state.measuring = None
                    print(f"Balloon measured: {args.balloon_size * 100:.0f} cm wide "
                          f"({args.balloon_size / 0.0254:.0f} inches). Saved.")
                else:
                    label(frame, f"Measuring balloon on the floor... {len(state.measuring)}/{MEASURE_FRAMES}",
                          (12, 64), (0, 255, 255))
            label(frame, f"{fps:.0f} fps   Q quit   F balloon on floor   T colour sliders   S save sliders",
                  (12, 28), (255, 255, 255))
            cv2.imshow(WINDOW, frame)
            if tuning:
                small = cv2.resize(balloon_finder.mask(clean), None, fx=0.4, fy=0.4)
                cv2.imshow(SLIDERS, small)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("f"):
                state.measuring = []
                print("Measuring the balloon: keep it resting on the floor, in view...")
            if key == ord("t") and not args.yolo:
                if tuning:
                    cv2.destroyWindow(SLIDERS)
                else:
                    make_sliders(balloon_finder)
                tuning = not tuning
            if key == ord("s") and not args.yolo:
                settings["balloon_hsv"] = balloon_finder.settings()
                roomlib.save_settings(settings, args.room)
                print(f"Saved balloon colour {balloon_finder.settings()}")
    except KeyboardInterrupt:
        pass
    finally:
        if cap:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
