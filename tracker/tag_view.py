"""
Live camera view for checking the robots' AprilTags.

    python tag_view.py               # EMEET ceiling camera (0)
    python tag_view.py --source 1    # another camera

Found tags get a green outline, the robot's name and an arrow showing which way
it faces. The top line says whether Cozmo (tag 1) and MiP (tag 2) are seen.
Keys: Q quit. Nothing is saved.
"""
import argparse

import cv2
import numpy as np
from pupil_apriltags import Detector

NAMES = {1: "Cozmo", 2: "MiP"}
WINDOW = "Tag check"


def put(frame, msg, org, color, scale=1.0):
    cv2.putText(frame, msg, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, msg, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)


def main():
    p = argparse.ArgumentParser(description="Live view of the robots' AprilTags.")
    p.add_argument("--source", type=int, default=0)
    args = p.parse_args()
    cap = cv2.VideoCapture(args.source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    det = Detector(families="tag36h11", nthreads=4, quad_decimate=1.0, refine_edges=1, decode_sharpening=0.25)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 1280, 720)
    print(__doc__)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        seen = {}
        for d in det.detect(gray):
            c = d.corners.astype(int)
            good = d.decision_margin > 20
            color = (0, 230, 0) if good else (0, 200, 255)
            cv2.polylines(frame, [c.reshape(-1, 1, 2)], True, color, 4)
            centre = d.corners.mean(axis=0)
            front = (d.corners[0] + d.corners[1]) / 2
            tip = centre + (front - centre) * 2.5
            cv2.arrowedLine(frame, tuple(centre.astype(int)), tuple(tip.astype(int)), color, 4, tipLength=0.3)
            name = NAMES.get(d.tag_id, f"tag {d.tag_id}")
            put(frame, f"{name} ({d.decision_margin:.0f})", (c[:, 0].max() + 10, c[:, 1].min() + 10), color)
            if good:
                seen[d.tag_id] = True
        status = "   ".join(f"{n}: {'SEEN' if t in seen else 'not seen'}" for t, n in NAMES.items())
        put(frame, status, (20, 50), (0, 230, 0) if len(seen) == 2 else (0, 200, 255), 1.4)
        put(frame, "Q quit", (20, frame.shape[0] - 25), (220, 220, 220), 0.9)
        cv2.imshow(WINDOW, frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
