"""
Shared room and camera maths for the Keepy Up tracker.

Room coordinates are in metres, using the build guide's crosses:
  x = from tape cross 1 (back-left) toward cross 2 (back-right)
  y = from tape cross 1 toward cross 4 (front-left)
  z = height above the floor
Heading is in degrees: 0 points toward cross 2, 90 points toward cross 4.
With the guide's cross order, seen from above, heading goes up clockwise
(Room.clockwise is True); with the opposite order it goes up anticlockwise.
Anything that steers a robot must check this (chase.py does).

Setup is saved in room.json by floor_setup.py.
"""

import json
import math
import shlex
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOM_FILE = Path(__file__).with_name("room.json")

# Which AprilTag (tag36h11) is on which robot, and each robot's size in metres.
# Change these in room.json if your robots differ. The sizes are rough
# estimates: measure your robots with a ruler and put the real numbers in.
#   tag_height     how high the tag sits above the floor
#   length         front to back (Cozmo: include the lift arms)
#   width          side to side (MiP: wheel to wheel)
#   height         floor to the top
#   tag_forward    how far the tag's centre is in front of the robot's middle
#                  (negative = behind the middle, e.g. a tag on Cozmo's back)
DEFAULT_ROBOTS = {
    "1": {"name": "cozmo", "tag_height": 0.07, "heading_offset": 0,
          "length": 0.10, "width": 0.06, "height": 0.075, "tag_forward": -0.02,
          "front_colour": "pink", "marker_forward": 0.0},
    "2": {"name": "mip", "tag_height": 0.20, "heading_offset": 0,
          "length": 0.09, "width": 0.11, "height": 0.20, "tag_forward": 0.0,
          "front_colour": "blue", "marker_forward": 0.0},
}

# Coloured tape on top of the robots (an alternative to tags the camera can't read
# from far away): a green patch on each robot, plus a smaller piece at the front
# whose colour says which robot it is. OpenCV HSV ranges; hue runs 0-179.
# Measured under the room's lighting: green hue 60-80, pink 171-175, blue 96-109.
DEFAULT_MARKER_HSV = {
    "green": {"lo": [48, 60, 60], "hi": [92, 255, 255]},
    "pink": {"lo": [150, 60, 80], "hi": [8, 255, 255]},      # wraps round past 179
    "blue": {"lo": [92, 80, 50], "hi": [130, 255, 255]},
}


def robot_settings(settings):
    """Robots from room.json, with any missing size filled in from the defaults."""
    robots = {}
    for tag, info in settings.get("robots", DEFAULT_ROBOTS).items():
        robots[tag] = {**DEFAULT_ROBOTS.get(tag, {"length": 0.1, "width": 0.1, "height": 0.1,
                                                   "tag_forward": 0.0, "heading_offset": 0}), **info}
    return robots


# ------------------------------------------------------------ floor layout
# Everything here is in room metres (cross 1 = (0, 0), x toward cross 2,
# y toward cross 4, "back" = the cross 1-2 side). The robots always stay
# inside the play area, so their rest spots are inside it too.

REST_SIZE = 0.42   # side of each robot's rest square (matches the blue tape, measured on camera)
GOAL_WIDTH = 0.72  # soccer goal mouth, between the posts (matches the taped marks, seen on camera)
CENTRE_SPOT = 0.20  # radius of the soccer serving spot (not used: either side can serve)
EDGE = 0.06        # gap between the robot spots and the play area's edges (as taped)


def rest_spots(width, depth, size=REST_SIZE):
    """{name: (x0, y0, x1, y1)}: each robot's rest square, in the back corner of its half."""
    size = min(size, width / 2 - 2 * EDGE, depth - 2 * EDGE)
    return {"cozmo": (EDGE, EDGE, EDGE + size, EDGE + size),
            "mip": (width - EDGE - size, EDGE, width - EDGE, EDGE + size)}


SOUNDS = Path(__file__).resolve().parent.parent / "sounds"


def play_on_mac(*names):
    """Play sounds/<name>.wav on the Mac's speakers, one after another, without waiting
    (game sound effects: count, start, goal, win, near_miss, out, miss, stop). Loudness follows the
    Mac's volume."""
    paths = [SOUNDS / f"{n}.wav" for n in names if (SOUNDS / f"{n}.wav").exists()]
    if paths:
        subprocess.Popen(["/bin/sh", "-c", "; ".join(f"afplay {shlex.quote(str(p))}" for p in paths)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def goals(width, depth, goal_width=GOAL_WIDTH):
    """{"left"/"right": (x, y_low, y_high)}: soccer goal lines at the left and right ends."""
    half = min(goal_width, depth) / 2
    return {"left": (0.0, depth / 2 - half, depth / 2 + half),
            "right": (width, depth / 2 - half, depth / 2 + half)}


def centre_spot(width, depth):
    return width / 2, depth / 2


SOCCER_SPOT = 0.30   # side of each robot's soccer spot (matches the pink tape)


def soccer_side(width, side):
    """(x_low, x_high) of one team's half in floor soccer. Like air hockey, people
    and robots never cross the centre line: only the balloon does."""
    return (0.0, width / 2) if side == "left" else (width / 2, width)


def soccer_spots(width, depth, robots_defend="right", goal_width=GOAL_WIDTH, size=SOCCER_SPOT):
    """{name: (x0, y0, x1, y1)}: where each robot waits in floor soccer.
    The robots stand on either side of their goal, just in front of the goal
    line: Cozmo by the back post, MiP by the front post, with a gap between
    them in the middle of the goal. Both are inside the play area."""
    x, y0, y1 = goals(width, depth, goal_width)[robots_defend]
    size = min(size, (y1 - y0) / 2)
    x0 = x - EDGE - size if robots_defend == "right" else x + EDGE
    return {"cozmo": (x0, y0, x0 + size, y0 + size),
            "mip": (x0, y1 - size, x0 + size, y1)}


def robot_corners(x, y, heading_deg, length, width):
    """Room (x, y) of a robot's 4 footprint corners: front-left, front-right, back-right, back-left."""
    h = math.radians(heading_deg)
    fx, fy = math.cos(h), math.sin(h)    # forward
    lx, ly = -fy, fx                     # left
    hl, hw = length / 2, width / 2
    return [(x + fx * a + lx * b, y + fy * a + ly * b)
            for a, b in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]

# Default balloon colour: a bright yellow balloon. Tune with tracker.py --tune.
DEFAULT_BALLOON_HSV = {"lo": [18, 90, 110], "hi": [38, 255, 255]}


def load_settings(path=ROOM_FILE):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_settings(data, path=ROOM_FILE):
    Path(path).write_text(json.dumps(data, indent=2))


def open_camera(source):
    """Open a webcam number or a video file, asking webcams for 1080p."""
    if str(source).isdigit():
        cap = cv2.VideoCapture(int(source))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    else:
        cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise SystemExit(
            "Could not open the camera. On a Mac, allow camera access for your terminal app in "
            "System Settings > Privacy & Security > Camera, then try again.\n"
            "If you have more than one camera, try --source 1."
        )
    return cap


def guess_camera_matrix(width, height, hfov_deg):
    """Rough lens model used until the checkerboard lens step is done."""
    f = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    return np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]], dtype=float)


def estimate_focal(clicks, width_m, depth_m, image_w, image_h):
    """Estimate the lens focal length (pixels) from the 4 crosses.

    Only works when the camera looks at the floor at an angle (the corner
    stand). Returns None if the clicks can't tell, e.g. a ceiling camera
    looking straight down.
    """
    world = np.float64([[0, 0], [width_m, 0], [width_m, depth_m], [0, depth_m]])
    H, _ = cv2.findHomography(world, np.float64(clicks))
    if H is None:
        return None
    T = np.array([[1, 0, -image_w / 2], [0, 1, -image_h / 2], [0, 0, 1]], dtype=float)
    h = T @ H
    h1, h2 = h[:, 0], h[:, 1]
    # In the real world the floor's x and y directions are at right angles and equally scaled.
    A = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = -np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    a = float(A @ b) / float(A @ A)
    if a <= 0:
        return None
    f = 1 / math.sqrt(a)
    return f if image_w / 6 < f < image_w * 3 else None


def camera_tilt(rvec):
    """Degrees the camera is tilted away from looking straight down."""
    R, _ = cv2.Rodrigues(np.asarray(rvec, dtype=float).reshape(3, 1))
    axis = R.T @ np.array([0.0, 0.0, 1.0])
    return math.degrees(math.acos(min(1.0, abs(axis[2]))))


def solve_camera_pose(clicks, width_m, depth_m, K, dist):
    """Find where the camera is from the 4 clicked tape crosses."""
    world = np.array(
        [[0, 0, 0], [width_m, 0, 0], [width_m, depth_m, 0], [0, depth_m, 0]], dtype=float
    )
    image = np.array(clicks, dtype=float)

    def fit_error(rvec, tvec):
        projected, _ = cv2.projectPoints(world, rvec, tvec, K, dist)
        return float(np.mean(np.linalg.norm(projected.reshape(-1, 2) - image, axis=1)))

    # A camera looking almost straight down has two near-mirror answers, and
    # any one method can pick the wrong one. Try several and keep the best fit.
    candidates = []
    try:
        n, rvecs, tvecs, _ = cv2.solvePnPGeneric(world, image, K, dist, flags=cv2.SOLVEPNP_IPPE)
        candidates += list(zip(rvecs[:n], tvecs[:n]))
    except cv2.error:
        pass
    ok, rvec, tvec = cv2.solvePnP(world, image, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if ok:
        candidates.append((rvec, tvec))
    if not candidates:
        raise ValueError("Could not work out the camera position from those clicks.")
    refined = []
    for rvec, tvec in candidates:
        rvec, tvec = cv2.solvePnPRefineLM(world, image, K, dist, rvec.copy(), tvec.copy())
        refined.append((fit_error(rvec, tvec), rvec, tvec))
    error_px, rvec, tvec = min(refined, key=lambda c: c[0])
    return rvec, tvec, error_px


class Room:
    """Turns camera pixels into room positions (and back)."""

    def __init__(self, settings):
        if "camera" not in settings or "rvec" not in settings["camera"]:
            raise SystemExit("No floor setup found. Run floor_setup.py first.")
        cam = settings["camera"]
        self.width = settings["width"]
        self.depth = settings["depth"]
        self.image_size = tuple(cam["image_size"])
        self.K = np.array(cam["K"], dtype=float)
        self.dist = np.array(cam["dist"], dtype=float)
        self.rvec = np.array(cam["rvec"], dtype=float).reshape(3, 1)
        self.tvec = np.array(cam["tvec"], dtype=float).reshape(3, 1)
        self.R, _ = cv2.Rodrigues(self.rvec)
        self.cam_pos = (-self.R.T @ self.tvec).ravel()
        # If the crosses were clicked the other way round, the maths ends up
        # with "up" pointing into the floor. Flip heights so up is always up.
        self.up = 1.0 if self.cam_pos[2] > 0 else -1.0

    @property
    def clockwise(self):
        """True if heading increases clockwise when seen from above."""
        return self.up < 0

    @property
    def camera_height(self):
        return abs(self.cam_pos[2])

    def _normalized(self, u, v):
        pt = np.array([[[u, v]]], dtype=float)
        return cv2.undistortPoints(pt, self.K, self.dist).reshape(2)

    def ray(self, u, v):
        """Direction (in room coordinates) the camera looks through pixel (u, v)."""
        x, y = self._normalized(u, v)
        d = self.R.T @ np.array([x, y, 1.0])
        return d / np.linalg.norm(d)

    def to_floor(self, u, v, height=0.0):
        """Room (x, y) of the point at pixel (u, v) that is `height` metres above the floor."""
        d = self.ray(u, v)
        c = self.cam_pos
        z = self.up * height
        if abs(d[2]) < 1e-9:
            return None
        s = (z - c[2]) / d[2]
        if s <= 0:
            return None
        p = c + s * d
        return float(p[0]), float(p[1])

    def to_pixel(self, x, y, height=0.0):
        pt = np.array([[x, y, self.up * height]], dtype=float)
        out, _ = cv2.projectPoints(pt, self.rvec, self.tvec, self.K, self.dist)
        u, v = out.reshape(2)
        return int(round(u)), int(round(v))

    def _cone(self, ellipse):
        """Direction to a ball's centre (room coordinates) and half the angle it
        covers, from the oval it makes in the picture.

        Away from the middle of the picture a round ball looks like an oval,
        stretched along the line from the picture's centre. The two ends of
        that line are exactly the ball's edges as the camera sees them.
        """
        (cx, cy), (w, h), ang = ellipse
        u = np.array([cx - self.K[0, 2], cy - self.K[1, 2]])
        u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1 else np.array([1.0, 0.0])
        t = math.radians(ang)
        half = math.hypot(w / 2 * (u @ [math.cos(t), math.sin(t)]),
                          h / 2 * (u @ [-math.sin(t), math.cos(t)]))
        rays = []
        for sign in (1, -1):
            x, y = self._normalized(cx + sign * half * u[0], cy + sign * half * u[1])
            d = np.array([x, y, 1.0])
            rays.append(d / np.linalg.norm(d))
        alpha = math.acos(float(np.clip(rays[0] @ rays[1], -1, 1))) / 2
        if alpha < 1e-6:
            return None, None
        centre = (rays[0] + rays[1]) / np.linalg.norm(rays[0] + rays[1])
        return self.R.T @ centre, alpha

    def sphere_position(self, ellipse, diameter_m):
        """Room (x, y, height) of a ball's centre, from the oval it makes in the
        picture and its real width. Bigger on screen = closer to the camera."""
        ray, alpha = self._cone(ellipse)
        if ray is None:
            return None
        p = self.cam_pos + (diameter_m / 2) / math.sin(alpha) * ray
        return float(p[0]), float(p[1]), float(self.up * p[2])

    def ball_size_on_floor(self, ellipse):
        """Real width (m) of a ball that is resting on the floor right now."""
        ray, alpha = self._cone(ellipse)
        if ray is None:
            return None
        s, dz, cz = math.sin(alpha), self.up * ray[2], self.camera_height
        if s - dz <= 0:
            return None
        return 2 * s * cz / (s - dz)


def wrap_degrees(a):
    """Wrap an angle to -180..180."""
    return (a + 180) % 360 - 180
