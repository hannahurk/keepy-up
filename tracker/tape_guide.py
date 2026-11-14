"""
Show where to tape the floor, drawn on the live camera view.

    python tape_guide.py --source 0 --camera-height 1.98                 # keepy uppy
    python tape_guide.py --source 0 --camera-height 1.98 --game soccer   # floor soccer

For a ceiling camera looking straight down. The top of the picture is called
the "back" and the bottom the "front"; no wall is needed.

Both games use the same play area and the same 4 purple tape crosses, numbered
like the build guide:
    1 back-left (0, 0)    2 back-right
    4 front-left          3 front-right
Click them in that same order, 1 to 4, in floor_setup.py. The robots always
stay inside the play area.

Keepy uppy also shows:
  - (blue tape) Cozmo's and MiP's rest spots: where each robot waits, in the back corner
    of its half, inside the play area
  - the middle line: Cozmo plays the left half, MiP the right half
Floor soccer also shows:
  - (pink tape) a goal at each end (tape the two posts of each), the centre
    line (a solid boundary: like air hockey, people and robots each stay on
    their own side and only the balloon crosses), and where the
    robots wait: on either side of the robots' goal, just in front of the goal
    line (Cozmo by the back post, MiP by the front post). These are different
    from the keepy uppy rest spots.

It starts with the biggest play area that fits in the picture. Resize it while
you watch (10 cm steps):
    + / -   wider / narrower     ] / [   deeper / shallower
    g       switch between keepy uppy and floor soccer

Sizes are worked out from the camera height and a typical lens, so they're
approximate. Tape where the markers show, then MEASURE the real distances and
give those to floor_setup.py. When you quit, it prints where the rest spots
and goals are, measured from cross 1, so you can tape them precisely.

Keys: q = quit. Nothing is saved.
"""

import argparse
import math

import cv2
import numpy as np

import room as roomlib

WINDOW = "Where to tape the floor"
MARGIN = 0.06   # keep the crosses this fraction of the picture away from its edges
# Drawn in the same colours as the tape (OpenCV colours are blue, green, red):
#   purple = the 4 corner crosses (both games)   blue = keepy uppy   pink = floor soccer
# Don't tape with yellow or orange (the camera would mistake it for the yellow balloon),
# or fluorescent green (too close to yellow).
PURPLE, BLUE, PINK, GREY = (235, 60, 175), (255, 110, 30), (140, 70, 255), (200, 200, 200)
TAPE_KEY = "Tape: PURPLE crosses (both games)  BLUE keepy uppy  PINK soccer"
GOAL_NET = 0.12   # m: hatched "net" drawn behind each goal line (outside the play area)
POST_TICK = 0.12  # m: short tick into the pitch at each post


def text(frame, msg, x, y, color, scale=0.9):
    cv2.putText(frame, msg, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
    cv2.putText(frame, msg, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)


def dashed(frame, a, b, color, thickness=3, n=10):
    for i in range(0, n, 2):
        pa = (int(a[0] + (b[0] - a[0]) * i / n), int(a[1] + (b[1] - a[1]) * i / n))
        pb = (int(a[0] + (b[0] - a[0]) * (i + 1) / n), int(a[1] + (b[1] - a[1]) * (i + 1) / n))
        cv2.line(frame, pa, pb, color, thickness, cv2.LINE_AA)


class Layout:
    """The play area drawn for a straight-down camera, centred in the picture."""

    def __init__(self, w, h, camera_height, hfov):
        self.w, self.h = w, h
        self.ppm = ((w / 2) / math.tan(math.radians(hfov) / 2)) / camera_height  # pixels per floor metre

    def biggest(self):
        return (math.floor(self.w * (1 - 2 * MARGIN) / self.ppm * 10) / 10,
                math.floor(self.h * (1 - 2 * MARGIN) / self.ppm * 10) / 10)

    def px(self, width, depth, x, y):
        left = self.w / 2 - width / 2 * self.ppm
        top = self.h / 2 - depth / 2 * self.ppm
        return int(left + x * self.ppm), int(top + y * self.ppm)


def draw_play_area(frame, P, width, depth):
    h, w = frame.shape[:2]
    pts = [P(0, 0), P(width, 0), P(width, depth), P(0, depth)]
    overlay = frame.copy()
    cv2.fillPoly(overlay, [np.int32(pts)], (255, 230, 200))
    cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)
    cv2.polylines(frame, [np.int32(pts)], True, PURPLE, 2, cv2.LINE_AA)
    inside = True
    for (x, y), name in zip(pts, ["1 back-left", "2 back-right", "3 front-right", "4 front-left"]):
        inside &= 0 <= x < w and 0 <= y < h
        cv2.drawMarker(frame, (x, y), PURPLE, cv2.MARKER_TILTED_CROSS, 56, 5)
        # back crosses: label just above, clear of the rest spots; front: just inside
        text(frame, name, x + (-230 if x > w / 2 else 30), y + (-18 if y < h / 2 else -26), PURPLE, 0.9)
    return inside


def draw_keepy_up(frame, P, width, depth):
    dashed(frame, P(width / 2, 0), P(width / 2, depth), BLUE, 2, 20)
    lx, ly = P(width / 4, depth * 0.7)
    rx, ry = P(3 * width / 4, depth * 0.7)
    text(frame, "Cozmo's half", lx - 95, ly, BLUE, 0.8)
    text(frame, "MiP's half", rx - 75, ry, BLUE, 0.8)
    for name, (x0, y0, x1, y1) in roomlib.rest_spots(width, depth).items():
        corners = [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            dashed(frame, a, b, BLUE, 3, 8)
        cx, cy = P((x0 + x1) / 2, (y0 + y1) / 2)
        label = "Cozmo" if name == "cozmo" else "MiP"
        text(frame, f"{label}'s spot", cx - 80, cy + 50, BLUE, 0.7)


def draw_soccer(frame, P, width, depth, robots_side):
    # centre line: a solid boundary, like air hockey. People and robots each stay on their side.
    cv2.line(frame, P(width / 2, 0), P(width / 2, depth), (255, 255, 255), 12, cv2.LINE_AA)
    cv2.line(frame, P(width / 2, 0), P(width / 2, depth), PINK, 7, cv2.LINE_AA)
    for side in ("left", "right"):
        team = "ROBOTS' SIDE" if side == robots_side else "PEOPLE'S SIDE"
        sx, sy = P(width * (0.25 if side == "left" else 0.75), depth * 0.82)
        text(frame, team, sx - 105, sy, PINK, 0.9)
    tx, ty = P(width / 2, depth * 0.08)
    text(frame, "Centre line: stay on your side", tx + 22, ty + 10, PINK, 0.8)
    for side, (x, y0, y1) in roomlib.goals(width, depth).items():
        out = -1 if side == "left" else 1          # direction away from the pitch
        a, b = P(x, y0), P(x, y1)
        # hatched "net" behind the goal line, outside the play area
        net = [P(x, y0), P(x + out * GOAL_NET, y0), P(x + out * GOAL_NET, y1), P(x, y1)]
        overlay = frame.copy()
        cv2.fillPoly(overlay, [np.int32(net)], PINK)
        cv2.addWeighted(overlay, 0.30, frame, 0.70, 0, frame)
        for k in range(1, 9):
            ya = y0 + (y1 - y0) * k / 9
            cv2.line(frame, P(x, ya), P(x + out * GOAL_NET, ya - 0.06), PINK, 1, cv2.LINE_AA)
        cv2.polylines(frame, [np.int32(net)], True, PINK, 2, cv2.LINE_AA)
        # thick solid goal line (tape this as one solid pink strip)
        cv2.line(frame, a, b, (255, 255, 255), 18, cv2.LINE_AA)
        cv2.line(frame, a, b, PINK, 12, cv2.LINE_AA)
        # posts: big dots, with a short tick into the pitch (tape an L at each post)
        for post_y in (y0, y1):
            p0, p1 = P(x, post_y), P(x - out * POST_TICK, post_y)
            cv2.line(frame, p0, p1, PINK, 10, cv2.LINE_AA)
            cv2.circle(frame, p0, 16, (255, 255, 255), -1)
            cv2.circle(frame, p0, 12, PINK, -1)
        team = "ROBOTS'" if side == robots_side else "PEOPLE'S"
        # label just above the top post, clear of the goalkeeper's spot
        text(frame, f"{team} GOAL", a[0] + (24 if side == "left" else -260), a[1] - 30, PINK, 1.05)
    # where Cozmo (goalkeeper) and MiP (defender) wait
    for name, (x0, y0, x1, y1) in roomlib.soccer_spots(width, depth, robots_side).items():
        corners = [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            dashed(frame, a, b, PINK, 3, 8)
        _, cy = P(0, (y0 + y1) / 2)
        label = "Cozmo" if name == "cozmo" else "MiP"
        lx = min(c[0] for c in corners) - 105 if robots_side == "right" else max(c[0] for c in corners) + 15
        text(frame, label, lx, cy + 8, PINK, 0.8)


SOCCER_LABELS = {"cozmo": "Cozmo's spot (by the back post)", "mip": "MiP's spot (by the front post)"}


def print_measurements(width, depth, game, robots_side):
    print(f"\nPlay area shown: about {width:.1f} m wide x {depth:.1f} m deep.")
    print("Measured from cross 1 (right = toward cross 2, forward = toward cross 4):")
    if game == "soccer":
        for side, (x, y0, y1) in roomlib.goals(width, depth).items():
            team = "Robots'" if side == robots_side else "People's"
            print(f"  {team} goal ({side} end, {x * 100:.0f} cm right): posts at "
                  f"{y0 * 100:.0f} cm and {y1 * 100:.0f} cm forward")
        for name, (x0, y0, x1, y1) in roomlib.soccer_spots(width, depth, robots_side).items():
            print(f"  {SOCCER_LABELS[name]}: {x0 * 100:.0f} to {x1 * 100:.0f} cm right, "
                  f"{y0 * 100:.0f} to {y1 * 100:.0f} cm forward")
    else:
        for name, (x0, y0, x1, y1) in roomlib.rest_spots(width, depth).items():
            label = "Cozmo" if name == "cozmo" else "MiP"
            print(f"  {label}'s spot: {x0 * 100:.0f} to {x1 * 100:.0f} cm right, "
                  f"{y0 * 100:.0f} to {y1 * 100:.0f} cm forward")
    print("Then map the floor with your MEASURED play area, for example:\n"
          f"  python floor_setup.py --source 0 --width {width:.1f} --depth {depth:.1f} --camera-height 1.98")


def main():
    p = argparse.ArgumentParser(description="Show where to tape the floor.")
    p.add_argument("--source", default="0", help="Webcam number")
    p.add_argument("--camera-height", type=float, required=True, help="Floor to camera lens, metres")
    p.add_argument("--game", choices=["keepy-up", "soccer"], default="keepy-up")
    p.add_argument("--robots-defend", choices=["left", "right"], default="right",
                   help="Soccer: which end's goal the robots defend")
    p.add_argument("--width", type=float, default=None, help="Play area width, metres (default: biggest that fits)")
    p.add_argument("--depth", type=float, default=None, help="Play area depth, metres (default: biggest that fits)")
    p.add_argument("--hfov", type=float, default=82, help="Lens width in degrees (EMEET C960: about 82, worked out from the taped arena)")
    args = p.parse_args()

    cap = roomlib.open_camera(args.source)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    print(__doc__)
    width, depth, game, lay = args.width, args.depth, args.game, None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        if lay is None:
            lay = Layout(w, h, args.camera_height, args.hfov)
            fit_w, fit_d = lay.biggest()
            width, depth = width or fit_w, depth or fit_d
            print(f"Starting with a play area of about {width:.1f} x {depth:.1f} m, the biggest that fits.")
        P = lambda x, y: lay.px(width, depth, x, y)
        inside = draw_play_area(frame, P, width, depth)
        if game == "soccer":
            draw_soccer(frame, P, width, depth, args.robots_defend)
        else:
            draw_keepy_up(frame, P, width, depth)
        title = "Floor soccer" if game == "soccer" else "Keepy uppy"
        text(frame, f"{title}  -  back (top of the picture)", w / 2 - 260, 34, GREY, 0.8)
        text(frame, TAPE_KEY, 12, h - 52, GREY, 0.7)
        if not inside:
            text(frame, "Too big: a cross is outside the picture. Press - or [", 12, 108, (0, 0, 255), 0.8)
        text(frame, "+/- wider/narrower   ]/[ deeper/shallower   g switch game   q quit",
             12, h - 16, GREY, 0.8)
        cv2.imshow(WINDOW, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("g"):
            game = "keepy-up" if game == "soccer" else "soccer"
        step = {ord("+"): (0.1, 0), ord("="): (0.1, 0), ord("-"): (-0.1, 0),
                ord("]"): (0, 0.1), ord("["): (0, -0.1)}.get(key)
        if step:
            width = max(0.8, round(width + step[0], 2))
            depth = max(0.6, round(depth + step[1], 2))
            print(f"Play area about {width:.1f} x {depth:.1f} m")
    cap.release()
    cv2.destroyAllWindows()
    if lay is not None:
        print_measurements(width, depth, game, args.robots_defend)


if __name__ == "__main__":
    main()
