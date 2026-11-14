"""
Robot drivers used by chase.py. Each one takes the same commands:

    await robot.drive(forward, turn)   forward in m/s (0 or more), turn in deg/s (+ = left / anticlockwise)
    await robot.stop()                 stop driving (a playing animation finishes)
    await robot.play(moment)           react to a soccer moment (see SOCCER_COZMO, SOCCER_MIP)

Cozmo  - PyCozmo. The laptop must be on Cozmo's own Wi-Fi network.
MiP    - Bluetooth, using the same commands as ../mip_test.py (already tested on your MiP).
DryRun - prints what it would do. Use it to test without robots.
"""

import asyncio
import glob
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for mip_test.py

# MiP's own speed dial runs 0-30. This caps it for the games (was 10; raised on
# 8 Nov for faster soccer: 16, 25, then 30 = MiP's top speed).
MAX_MIP_SPEED = 30
MOVE_PAUSE = 0.03 # s: wait after each move before the next (lets the camera catch up; was 0.05, 0.04)
# Turning (8 Nov: made faster). MiP turns on the spot in one go by the whole
# heading error, up to MAX_TURN_STEP, at TURN_SPEED (MiP's dial 0-24), then waits
# only as long as the turn takes instead of a fixed half second.
TURN_SPEED = 24       # MiP's top turn speed (was 20)
TURN_SETTLE = 0.10    # s: extra wait after a turn for the camera (was 0.15, 0.12)
MAX_TURN_STEP = 90   # degrees per turn command
TURN_RATE = 400      # degrees per second MiP turns at TURN_SPEED (estimate)
MAX_COZMO_SPEED = 0.20   # m/s: Cozmo's top speed (PyCozmo's MAX_WHEEL_SPEED is 200 mm/s)
# Longest single MiP move between camera checks. Faster = shorter moves, so a fast
# MiP still can't overshoot the centre line or the border between checks.
MAX_MOVE = 0.10   # m
# Firm rolls (12 Nov): in the 11 Nov test, at the slow dial setting (10) MiP couldn't
# beat its own backward lean and crept backwards instead of going for the balloon.
# Now it always rolls at dial 18 or more, in short hops scaled to the speed asked
# for (so it can't overshoot a near target), and waits between hops so that on
# average it covers the floor at the speed asked for, the same as Cozmo.
MIN_MIP_DIAL = 18     # MiP's speed dial (0-30): never roll weaker than this
MIN_HOP = 0.02        # m: shortest hop
HOP_TIME = 0.6        # s: a hop is the distance the asked speed covers in this time
MAX_HOP_GAP = 0.25    # s: longest wait between hops (MiP leans back if left too long)
RECONNECT_WAIT = 2    # s between Bluetooth reconnect tries


# Soccer moments (sent by soccer.py when they happen). Each robot reacts in its own
# voice, quietly. Cozmo: (animation or None, kind of voice clip from sounds/cozmo,
# taken from the Cozmo app). An animation is only used while play is stopped
# (goals, wins), because Cozmo stops driving while it plays. MiP: a built-in sound
# number, named as in the MiP app (WowWee's MiP developer kit numbering).
SOCCER_COZMO = {
    "play":        (None, "go"),                                   # "Go!" as play starts
    "out":         (None, "huh"),                                  # "Huh?"
    "robots_goal": ("anim_reacttoblock_success_01", "woohoo"),     # little cheer, "Woohoo!" (1.1 s)
    "people_goal": (None, "whoa"),                                 # "Whoa!"
    "robots_win":  ("anim_majorwin", "celebrate"),                 # victory dance (2.1 s)
    "people_win":  ("anim_greeting_happy_03", "wow"),              # happy for the people, "Wow!" (3.1 s)
    "new_game":    (None, "excited"),
}
SOCCER_MIP = {
    "play":        29,   # MIP_GO        "Go!"
    "out":         55,   # MIP_OHOH      "Oh-oh"
    "robots_goal": 81,   # MIP_YEEESSS   "Yesss!"
    "people_goal": 15,   # MIP_AWWW      "Awww"
    "robots_win":  56,   # MIP_OH_YEAH   "Oh yeah!"
    "people_win":  79,   # MIP_WOO       "Woo!"
    "new_game":    35,   # MIP_HI        "Hi!"
}
MIP_VOLUME = 2         # 0 = off, 7 = loudest (the voice app uses 4)
COZMO_VOLUME = round(65535 * MIP_VOLUME / 7)   # 0-65535: the same share of his range as MiP's (12 Nov; was 15000)
SOUNDS = Path(__file__).resolve().parent.parent / "sounds" / "cozmo"

# Cozmo's personality while playing (12 Nov). The Cozmo app normally runs his face,
# sounds and arm; our game replaces the app, so it does a little of that here.
# Faces for moments that have no animation (goals and wins play a full animation instead).
COZMO_FACES = {"play": "Happiness", "new_game": "Happiness", "out": "Surprise", "people_goal": "Sadness"}
FACE_SECONDS = 1.5               # how long an expression shows before his normal eyes come back
IDLE_SOUNDS = ("hum", "giggle", "vroom")
IDLE_EVERY = (15, 25)            # seconds between quiet idle sounds while he plays
CHASE_SOUNDS = ("vroom", "excited")
CHASE_EVERY = 10                 # seconds: at most one "going for it" sound this often
LIFT_DOWN, LIFT_UP = 32, 55      # mm: arm resting, and a small raise


class DryRun:
    def __init__(self, name):
        self.name = name
        self.last = None

    async def connect(self):
        print(f"[{self.name}] dry run, no robot connected")

    async def drive(self, forward, turn):
        cmd = f"drive forward {forward:.2f} m/s, turn {turn:+.0f} deg/s"
        if cmd != self.last:
            print(f"[{self.name}] {cmd}")
            self.last = cmd

    async def stop(self):
        if self.last != "stop":
            print(f"[{self.name}] stop")
            self.last = "stop"

    async def play(self, moment):
        what = SOCCER_COZMO.get(moment) if self.name == "cozmo" else SOCCER_MIP.get(moment)
        print(f"[{self.name}] plays '{moment}' ({what or 'nothing'})")
        self.last = None

    async def close(self):
        pass


class Cozmo:
    TRACK_M = 0.046  # distance between Cozmo's treads

    def __init__(self, name="cozmo"):
        self.name = name
        self.cli = None
        self.busy_until = 0  # an animation is playing until this time
        self.next_idle = time.monotonic() + random.uniform(*IDLE_EVERY)
        self.last_chase = float("-inf")   # when he last made a "going for it" sound (never yet)
        self.wheels = None       # last wheel speeds sent, so the same command isn't resent

    async def connect(self):
        import pycozmo
        from pycozmo import protocol_encoder

        def _connect():
            pycozmo.setup_basic_logging(log_level="WARNING", protocol_log_level="WARNING")
            cli = pycozmo.Client()               # his normal eyes: blinking and glancing around
            cli.start()
            cli.connect()
            cli.wait_for_robot()
            # Turn off Cozmo's own cliff stop: on 10 Nov his cliff sensor saw a "drop" on
            # the flat arena floor and locked his wheels all game. The floor is flat and
            # the camera keeps him inside the tape.
            cli.conn.send(protocol_encoder.EnableStopOnCliff(enable=False))
            cli.set_volume(COZMO_VOLUME)
            cli.load_anims()
            cli.set_lift_height(LIFT_DOWN)       # arm down while he drives
            return cli

        print(f"[{self.name}] connecting over Cozmo's Wi-Fi...")
        self.cli = await asyncio.to_thread(_connect)
        print(f"[{self.name}] connected")

    @property
    def animating(self):
        return time.monotonic() < self.busy_until

    def sound(self, kind):
        """Play a random clip of Cozmo's own voice of this kind ("go", "huh"...)."""
        clips = glob.glob(str(SOUNDS / f"{kind}_*.wav"))
        if self.cli and clips:
            self.cli.play_audio(random.choice(clips))

    def face(self, expression):
        """Show an expression (e.g. "Happiness") for FACE_SECONDS, then his normal eyes."""
        import numpy as np
        from PIL import Image
        from pycozmo import expressions, image_encoder, protocol_encoder, robot
        im = getattr(expressions, expression)().render()
        im = Image.fromarray(np.array(im)[::2])            # the screen uses every other row
        pkt = protocol_encoder.DisplayImage(image=bytes(image_encoder.ImageEncoder(im).encode()))
        for _ in range(int(FACE_SECONDS * robot.FRAME_RATE)):
            self.cli.anim_controller.display_image(pkt)    # one frame each

    def lift_bounce(self):
        """A small arm raise, back down a moment later."""
        self.cli.set_lift_height(LIFT_UP)
        asyncio.get_running_loop().call_later(0.6, self.cli.set_lift_height, LIFT_DOWN)

    def going_for_it(self):
        """He's set off after the balloon: a quiet sound and an arm lift, at most every
        CHASE_EVERY seconds. Idle sounds wait while he's chasing."""
        now = time.monotonic()
        if not self.cli or self.animating or now - self.last_chase < CHASE_EVERY:
            return
        self.last_chase = now
        self.next_idle = now + random.uniform(*IDLE_EVERY)
        self.sound(random.choice(CHASE_SOUNDS))
        self.lift_bounce()

    async def play(self, moment):
        if moment not in SOCCER_COZMO or not self.cli:
            return
        name, kind = SOCCER_COZMO[moment]
        if kind:
            self.sound(kind)      # queue the voice BEFORE the animation, or it waits for it
        if not name:
            if moment in COZMO_FACES:
                self.face(COZMO_FACES[moment])
            if COZMO_FACES.get(moment) == "Happiness":
                self.lift_bounce()
            return
        self.cli.stop_all_motors()
        self.wheels = None        # the animation moves his wheels: resend the next drive command
        self.cli.play_anim(name)  # queues the frames and returns straight away
        clip = self.cli._ppclips.get(name)
        length = max(clip.keyframes) / 1000 if clip and clip.keyframes else 1.5
        self.busy_until = time.monotonic() + length + 0.3

    async def drive(self, forward, turn):
        if self.animating:
            return  # let the animation finish before driving again
        if time.monotonic() > self.next_idle:          # now and then while playing: a quiet sound
            self.next_idle = time.monotonic() + random.uniform(*IDLE_EVERY)
            self.sound(random.choice(IDLE_SOUNDS))
            self.lift_bounce()
        forward = min(forward, MAX_COZMO_SPEED)
        # Turn rate (deg/s) to a speed difference between the two treads.
        diff = (turn * 3.14159 / 180) * self.TRACK_M / 2
        # mm/s, rounded to 5: only send when it changes (12 Nov: less Wi-Fi traffic, which
        # shares the Mac's radio with MiP's Bluetooth)
        wheels = (round((forward - diff) * 200) * 5, round((forward + diff) * 200) * 5)
        if wheels != self.wheels:
            self.wheels = wheels
            self.cli.drive_wheels(*wheels, lwheel_acc=300, rwheel_acc=300)

    async def stop(self):
        if self.cli and not self.animating and self.wheels != (0, 0):
            self.wheels = (0, 0)
            self.cli.drive_wheels(0, 0)    # wheels only, so an arm move can finish

    async def close(self):
        if self.cli:
            self.cli.cancel_anim()
            self.cli.stop_all_motors()
            self.cli.disconnect()
            self.cli.stop()


class MiP:
    """MiP only takes short moves (a turn of N degrees, or a roll for N seconds),
    so this turns the steady drive command into a short move every so often."""

    STEP = 0.5  # seconds between moves

    def __init__(self, name="mip"):
        self.name = name
        self.client = None
        self.send = None
        self.needs_reply = True
        self.busy_until = 0
        self.stopped = True
        self.last_ask = 0      # when we last asked MiP for its battery
        self.device = None
        self.loop = None
        self.lost = False      # Bluetooth dropped: reconnecting in the background
        self.failed = 0        # commands in a row that didn't go through
        self.closing = False
        self.reconnecting = None

    async def connect(self):
        import mip_test

        self.mip = mip_test
        self.loop = asyncio.get_running_loop()
        self.device = await mip_test.find_mip()
        if not self.device:
            raise SystemExit("MiP not found. Stand it up, switch it on, and try again.")
        await self._open()
        print(f"[{self.name}] connected", flush=True)

    async def _open(self):
        """Connect over Bluetooth and set MiP up (light, volume, battery reports)."""
        from bleak import BleakClient
        mip_test = self.mip
        self.client = BleakClient(self.device, disconnected_callback=self._on_disconnect)
        await self.client.connect()
        self.send = mip_test.find_characteristic(self.client, "ffe9")
        if not self.send:
            raise SystemExit("Connected to MiP but couldn't find its command channel. Run mip_test.py to check.")
        self.needs_reply = "write-without-response" not in self.send.properties
        await self.client.write_gatt_char(self.send, mip_test.chest_light(0, 150, 60), response=self.needs_reply)
        await self.client.write_gatt_char(self.send, bytes([0x15, MIP_VOLUME]), response=self.needs_reply)
        # Battery and posture: MiP answers ASK_STATUS on its 'ffe4' channel.
        receive = mip_test.find_characteristic(self.client, "ffe4")
        if receive:
            def on_message(_, data):
                status = mip_test.read_status(data)
                if status:
                    volts, upright = status
                    percent = max(0, min(100, round((volts - 4.0) / 2.4 * 100)))   # 4.0 V empty, 6.4 V full
                    extra = "" if upright == "upright" else f", {upright}"
                    print(f"[{self.name}] battery {percent}%{extra}", flush=True)
            try:
                await self.client.start_notify(receive, on_message)
                self.last_ask = 0
                await self.ask_status()
            except Exception:
                pass

    # ------------------------------------------------ Bluetooth drops (12 Nov)
    # On 11 Nov MiP's Bluetooth dropped mid-game twice and the error stopped the whole
    # robot program, which also lost Cozmo. Now MiP just stops, says so, and keeps
    # trying to reconnect in the background while the game (and Cozmo) carry on.
    def _on_disconnect(self, _client):
        if not self.closing and self.loop:
            self.loop.call_soon_threadsafe(self._lose, "the link dropped")

    def _lose(self, why):
        if self.lost or self.closing:
            return
        self.lost = True
        self.stopped, self.busy_until = True, 0
        print(f"[{self.name}] Bluetooth lost ({why}): reconnecting...", flush=True)
        self.reconnecting = asyncio.ensure_future(self._reconnect())

    async def _reconnect(self):
        tries = 0
        while not self.closing:
            tries += 1
            try:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
                if tries > 3 and tries % 3 == 1:       # not answering where it was: look for it again
                    found = await self.mip.find_mip()
                    if found:
                        self.device = found
                await self._open()
                self.lost, self.failed = False, 0
                self.stopped, self.busy_until = True, 0
                print(f"[{self.name}] reconnected", flush=True)
                return
            except asyncio.CancelledError:
                raise
            except BaseException as e:                  # includes SystemExit from _open
                if tries in (1, 5) or tries % 10 == 0:
                    print(f"[{self.name}] still reconnecting (try {tries}: {e.__class__.__name__})", flush=True)
                await asyncio.sleep(RECONNECT_WAIT)

    async def ask_status(self):
        """Ask MiP for its battery (the answer is printed when it arrives). At most once a minute."""
        if self.client and self.client.is_connected and time.monotonic() - self.last_ask > 60:
            self.last_ask = time.monotonic()
            await self._write(self.mip.ASK_STATUS)

    async def _write(self, command):
        if self.lost or not self.client:
            return
        try:
            await self.client.write_gatt_char(self.send, command, response=self.needs_reply)
            self.failed = 0
        except Exception:
            # Link still up: skip this command (12 Nov: don't hang up over one hiccup).
            # Down, or 3 failures in a row: reconnect instead of stopping the game.
            self.failed += 1
            if not self.client.is_connected:
                self._lose("the link dropped")
            elif self.failed >= 3:
                self._lose("commands kept failing")

    async def drive(self, forward, turn):
        now = time.monotonic()
        if now < self.busy_until:
            return
        await self.ask_status()
        if abs(turn) > 15 and forward < 0.02:
            degrees = min(MAX_TURN_STEP, abs(turn) * self.STEP)
            await self._write(self.mip.turn_left(degrees, TURN_SPEED) if turn > 0
                              else self.mip.turn_right(degrees, TURN_SPEED))
            self.stopped = False
            self.busy_until = now + degrees / (TURN_RATE * TURN_SPEED / 20) + TURN_SETTLE   # turn time + camera
            return
        elif forward > 0.02:
            speed = max(MIN_MIP_DIAL, min(MAX_MIP_SPEED, round(forward / 0.15 * 8)))  # MiP dial 0-30
            real = speed / 8 * 0.15                          # m/s this dial setting gives
            hop = min(MAX_MOVE, max(MIN_HOP, forward * HOP_TIME))   # metres this move
            roll = hop / real                                # seconds rolling
            wait = min(hop / forward, roll + MAX_HOP_GAP)    # so on average it goes at `forward`
            await self._write(self.mip.roll_forward(roll, speed))
            self.stopped = False
            self.busy_until = now + max(roll + MOVE_PAUSE, wait)
            return
        else:
            return
        self.stopped = False
        self.busy_until = now + self.STEP

    async def play(self, moment):
        """Say something in MiP's own voice. It keeps driving while it talks."""
        number = SOCCER_MIP.get(moment)
        if number and not self.lost and self.client and self.client.is_connected:
            await self._write(bytes([0x06, number, 0]))

    async def stop(self):
        if not self.stopped and not self.lost and self.client and self.client.is_connected:
            await self._write(self.mip.STOP)
        self.stopped = True
        self.busy_until = 0

    async def close(self):
        self.closing = True
        if self.reconnecting:
            self.reconnecting.cancel()
        if self.client and self.client.is_connected:
            self.stopped = False
            await self.stop()
            await self.client.disconnect()
