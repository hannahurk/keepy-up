# Keepy Up robot tracker

The webcam finds each robot's AprilTag and the balloon, then streams their
positions over a WebSocket. Two games listen to that stream:

- **Keepy uppy** (`chase.py`): Cozmo and MiP follow the floor spot under the balloon.
- **Floor soccer** (`soccer.py`): people roll the balloon along the floor toward the
  robots' goal; goals are spotted and the score kept automatically.

Both games use the same taped play area (the pink area in `tape_guide.py`), and the
robots always stay inside it.

## One-time setup

```bash
cd keepy-up/tracker
source .venv/bin/activate        # already created; or: python3 -m venv .venv && pip install -r requirements.txt
python make_tags.py              # makes tags.svg: Cozmo 4 cm, MiP 5 cm
```

Print `tags.svg` landscape at 100% scale and check that the 10 cm line measures 10 cm.
Cut along the dashed line, keeping the white border. Stick tag 1 flat on Cozmo's back
(behind its head, clear of the lift) and tag 2 flat on top of MiP's head, facing straight
up, with the FRONT arrow toward the robot's front. The tag sizes suit a camera about 2 m up;
for the corner stand, 3–4 m away, print bigger ones with `python make_tags.py --size-cm 8`.

**Coloured tape instead of tags (what works with the EMEET on a 6 ft ceiling).** From the
ceiling, 4–5 cm tags are only about 20–30 pixels wide, too small to read reliably. Coloured
tape works better: put a **green** patch (3–4 cm) on top of each robot, plus a smaller
piece at the **front**: **pink for Cozmo**, **blue for MiP**. The front piece says which
robot it is and which way it faces. Avoid yellow and orange on the robots (too close to the
yellow balloon). The tracker uses tape whenever it can't read a tag (`--no-tape` turns this off).
`python tag_view.py` shows a live view for checking tags.

When the balloon floats right over a robot, the camera can't see the robot. The tracker
keeps that robot's last spot for up to 2 seconds, marked `"hidden": true`, and chase.py
holds the robot still until it's seen again.

### Robot sizes

The tracker knows each robot's size, so it can:
- report the robot's middle, not just where its tag is
- draw a box around each robot in the preview, to check the sizes look right
- ignore the robots when looking for the balloon, so a coloured part on a robot
  is never mistaken for it

The sizes are estimates. Measure your robots with a ruler and change them in
`room.json` (made by the floor step), under `"robots"`, in metres:

| Setting | Cozmo (tag 1) | MiP (tag 2) | What it is |
|---|---|---|---|
| `length` | 0.10 | 0.09 | front to back (Cozmo: include the lift arms) |
| `width` | 0.06 | 0.11 | side to side (MiP: wheel to wheel) |
| `height` | 0.075 | 0.20 | floor to the top |
| `tag_height` | 0.07 | 0.20 | floor to the tag |
| `tag_forward` | -0.02 | 0.0 | how far the tag is in front of the robot's middle (negative = behind) |

If the box in the preview is bigger or smaller than the robot, or off to one
side, adjust these numbers.

## Each time the camera is set up

```bash
python floor_setup.py --lens                    # optional, once per camera: checkerboard, ~15 views
python tape_guide.py --source 0 --camera-height 1.98   # ceiling camera: shows where to tape the crosses and rest spots
python floor_setup.py --width 3 --depth 3       # corner stand: click crosses 1 back-left, 2 back-right, 3 front-right, 4 front-left
python floor_setup.py --source 1 --width 2 --depth 2 --camera-height 2.6   # ceiling camera looking straight down
```

For a ceiling camera, measure from the floor to the camera lens and pass it as
`--camera-height`: looking straight down, the crosses alone can't show how wide
the lens is. For the corner stand, check the printed camera height against your
tape measure. Either way, look at `floor_check.jpg`: the 50 cm grid should sit on the tape.

Then measure the balloon once: start `tracker.py`, rest the balloon on the floor
in view, and press **F**. Its size is saved, so heights are right.

## Taping the floor

```bash
python tape_guide.py --source 0 --camera-height 1.98                  # keepy uppy layout
python tape_guide.py --source 0 --camera-height 1.98 --game soccer    # floor soccer layout (or press G)
```

It draws on the live camera view where to tape the 4 crosses (1 back-left, 2 back-right,
3 front-right, 4 front-left, as in the build guide; "back" is the top of the picture), the
robots' rest spots (inside the play area, in the back corners) and, for soccer, the goal
posts (72 cm goals at the left and right ends, as taped). One set of crosses works
for both games. When you quit it prints exact measurements from cross 1.

## Playing keepy uppy

Terminal 1 starts the tracker:

```bash
python tracker.py --tune          # first time: drag sliders until only the balloon is white, press S
                                  # (starts set for a yellow balloon)
python tracker.py                 # after that
```

Terminal 2 starts the robots:

```bash
python chase.py --dry-run         # practise with no robots moving
python chase.py                   # Cozmo + MiP
```

Ctrl+C in terminal 2 stops the robots.

## Playing floor soccer

It plays like air hockey: 2 people against Cozmo and MiP, each team defending its own
goal. People stay on their own side of the centre line. The robots may cross it and
go up to halfway into the people's half, but never into the half by the people's goal.

**The easy way:** double-click **Keepy Up Soccer** on the Desktop. It runs
`play_soccer.py`, which asks which robots (a = both, c = Cozmo, m = MiP), shows a
checklist, checks Cozmo's Wi-Fi, then starts the camera, the scoreboard and the robots
(`chase.py --game soccer`, both at 0.20 m/s, Cozmo's top speed). With Cozmo playing, he
starts on his charger and the robots wait until he's moved into the arena. Every game,
first or new, begins with the start sequence: "Get ready..." on the scoreboard, then 1, 2, 3
(a beep each) and START!; the robots and scoreboard wait until START!. Say "start" to start
and "stop" to stop (offline, those two words only, nothing saved), or use the keys: p pause /
carry on, n new game, q stop. Only one game window can be open at a time. Logs go to
`keepy-up/logs/`. No internet needed. `--dry-run` tries it with no
robots moving; `--no-voice` turns the microphone off.

The robots: the arena is cut in two the long way. Cozmo has the back strip, MiP the
front, each from the robots' goal up to the halfway limit in the people's half (`guard.py`).
A robot pushes the balloon at the people's goal when it's in its strip and within reach,
and never enters the other's strip. Both react quietly in their own voices to goals,
"Out!", wins and a new game (`soccer.py` sends each moment to `chase.py` on this Mac).
Cozmo's face, expressions, arm and quiet idle and "vroom" sounds also play. Sound effects
play on the Mac's speakers (`keepy-up/sounds/`): the countdown, start, every goal, the win,
a near miss at a goal, a robot's missed push, and stop.

**By hand**, in separate terminals: terminal 1 runs the tracker as above, terminal 2 the referee and scoreboard,
and terminal 3 the robots (`python chase.py --game soccer --max-speed 0.20 --max-turn 180`):

```bash
python soccer.py                          # robots defend the right goal, people the left
python soccer.py --robots-defend left
```

1. Serve ("People's balloon" / "Robot's balloon" on the scoreboard): nobody kicks. People
   push the balloon with their hands, robots with their bodies. A new game always starts
   with the people's balloon, served from their side toward the robots. After a goal, the
   team that scored gets the balloon and serves from their own side, toward the other team
   (for the robot's balloon, a person puts the balloon down on the robots' side).
   After a second on the floor on that side, the scoreboard says "Play!".
2. A goal counts as soon as the balloon, on the floor, touches the pink goal line between
   the two pink posts (or when it rolls out of view through the goal mouth). A balloon in the air doesn't count.
3. After a goal, or if the balloon leaves the play area elsewhere, the next serve
   restarts play. After the balloon goes out, the team whose side it went out on
   serves. The first team to 5 goals wins; press n in the game window for a new game.

Scoreboard keys (only when you run `soccer.py` by hand): SPACE pause, R new game,
K serve again, Q quit. Started from the game window (`--no-keys`), the scoreboard ignores
the keyboard, so typing while it's in front can't reset or pause the game.

## Message format (ws://localhost:8765, about 15 per second)

```json
{"type": "positions", "t": 1730412345.12, "room": {"width": 3, "depth": 3, "clockwise": true},
 "robots": {"cozmo": {"id": 1, "x": 0.8, "y": 1.2, "heading": 90.0,
                      "length": 0.10, "width": 0.06, "height": 0.075, "seen": true, "age": 0.03},
            "mip":   {"id": 2, "x": 2.1, "y": 1.9, "heading": 270.0,
                      "length": 0.09, "width": 0.11, "height": 0.20, "seen": true, "age": 0.03}},
 "balloon": {"x": 1.4, "y": 1.6, "height": 1.1, "seen": true, "age": 0.03}}
```

Metres from tape cross 1 (back-left, as in the build guide). x runs toward cross 2 and y toward cross 4.
A robot's x and y are its middle; length, width and height are its size.
Heading 0 means facing cross 2 and 90 means facing cross 4 (the front). With the guide's
cross order, heading goes up clockwise seen from above, so `"clockwise": true`; anything
that steers a robot must flip its turn direction when that's true.
`seen` goes false after half a second without a sighting.

## Not done yet

- Children aren't tracked, so robots don't yet slow or stop near children. Keep a grown-up watching.
- No-go zones and calm-spot resting aren't used yet. The waiting robot just stops where it is.
- Keepy uppy doesn't yet have the voice commands, robot sounds or game screen that
  floor soccer has.
- Rest spots (keepy uppy) and the soccer spots either side of the robots' goal are marked on the floor,
  but robots don't drive to them yet.
- With a low ceiling camera, a balloon in the air can hide a robot. The tracker keeps
  its last spot for 2 seconds and the robot holds still; after that it stops until
  it's visible again.
