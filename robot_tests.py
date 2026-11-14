"""
Keepy Up: three start/stop tests for Cozmo and MiP.

In every test both robots do the same thing: roll around the floor in a
random pattern (roll forward, turn left or right, now and then a spin
or a back-up) until you say "stop" or 30 seconds pass. Each does it in its own style,
using behaviors from its app:

  Starts     Cozmo: "Go!" and an excited face      MiP: "Hi! Play! Go go go!", glows green
  Rolling    Cozmo: "vroom", happy humming, and    MiP: "Wheee!", "Woo!", "Whoah!",
             a giggle, laugh or "Woohoo!"               "Oh yeah!" now and then
             every few turns
  Stopped    Cozmo: "Huh?"                         MiP: "Oh-oh", glows amber
  Quit (q)   Cozmo: yawns and falls asleep         MiP: "Bye", light off

Both robots use their own voices. MiP's sounds are built into MiP.
Cozmo's are clips from the Cozmo app, in sounds/cozmo (see README.txt there).

  Test 1  python3 robot_tests.py clap    Clap once     -> both robots roll
                                         Say "stop"    -> both robots freeze
  Test 2  python3 robot_tests.py start   Say "start" or "let's play"
                                                       -> both robots roll
  Test 3  python3 robot_tests.py stop    Say "start", wait, say "stop"
                                                       -> both robots freeze

In every test, "stop" or the space bar stops the robots. Press q to quit.
While the robots are rolling, saying "start" also stops them: some
accents' "stop" sounds like "start" to the voice model, so it's safer.
Add --no-cozmo, --no-mip or --no-robots to leave a robot out.

EDGES: Cozmo's own cliff sensor is switched on. If Cozmo reaches the edge
of a table its wheels stop by themselves, it says "Whoa!", backs up and
turns round. MiP has NO edge sensor: only ever run MiP on the floor.

SAFETY: these tests don't use the webcam, so the robots can't see.
Give each robot about 2 x 2 m of clear floor, keep children out of the
area, and keep a hand near the space bar.

Setup is the same as voice_start.py (see the top of that file).
"""

import argparse
import asyncio
import json
import queue
import random
import time

import numpy as np

import voice_start as vs
from voice_start import BLUE, GREEN, GREY, RESET, YELLOW, banner, say

ROLL_SECONDS = 30            # robots stop by themselves after this
RATE = 16000                 # microphone samples per second
BLOCK = 1600                 # 0.1 s of sound per block
FRAME = 320                  # 0.02 s frames for clap detection


# ---------------------------------------------------------------------
# Rolling around: the same action for both robots in every test
# ---------------------------------------------------------------------

# MiP's built-in sounds. Numbers from WowWee's public MiP developer kit
# (MipCommandValues.h); the names match the MiP app's own data files.
MIP_GOGOGO, MIP_WHEEE, MIP_OHOH, MIP_BYE = 30, 76, 55, 19
MIP_HI, MIP_PLAY = 35, 60                                        # "Hi!", "Play!"
MIP_WOO, MIP_WHOAH, MIP_OH_YEAH = 79, 78, 56                     # "Woo!", "Whoah!", "Oh yeah!"
MIP_ROLLING_WORDS = [MIP_WHEEE, MIP_WOO, MIP_WHOAH, MIP_OH_YEAH]
MIP_VOLUME = 4                                                   # 0 = off, 7 = loudest


MIP_SPEED = 20               # forward speed, 0-30 (was 6). Higher can tip MiP over
MIP_TURN_SPEED = 16          # turning speed, 0-24 (was 8)


def mip_sound(number):
    return bytes([0x06, number, 0])


def mip_backward(seconds, speed):
    """Roll backward for a short time (WowWee command 0x72)."""
    return bytes([0x72, speed, max(0, min(255, round(seconds / 0.007)))])


def mip_turn_time(degrees):
    """Roughly how long a turn takes at MIP_TURN_SPEED, plus a little settling."""
    return degrees / 200 + 0.3


class RollingMiP(vs.MiP):
    async def connect(self):
        ok = await super().connect()
        if ok:
            await self._send(bytes([0x15, MIP_VOLUME]))
        return ok

    async def _hello(self):
        m = self.m
        await self._send(m.chest_light(0, 150, 60))                 # green: rolling
        for word in (MIP_HI, MIP_PLAY, MIP_GOGOGO):                 # "Hi! Play! Go go go!"
            await self._send(mip_sound(word))
            await asyncio.sleep(0.9)
        end = time.monotonic() + ROLL_SECONDS
        lap = 0
        while time.monotonic() < end:
            if lap % 2 == 1:                                        # "Wheee!", "Woo!", "Whoah!"...
                await self._send(mip_sound(random.choice(MIP_ROLLING_WORDS)))
            await self._send(m.roll_forward(1.75, speed=MIP_SPEED))  # longest single roll
            await asyncio.sleep(1.8)
            if lap % 4 == 3:                                        # now and then: full spin
                await self._send(m.turn_left(360, speed=MIP_TURN_SPEED))
                await asyncio.sleep(mip_turn_time(360))
            elif random.random() < 0.3:                             # sometimes: quick back-up
                await self._send(mip_backward(0.6, speed=MIP_SPEED - 5))
                await asyncio.sleep(0.7)
            degrees = random.choice([90, 120, 150, 180])
            turn = random.choice([m.turn_left, m.turn_right])
            await self._send(turn(degrees, speed=MIP_TURN_SPEED))
            await asyncio.sleep(mip_turn_time(degrees))
            lap += 1
        await self._send(m.STOP)
        await self._send(m.chest_light(160, 100, 0))               # amber: stopped

    async def stop(self):
        self._cancel()
        await self._send(self.m.STOP)                               # wheels first
        await self._send(mip_sound(MIP_OHOH))                       # "Oh-oh"
        await self._send(self.m.chest_light(160, 100, 0))           # amber: stopped

    async def all_done(self):
        self._cancel()
        await self._send(self.m.STOP)
        await self._send(mip_sound(MIP_BYE))                        # "Bye"
        await asyncio.sleep(1.2)
        await self._send(self.m.chest_light(0, 0, 0))              # light off
        await self.client.disconnect()


# Cozmo's own animations, from the files the Cozmo app uses (PyCozmo keeps
# a copy in ~/.pycozmo). The explorer "driving" ones only change Cozmo's
# face and sounds, so they play on top of the rolling.
COZMO_SET_OFF = ["anim_explorer_driving01_start_01", "anim_explorer_driving01_start_02"]    # 0.9 s
COZMO_DRIVING = ["anim_explorer_driving01_loop_01", "anim_explorer_driving01_loop_02",
                 "anim_explorer_driving01_loop_03"]                                          # 1.9 s
COZMO_HUH = "anim_reacttocliff_huh_01"                                                       # 0.5 s
COZMO_SLEEP = "anim_gotosleep_getin_01"                                                      # 5.3 s
# Happy moments: Cozmo's own giggle, cheers and celebrations (name, seconds, voice).
# These move Cozmo's wheels and lift themselves, so it stops driving first.
# Each comes with a matching clip of Cozmo's voice (sounds/cozmo/<kind>_NN.wav).
COZMO_HAPPY = [("anim_poked_giggle", 0.9, "giggle"),
               ("anim_reacttoblock_success_01", 1.1, "woohoo"),
               ("anim_majorwin", 2.1, "celebrate"),
               ("anim_reacttoblock_happydetermined_01", 1.2, "excited"),
               ("anim_pyramid_reacttocube_happy_high_01", 2.1, "laugh"),
               ("anim_greeting_happy_03", 3.1, "wow")]
COZMO_SPEED = 120            # mm per second going forward (was 50; top speed about 200)
COZMO_VOLUME = 30000                                             # 0-65535, about medium


class RollingCozmo(vs.Cozmo):
    anims = False

    def send(self, command):
        super().send(command)
        if command in ("stop", "done") and self.cli and self.anims:
            self.cli.cancel_anim()                                  # cut the driving sounds now

    def _move(self, cli, left, right, seconds):
        """Drive the wheels (or stand still) for a while. If Cozmo reaches an
        edge it backs away first. Returns False if told to stop."""
        if left or right:
            cli.drive_wheels(lwheel_speed=left, rwheel_speed=right)
        else:
            cli.stop_all_motors()
        if not self._wait(seconds):
            return False
        if self.edge.is_set():
            return self._back_away(cli)
        return True

    def _back_away(self, cli):
        """Cozmo saw an edge: its wheels have already stopped by themselves.
        Say "Whoa!", back up, turn round and carry on. False if told to stop."""
        cli.stop_all_motors()
        vs.say(f"{YELLOW}Cozmo found an edge: backing away from it{RESET}")
        self._perform(cli, "whoa", COZMO_HUH)
        cli.drive_wheels(lwheel_speed=-60, rwheel_speed=-60)        # back up about 5 cm
        if self.halt.wait(0.8):
            return False
        cli.drive_wheels(lwheel_speed=100, rwheel_speed=-100)       # turn round
        if self.halt.wait(1.6):
            return False
        cli.stop_all_motors()
        self.edge.clear()
        return True

    def _perform(self, cli, sound=None, anim=None):
        """Cozmo's voice clip plus an animation, starting together. PyCozmo
        plays animations silently, so the voice comes from sounds/cozmo.
        The sound has to be queued before the animation or it waits for it."""
        if self.anims:
            cli.cancel_anim()                                       # clear anything still queued
        if sound:
            vs.cozmo_sound(cli, sound)
        if anim:
            self._anim(cli, anim)

    def _anim(self, cli, name):
        """Play one of Cozmo's animations; if they didn't load, carry on without."""
        if self.anims:
            try:
                cli.play_anim(name)
            except Exception:
                pass

    def _hello(self, cli, robot):
        cli.set_head_angle(0.0)
        self._perform(cli, "go", random.choice(COZMO_SET_OFF))      # "Go!" and an excited face
        if not self.anims:
            cli.display_image(self._face("happy"))
        if not self._wait(1.0):
            return
        end = time.monotonic() + ROLL_SECONDS
        lap = 0
        while time.monotonic() < end:
            if self.edge.is_set() and not self._back_away(cli):
                return
            sound = "vroom" if lap == 0 else ("hum" if lap % 2 else None)   # "vroom", then happy humming
            self._perform(cli, sound, random.choice(COZMO_DRIVING))   # driving face
            if not self._move(cli, COZMO_SPEED, COZMO_SPEED, random.uniform(1.5, 2.5)):
                return                                              # longer runs forward
            if lap % 3 == 2 and self.anims:                         # happy moment
                cli.stop_all_motors()
                name, seconds, sound = random.choice(COZMO_HAPPY)
                self._perform(cli, sound, name)
                if not self._move(cli, 0, 0, seconds + 0.3):
                    return
            elif lap % 5 == 4:                                      # big spin
                if not self._move(cli, 150, -150, 2.0):
                    return
            else:                                                   # turn left or right
                turn = random.choice([1, -1]) * 100
                if not self._move(cli, turn, -turn, random.uniform(0.6, 1.2)):
                    return
            if not self._move(cli, 0, 0, 0.1):
                return
            lap += 1
        cli.stop_all_motors()

    def _run(self):
        try:
            import pycozmo
            from pycozmo import robot
            with pycozmo.connect(enable_procedural_face=False, log_level="WARNING",
                                 protocol_log_level="WARNING") as cli:
                self.cli = cli
                self._guard_edges(cli)                              # stop at table edges
                try:
                    cli.load_anims()
                    self.anims = True
                except Exception as e:
                    vs.say(f"{YELLOW}Cozmo's animations didn't load ({e}). "
                           f"Run: pycozmo_resources.py download{RESET}")
                cli.set_volume(COZMO_VOLUME)
                cli.set_head_angle(0.0)
                cli.display_image(self._face("calm"))
                self.connected.set()
                while True:
                    command = self.commands.get()
                    if command == "start":
                        self._hello(cli, robot)
                    elif command == "stop":
                        cli.stop_all_motors()                       # wheels first
                        self._perform(cli, "huh", COZMO_HUH)        # quick "huh?"
                        if not self.anims:
                            cli.display_image(self._face("calm"))
                    elif command == "done":
                        cli.stop_all_motors()
                        cli.set_lift_height(robot.MIN_LIFT_HEIGHT.mm)
                        if self.anims:
                            self._perform(cli, "sleep", COZMO_SLEEP)  # yawns, falls asleep
                            time.sleep(5.5)
                        else:
                            cli.set_head_angle(robot.MIN_HEAD_ANGLE.radians)
                            cli.display_image(self._face("sleepy"))
                            time.sleep(1.5)
                        break
        except Exception as e:
            self.error = e
            self.connected.set()
        finally:
            self.finished.set()


async def connect_robots(args):
    use_mip = not (args.no_robots or args.no_mip)
    use_cozmo = not (args.no_robots or args.no_cozmo)

    cozmo = None
    if use_cozmo:
        say("Connecting to Cozmo over its Wi-Fi...")
        cozmo = RollingCozmo()
        cozmo.start()

    mip = None
    if use_mip:
        mip = RollingMiP()
        try:
            if not await mip.connect():
                mip = None
        except Exception as e:
            say(f"{YELLOW}MiP didn't connect: {e}{RESET}")
            mip = None
        if mip:
            say(f"{GREEN}MiP connected{RESET}")

    if cozmo:
        await asyncio.get_running_loop().run_in_executor(None, cozmo.connected.wait, 20)
        if cozmo.error or not cozmo.connected.is_set():
            say(f"{YELLOW}Cozmo didn't connect: {cozmo.error or 'timed out'}. "
                f"Is the laptop on Cozmo's Wi-Fi?{RESET}")
            cozmo = None
        else:
            say(f"{GREEN}Cozmo connected{RESET}")
    return cozmo, mip


# ---------------------------------------------------------------------
# Clap detection: a short, sharp sound much louder than the room
# ---------------------------------------------------------------------

class ClapDetector:
    """A clap jumps far above the room's normal loudness and dies away
    within about 0.15 s. Talking and footsteps rise more slowly or last
    longer, so they don't count."""

    def __init__(self, room_level, sensitivity=1.0):
        self.room = max(room_level, 0.002)
        self.sensitivity = sensitivity
        self.peak = 0.0               # loudness of a possible clap
        self.frames_since_peak = None
        self.quiet_until = 0.0        # ignore echoes just after a clap

    def threshold(self):
        return max(0.05, self.room * 8) / self.sensitivity

    def feed(self, frame, now):
        """frame: 0.02 s of sound as floats -1..1. Returns True on a clap."""
        level = float(np.sqrt(np.mean(frame ** 2)))

        if self.frames_since_peak is not None:                     # watching a possible clap
            self.frames_since_peak += 1
            if level > self.peak:
                self.peak, self.frames_since_peak = level, 0
            elif level < self.peak * 0.3:                          # died away fast: a clap
                self.frames_since_peak = None
                self.quiet_until = now + 0.8
                return True
            elif self.frames_since_peak > 8:                       # lasted too long: not a clap
                self.frames_since_peak = None
            return False

        if now >= self.quiet_until and level > self.threshold():
            self.peak, self.frames_since_peak = level, 0
        elif level < self.threshold() / 2:                         # slowly follow the room
            self.room = 0.98 * self.room + 0.02 * max(level, 0.002)
        return False


def loudness_bar(level, threshold, width=40):
    full = min(width, int(level / (threshold * 1.5) * width))
    mark = min(width - 1, int(width / 1.5))
    bar = "".join("#" if i < full else ("|" if i == mark else " ") for i in range(width))
    colour = GREEN if level >= threshold else GREY
    return f"{colour}Loudness [{bar}]{RESET}  (a clap must pass the | line and be short)"


# ---------------------------------------------------------------------
# Words: offline listening for just "start" and "stop"
# ---------------------------------------------------------------------

def make_listener():
    try:                                    # python.org Python on Mac has no web certificates
        import os
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    from vosk import KaldiRecognizer, Model, SetLogLevel
    say("Loading voice model...")
    SetLogLevel(-1)
    model = Model(lang="en-us")
    # Only these two words. Tested with 8 voices in quiet and noisy rooms:
    # every "stop" was caught, and "stop" never started the robots.
    return KaldiRecognizer(model, RATE, json.dumps(["start", "let's play", "stop", "[unk]"]))


def words_in(recogniser, chunk):
    """Returns (words, finished). Partial words come while someone is
    still speaking; finished ones come once they pause."""
    if recogniser.AcceptWaveform(chunk):
        text, finished = json.loads(recogniser.Result()).get("text", ""), True
    else:
        text, finished = json.loads(recogniser.PartialResult()).get("partial", ""), False
    return text.replace("[unk]", "").split(), finished


# ---------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------

INTRO = {
    "clap":  ("TEST 1: CLAP TO START", 'Clap once, loudly, to start both robots, then say "stop".'),
    "start": ("TEST 2: SAY START",      'Say "start" or "let\'s play" to start both robots.'),
    "stop":  ("TEST 3: SAY STOP",       'Say "start" or "let\'s play", let them roll a few seconds, then say "stop".'),
}


async def main(args):
    import sounddevice as sd

    cozmo, mip = await connect_robots(args)
    recogniser = make_listener()
    loop = asyncio.get_running_loop()

    audio = queue.Queue()

    def on_audio(data, frames, when, status):
        audio.put((time.monotonic(), bytes(data)))

    mic = sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16",
                            channels=1, callback=on_audio)
    mic.start()

    def next_audio():
        try:
            return audio.get(timeout=0.2)
        except queue.Empty:
            return None

    clap = None
    if args.test == "clap":
        say("Measuring how loud the room is. Stay quiet for 2 seconds...")
        levels, end = [], time.monotonic() + 2
        while time.monotonic() < end:
            item = await loop.run_in_executor(None, next_audio)
            if item:
                s = np.frombuffer(item[1], dtype=np.int16).astype(np.float32) / 32768
                levels += [float(np.sqrt(np.mean(f ** 2))) for f in s.reshape(-1, FRAME)]
        room = float(np.median(levels)) if levels else 0.005
        clap = ClapDetector(room, args.sensitivity)
        say(f"{GREY}Room level {room:.3f}, clap needs over {clap.threshold():.3f}{RESET}")

    state = {"rolling_until": 0.0, "quit": False}
    robots = " + ".join(n for n, r in (("Cozmo", cozmo), ("MiP", mip)) if r) or "no robots"
    title, how = INTRO[args.test]
    banner(f"{title}  ({robots})", BLUE)
    say(f"{how}\n{GREY}\"Stop\" or space bar stops them. q quits.{RESET}\n")

    def rolling():
        return state["rolling_until"] is not None and time.monotonic() < state["rolling_until"]

    async def start_robots(what):
        if rolling():
            return
        if cozmo:
            cozmo.send("start")
        if mip:
            mip.start_game()
        state["rolling_until"] = time.monotonic() + ROLL_SECONDS
        if args.test == "clap":
            banner(f"PASS: heard the {what}, robots are rolling  ->  now say \"stop\"", GREEN)
        elif args.test == "stop":
            banner(f"ROLLING  (heard {what})  ->  now say \"stop\"", GREEN)
        else:
            banner(f"PASS: heard {what}, robots are rolling", GREEN)

    async def stop_robots(what):
        if not rolling():
            return
        state["rolling_until"] = None          # None = stopped by someone, not the time limit
        if cozmo:
            cozmo.send("stop")
        if mip:
            await mip.stop()
        if args.test in ("clap", "stop") and what == "your voice":
            banner('PASS: heard "stop", robots stopped', GREEN)
        else:
            banner(f"Robots stopped ({what})", YELLOW)
        say(f"{GREY}Try again, or press q to finish.{RESET}")

    def on_key(key):
        if key == " ":
            asyncio.ensure_future(stop_robots("space bar"))
        elif key in ("q", "Q"):
            state["quit"] = True

    restore_terminal = vs.watch_keyboard(loop, on_key)
    ignore_rest = False

    try:
        while not state["quit"]:
            limit = state["rolling_until"]
            if limit and time.monotonic() >= limit:
                state["rolling_until"] = 0.0
                say(f"{YELLOW}{ROLL_SECONDS} s limit reached: robots stopped by themselves.{RESET}")

            item = await loop.run_in_executor(None, next_audio)
            if item is None:
                continue
            heard_at, chunk = item

            if clap:
                sound = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768
                loudest = 0.0
                for i, frame in enumerate(sound.reshape(-1, FRAME)):
                    loudest = max(loudest, float(np.sqrt(np.mean(frame ** 2))))
                    if clap.feed(frame, heard_at + i * FRAME / RATE):
                        await start_robots("clap")
                print(f"\r\033[K{loudness_bar(loudest, clap.threshold())}", end="", flush=True)

            # "stop" acts as soon as it's heard, even mid-word, so the robots
            # freeze fast. Some accents' "stop" sounds like "start" to the
            # voice model, so while the robots are rolling EITHER word stops
            # them. "start" only starts them once the word is finished.
            words, finished = words_in(recogniser, chunk)
            if "stop" in words or (rolling() and "start" in words):
                await stop_robots("your voice")
                ignore_rest = True             # the rest of what stopped them can't restart them
            elif finished and ("start" in words or "play" in words) and not ignore_rest and args.test in ("start", "stop"):
                await start_robots('"start"' if "start" in words else '"let\'s play"')
            if finished:
                ignore_rest = False
    finally:
        mic.stop()
        if restore_terminal:
            restore_terminal()
        state["rolling_until"] = 0.0
        say("Finishing: robots going to sleep...")
        if cozmo:
            cozmo.send("done")
        if mip:
            await mip.all_done()
        if cozmo:
            await loop.run_in_executor(None, cozmo.finished.wait, 8)
    say("Test finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keepy Up start/stop tests")
    parser.add_argument("test", choices=["clap", "start", "stop"], help="which test to run")
    parser.add_argument("--sensitivity", type=float, default=1.0,
                        help="clap test: above 1 hears quieter claps, below 1 ignores more noise")
    parser.add_argument("--no-robots", action="store_true", help="no robots, just the listening")
    parser.add_argument("--no-cozmo", action="store_true", help="skip Cozmo")
    parser.add_argument("--no-mip", action="store_true", help="skip MiP")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
