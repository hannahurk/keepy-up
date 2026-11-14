"""
Teach the tracker where the floor is.

Step 1 (recommended, once per camera): straighten the wide-angle lens.
    python floor_setup.py --lens
  Hold a printed checkerboard (default 9 x 6 inner corners, 25 mm squares)
  in front of the camera. Press SPACE when the corners are drawn in colour,
  about 15 times at different angles and distances, covering the corners
  of the picture too. Then press C to calculate.

Step 2 (every time the camera moves): click the 4 tape crosses.
    python floor_setup.py --width 3 --depth 3                      # corner stand, angled down
    python floor_setup.py --width 2 --depth 2 --camera-height 2.6  # ceiling, looking straight down
  For a ceiling camera, measure from the floor to the camera lens: looking
  straight down, the crosses alone can't show how wide the lens is.
  Click the crosses in the build guide's order ("back" = the drawing wall the
  children face):
    1 back-left (0, 0)   2 back-right   3 front-right   4 front-left
  tape_guide.py shows where to tape them. Cozmo plays on the left half
  (crosses 1 and 4), MiP on the right half.
  Keys: U = undo last click, S = save, Q = quit.

After saving it prints how high it thinks the camera is. If that's far off
from your tape measure, redo the lens step or check the click order.
"""

import argparse
import math
import time

import cv2
import numpy as np

import room as roomlib

WINDOW = "Keepy Up floor setup"
LABELS = ["1 back-left", "2 back-right", "3 front-right", "4 front-left"]  # as in the build guide


def text(frame, msg, row, color=(255, 255, 255), scale=0.8):
    y = 32 + row * 32
    cv2.putText(frame, msg, (12, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4)
    cv2.putText(frame, msg, (12, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)


def lens_step(args):
    cols, rows = (int(n) for n in args.board.lower().split("x"))
    square = args.square_mm / 1000
    grid = np.zeros((rows * cols, 3), np.float32)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square

    cap = roomlib.open_camera(args.source)
    object_points, image_points = [], []
    size = None
    last_grab = 0
    print("Show the checkerboard. SPACE = keep this view, C = calculate, Q = quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        size = (frame.shape[1], frame.shape[0])
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(
            gray, (cols, rows), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
        )
        view = frame.copy()
        if found:
            cv2.drawChessboardCorners(view, (cols, rows), corners, found)
        text(view, f"Views kept: {len(object_points)} (aim for 15)", 0, (0, 255, 0) if found else (0, 200, 255))
        text(view, "SPACE keep view   C calculate   Q quit", 1, (220, 220, 220))
        cv2.imshow(WINDOW, view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            return
        if key == ord(" ") and found and time.time() - last_grab > 0.5:
            corners = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
            )
            object_points.append(grid)
            image_points.append(corners)
            last_grab = time.time()
            print(f"Kept view {len(object_points)}")
        if key == ord("c"):
            if len(object_points) < 8:
                print("Keep at least 8 views first (15 is better).")
                continue
            break
    cap.release()
    cv2.destroyAllWindows()
    if len(object_points) < 8:
        return

    error, K, dist, _, _ = cv2.calibrateCamera(object_points, image_points, size, None, None)
    settings = roomlib.load_settings()
    settings["lens"] = {"image_size": list(size), "K": K.tolist(), "dist": dist.ravel().tolist(), "error_px": error}
    settings.pop("camera", None)  # floor step must be redone with the new lens model
    roomlib.save_settings(settings)
    quality = "good" if error < 0.8 else "OK" if error < 1.5 else "poor, try again with more varied views"
    print(f"Lens saved. Average error {error:.2f} px ({quality}).")
    print("Now run the floor step: python floor_setup.py --width 3 --depth 3")


def floor_step(args):
    settings = roomlib.load_settings()
    cap = roomlib.open_camera(args.source)
    clicks = []

    def on_click(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((x, y))
            print(f"Cross {LABELS[len(clicks) - 1]} at pixel ({x}, {y})")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW, on_click)
    print("Click the 4 tape crosses in order. U = undo, S = save, Q = quit.")
    frame = None
    while True:
        ok, new = cap.read()
        if ok:
            frame = new
        elif frame is None:
            raise SystemExit("No picture from the camera.")
        view = frame.copy()
        for i, (x, y) in enumerate(clicks):
            cv2.drawMarker(view, (x, y), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
            cv2.putText(view, str(i + 1), (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        if len(clicks) > 1:
            cv2.polylines(view, [np.array(clicks)], len(clicks) == 4, (0, 255, 0), 1)
        if len(clicks) < 4:
            text(view, f"Click cross {LABELS[len(clicks)]}", 0, (0, 255, 255))
        else:
            text(view, "All 4 clicked. Press S to save.", 0, (0, 255, 0))
        text(view, "U undo   S save   Q quit", 1, (220, 220, 220))
        cv2.imshow(WINDOW, view)
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        if key == ord("u") and clicks:
            clicks.pop()
        if key == ord("s") and len(clicks) == 4:
            if save_floor(settings, clicks, frame, args):
                break
    cap.release()
    cv2.destroyAllWindows()


def lens_width(f, w):
    return math.degrees(2 * math.atan(w / 2 / f))


def pick_lens(clicks, w, h, args):
    """Lens model when the checkerboard step hasn't been done."""
    dist = np.zeros(5)
    if args.camera_height:
        # Ceiling camera: find the lens that puts the camera at the measured height.
        f = (w / 2) / math.tan(math.radians(args.hfov) / 2)
        for _ in range(8):
            K = roomlib.guess_camera_matrix(w, h, lens_width(f, w))
            rvec, tvec, _ = roomlib.solve_camera_pose(clicks, args.width, args.depth, K, dist)
            R, _ = cv2.Rodrigues(rvec)
            f *= args.camera_height / abs((-R.T @ tvec).ravel()[2])
        return (roomlib.guess_camera_matrix(w, h, lens_width(f, w)), dist,
                f"lens worked out from your {args.camera_height:g} m camera height: about "
                f"{lens_width(f, w):.0f} degrees wide")

    f = roomlib.estimate_focal(clicks, args.width, args.depth, w, h)
    if f:
        K = roomlib.guess_camera_matrix(w, h, lens_width(f, w))
        rvec, _, _ = roomlib.solve_camera_pose(clicks, args.width, args.depth, K, dist)
        if roomlib.camera_tilt(rvec) >= 25:
            return K, dist, f"lens worked out from the crosses: about {lens_width(f, w):.0f} degrees wide"

    print("\nThe camera looks nearly straight down, so the crosses can't show how wide the lens is.\n"
          "Measure from the floor to the camera lens and run this again with --camera-height,\n"
          "for example: python floor_setup.py --camera-height 2.6\n")
    return (roomlib.guess_camera_matrix(w, h, args.hfov), dist,
            f"using a guessed lens ({args.hfov:g} degrees). Heights will be off until you use --camera-height")


def save_floor(settings, clicks, frame, args):
    h, w = frame.shape[:2]
    lens = settings.get("lens")
    if lens and tuple(lens["image_size"]) == (w, h):
        K, dist = np.array(lens["K"]), np.array(lens["dist"])
        lens_note = "using your lens calibration"
    else:
        if lens:
            print(f"Lens step was done at {lens['image_size']}, but the camera is now {w}x{h}. Ignoring it.")
        K, dist, lens_note = pick_lens(clicks, w, h, args)

    rvec, tvec, err = roomlib.solve_camera_pose(clicks, args.width, args.depth, K, dist)
    settings.update({
        "width": args.width,
        "depth": args.depth,
        "clicks": clicks,
        "camera": {
            "image_size": [w, h], "K": K.tolist(), "dist": np.ravel(dist).tolist(),
            "rvec": rvec.ravel().tolist(), "tvec": tvec.ravel().tolist(),
        },
    })
    settings.setdefault("robots", roomlib.DEFAULT_ROBOTS)
    settings.setdefault("balloon_hsv", roomlib.DEFAULT_BALLOON_HSV)
    room = roomlib.Room(settings)
    roomlib.save_settings(settings)

    # Save a picture with the floor grid drawn on, to check it lines up.
    check = frame.copy()
    step = 0.5
    for x in np.arange(0, args.width + 1e-6, step):
        cv2.line(check, room.to_pixel(x, 0), room.to_pixel(x, args.depth), (0, 255, 0), 1)
    for y in np.arange(0, args.depth + 1e-6, step):
        cv2.line(check, room.to_pixel(0, y), room.to_pixel(args.width, y), (0, 255, 0), 1)
    mid = args.width / 2
    cv2.line(check, room.to_pixel(mid, 0), room.to_pixel(mid, args.depth), (255, 120, 0), 3)
    out = roomlib.ROOM_FILE.with_name("floor_check.jpg")
    cv2.imwrite(str(out), check)

    print(f"\nSaved floor setup ({lens_note}).")
    print(f"Clicks fit within {err:.1f} px.")
    print(f"The camera seems to be {room.camera_height:.2f} m above the floor. Does that match your tape measure?")
    print(f"Check picture with a 50 cm grid saved to {out}. The thick line splits Cozmo's and MiP's halves.")
    return True


def main():
    p = argparse.ArgumentParser(description="Teach the tracker where the floor is.")
    p.add_argument("--source", default="0", help="Webcam number (0, 1, ...) or a video file")
    p.add_argument("--lens", action="store_true", help="Do the checkerboard lens step")
    p.add_argument("--board", default="9x6", help="Checkerboard inner corners, columns x rows")
    p.add_argument("--square-mm", type=float, default=25, help="Checkerboard square size in mm")
    p.add_argument("--width", type=float, default=3.0, help="Metres from cross 1 to cross 2")
    p.add_argument("--depth", type=float, default=3.0, help="Metres from cross 1 to cross 4")
    p.add_argument("--camera-height", type=float, default=None,
                   help="Measured height of the camera lens above the floor (m). Needed for a ceiling camera")
    p.add_argument("--hfov", type=float, default=100, help="Guessed lens angle if the lens step wasn't done")
    args = p.parse_args()
    lens_step(args) if args.lens else floor_step(args)


if __name__ == "__main__":
    main()
