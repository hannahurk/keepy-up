"""
Keepy Up: voice start demo with Cozmo and MiP.

Listens to the room (offline, nothing recorded) for three phrases:

  "Let's play"  -> three soft beeps, then both robots say hello
                  and Cozmo shouts "Woohoo!"
                              (MiP glows and wiggles, Cozmo looks up,
                              bounces its lift and shows happy eyes)
  "Stop"                   -> both robots freeze straight away
  "All done"               -> robots go to sleep and the program ends

Space bar also pauses (like the big pause button). Press q to quit.

---------------------------------------------------------------------
Setup (once)
---------------------------------------------------------------------
  pip3 install vosk sounddevice numpy bleak pycozmo pillow certifi
  python3 -m pycozmo.resources download      # only needed once, for Cozmo

The first run downloads the small English Vosk voice model (~40 MB)
into ~/.cache/vosk. After that it works with the internet off.

macOS will ask to let Terminal use the microphone and Bluetooth: allow both.

---------------------------------------------------------------------
Run it in three steps
---------------------------------------------------------------------
  1. Voice only:        python3 voice_start.py --no-robots
  2. Voice + MiP:       python3 voice_start.py --no-cozmo
  3. Both robots:       python3 voice_start.py

For step 3, join Cozmo's Wi-Fi network on the laptop first (Cozmo app
shows the name/password on its screen). MiP uses Bluetooth, so both can
be connected at once.

Stand MiP up and let it balance first. Give both robots 1 m of space.
"""

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time

# ---------------------------------------------------------------------
# Matching what was heard
# ---------------------------------------------------------------------

def heard_all_done(text):
    # The listener only knows the game's phrases, so "done" on its own
    # can only come from "all done"
    return "done" in text.split()


def heard_stop(text):
    return "stop" in text.split()


def heard_start(text):
    """'Let's play'. Any phrase with 'play' in it counts."""
    return "play" in text.split()


# Cozmo's own voice: clips unpacked from the Cozmo app's sound files
# (see sounds/cozmo/README.txt). Named by kind: go_01.wav, giggle_03.wav...
COZMO_SOUNDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds", "cozmo")


def cozmo_sound(cli, kind):
    """Play a random Cozmo clip of this kind ("go", "giggle"...) through
    Cozmo's speaker. Returns the clip's length in seconds, or 0 if none played."""
    try:
        import glob
        import random
        import wave
        clips = glob.glob(os.path.join(COZMO_SOUNDS, kind + "_*.wav"))
        if not clips:
            return 0
        clip = random.choice(clips)
        with wave.open(clip) as w:
            seconds = w.getnframes() / w.getframerate()
        cli.play_audio(clip)
        return seconds
    except Exception:
        return 0


# ---------------------------------------------------------------------
# Screen output (big, clear, good for a screen recording)
# ---------------------------------------------------------------------

GREEN, YELLOW, BLUE, GREY, BOLD, RESET = "\033[92m", "\033[93m", "\033[94m", "\033[90m", "\033[1m", "\033[0m"


def banner(text, colour):
    line = "=" * (len(text) + 8)
    print(f"\r\033[K\n{colour}{BOLD}{line}\n    {text}\n{line}{RESET}\n", flush=True)


def show_hearing(text):
    print(f"\r\033[K{GREY}Hearing: {text}{RESET}", end="", flush=True)


def say(text):
    print(f"\r\033[K{text}", flush=True)


# ---------------------------------------------------------------------
# Start beeps: three soft beeps that fade in and out
# ---------------------------------------------------------------------

def play_start_beeps():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        return
    rate = 44100
    t = np.linspace(0, 0.25, int(rate * 0.25), endpoint=False)
    fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.05)          # 50 ms fade in/out
    gap = np.zeros(int(rate * 0.35))
    parts = []
    for freq in (523, 659, 784):                                  # C, E, G
        parts += [0.15 * np.sin(2 * np.pi * freq * t) * fade, gap]
    sd.play(np.concatenate(parts).astype("float32"), rate)


# ---------------------------------------------------------------------
# MiP (Bluetooth). Uses the commands already in mip_test.py
# ---------------------------------------------------------------------

class MiP:
    def __init__(self):
        self.client = None
        self.send_char = None
        self.needs_reply = True
        self.routine = None

    async def connect(self):
        from bleak import BleakClient
        import mip_test
        self.m = mip_test
        device = await mip_test.find_mip()
        if not device:
            return False
        say(f"Found {device.name}. Connecting...")
        self.client = BleakClient(device)
        await self.client.connect()
        self.send_char = mip_test.find_characteristic(self.client, "ffe9")
        if not self.send_char:
            say("Connected to MiP but couldn't find its command channel.")
            return False
        self.needs_reply = "write-without-response" not in self.send_char.properties
        await self._send(self.m.chest_light(0, 20, 40))           # dim blue: waiting
        return True

    async def _send(self, command):
        await self.client.write_gatt_char(self.send_char, command, response=self.needs_reply)

    async def _hello(self):
        m = self.m
        await self._send(m.chest_light(0, 150, 60))                # green: playing
        await asyncio.sleep(0.4)
        for _ in range(2):                                          # small wiggle
            await self._send(m.turn_right(20))
            await asyncio.sleep(0.6)
            await self._send(m.turn_left(20))
            await asyncio.sleep(0.6)
        await self._send(m.STOP)

    def start_game(self):
        self._cancel()
        self.routine = asyncio.ensure_future(self._hello())

    async def stop(self):
        self._cancel()
        await self._send(self.m.STOP)
        await self._send(self.m.chest_light(160, 100, 0))          # amber: paused

    async def all_done(self):
        self._cancel()
        await self._send(self.m.STOP)
        await self._send(self.m.chest_light(0, 0, 0))              # light off
        await self.client.disconnect()

    def _cancel(self):
        if self.routine and not self.routine.done():
            self.routine.cancel()


# ---------------------------------------------------------------------
# Cozmo (its own Wi-Fi, via PyCozmo). PyCozmo isn't async, so Cozmo
# runs in its own thread and takes commands from a queue.
# ---------------------------------------------------------------------

class Cozmo:
    def __init__(self):
        self.commands = queue.Queue()
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.halt = threading.Event()
        self.edge = threading.Event()      # set when Cozmo's cliff sensor sees an edge
        self.cli = None
        self.error = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, command):
        if command == "start":
            self.halt.clear()
        elif command in ("stop", "done"):
            self.halt.set()                                         # interrupt any routine now
            if self.cli:
                self.cli.stop_all_motors()
        self.commands.put(command)

    # --- faces (128 x 32 pixel screen) ---
    @staticmethod
    def _face(kind):
        from PIL import Image, ImageDraw
        im = Image.new("1", (128, 32), 0)
        d = ImageDraw.Draw(im)
        for x in (24, 76):
            if kind == "happy":
                d.arc((x, 6, x + 28, 34), 200, 340, fill=1, width=5)
            elif kind == "calm":
                d.rounded_rectangle((x, 6, x + 28, 26), radius=6, fill=1)
            else:                                                   # sleepy
                d.line((x, 20, x + 28, 20), fill=1, width=3)
        return im

    def _wait(self, seconds):
        """Sleep, but return False straight away if told to stop.
        Also wakes up early (returning True) if Cozmo sees an edge."""
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0 or self.edge.is_set():
                return True
            if self.halt.wait(min(left, 0.05)):
                return False

    def _guard_edges(self, cli):
        """Turn on Cozmo's own edge safety: the cliff sensor under its front
        stops the wheels in the robot itself, the instant it sees a drop.
        We also hear about it, so the routine can back away and turn round."""
        from pycozmo import event, protocol_encoder
        cli.conn.send(protocol_encoder.EnableStopOnCliff(enable=True))

        def on_cliff(cli, at_edge):
            if at_edge:
                cli.stop_all_motors()
                self.edge.set()
        cli.add_handler(event.EvtCliffDetectedChange, on_cliff)

    def _hello(self, cli, robot):
        cli.display_image(self._face("happy"))
        cli.set_head_angle(robot.MAX_HEAD_ANGLE.radians)
        cozmo_sound(cli, "woohoo")                                  # Cozmo's own "Woohoo!"
        if not self._wait(0.7):
            return
        for _ in range(2):                                          # lift bounce
            cli.set_lift_height(robot.MAX_LIFT_HEIGHT.mm)
            if not self._wait(0.5):
                return
            cli.set_lift_height(robot.MIN_LIFT_HEIGHT.mm)
            if not self._wait(0.5):
                return
        for left, right in ((40, -40), (-40, 40)):                  # small wiggle
            cli.drive_wheels(lwheel_speed=left, rwheel_speed=right, duration=0.3)
            if not self._wait(0.4):
                return
        cli.set_head_angle(0.0)

    def _run(self):
        try:
            import pycozmo
            from pycozmo import robot
            with pycozmo.connect(enable_procedural_face=False, log_level="WARNING",
                                 protocol_log_level="WARNING") as cli:
                self.cli = cli
                self._guard_edges(cli)
                cli.set_head_angle(0.0)
                cli.display_image(self._face("calm"))
                self.connected.set()
                while True:
                    command = self.commands.get()
                    if command == "start":
                        self._hello(cli, robot)
                    elif command == "stop":
                        cli.stop_all_motors()
                        cli.display_image(self._face("calm"))
                    elif command == "done":
                        cli.stop_all_motors()
                        cli.set_lift_height(robot.MIN_LIFT_HEIGHT.mm)
                        cli.set_head_angle(robot.MIN_HEAD_ANGLE.radians)
                        cli.display_image(self._face("sleepy"))
                        time.sleep(1.5)
                        break
        except Exception as e:
            self.error = e
            self.connected.set()
        finally:
            self.finished.set()


# ---------------------------------------------------------------------
# Listening (Vosk, offline)
# ---------------------------------------------------------------------

def open_microphone(audio_queue):
    import sounddevice as sd

    def on_audio(data, frames, when, status):
        audio_queue.put(bytes(data))

    stream = sd.RawInputStream(samplerate=16000, blocksize=4000, dtype="int16",
                               channels=1, callback=on_audio)
    stream.start()
    return stream


def watch_keyboard(loop, on_key):
    """Space = pause, q = quit. Reads single key presses without Enter."""
    if not sys.stdin.isatty():
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    def reader():
        try:
            tty.setcbreak(fd)
            while True:
                key = sys.stdin.read(1)
                loop.call_soon_threadsafe(on_key, key)
                if key in ("q", "Q"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def main(args):
    from vosk import KaldiRecognizer, Model, SetLogLevel

    use_mip = not (args.no_robots or args.no_mip)
    use_cozmo = not (args.no_robots or args.no_cozmo)

    # --- connect robots ---
    cozmo = None
    if use_cozmo:
        say("Connecting to Cozmo over its Wi-Fi...")
        cozmo = Cozmo()
        cozmo.start()

    mip = None
    if use_mip:
        mip = MiP()
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

    # --- voice model ---
    say("Loading voice model (first time downloads ~40 MB)...")
    try:                                    # python.org Python on Mac has no web certificates
        import os
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    SetLogLevel(-1)
    model = Model(lang="en-us")
    # Only listen for the game's phrases. Anything else comes out as [unk],
    # which makes it much more accurate in a noisy room.
    phrases = ["let's play",
               "stop", "all done", "[unk]"]
    recogniser = KaldiRecognizer(model, 16000, json.dumps(phrases))

    audio = queue.Queue()
    mic = open_microphone(audio)

    state = {"mode": "waiting"}
    loop = asyncio.get_running_loop()
    finished = asyncio.Event()

    async def start_game(heard):
        if state["mode"] == "playing":
            return
        state["mode"] = "playing"
        banner(f'Heard "{heard}"  ->  GAME STARTED', GREEN)
        play_start_beeps()
        await asyncio.sleep(1.8)                                   # let the beeps finish
        if state["mode"] != "playing":
            return
        if mip:
            mip.start_game()
        if cozmo:
            cozmo.send("start")

    async def pause(heard):
        if state["mode"] != "playing":
            return
        state["mode"] = "paused"
        try:
            import sounddevice as sd
            sd.stop()                                               # cut the start beeps
        except Exception:
            pass
        if cozmo:
            cozmo.send("stop")
        if mip:
            await mip.stop()
        banner(f'Heard "{heard}"  ->  PAUSED  (say "Let\'s play" to carry on)', YELLOW)

    async def all_done(heard):
        if state["mode"] == "done":
            return
        state["mode"] = "done"
        banner(f'Heard "{heard}"  ->  ALL DONE', BLUE)
        if cozmo:
            cozmo.send("done")
        if mip:
            await mip.all_done()
        if cozmo:
            await loop.run_in_executor(None, cozmo.finished.wait, 5)
        finished.set()

    def on_key(key):
        if key == " ":
            asyncio.ensure_future(pause("[pause key]"))
        elif key in ("q", "Q"):
            asyncio.ensure_future(all_done("[q key]"))

    restore_terminal = watch_keyboard(loop, on_key)

    robots = " + ".join(n for n, r in (("Cozmo", cozmo), ("MiP", mip)) if r) or "no robots"
    banner(f'Listening ({robots}). Say "Let\'s play"', BLUE)
    say(f'{GREY}"Stop" or space bar pauses. "All done" or q ends.{RESET}\n')

    def next_audio():
        try:
            return audio.get(timeout=0.2)
        except queue.Empty:
            return None

    try:
        while not finished.is_set():
            chunk = await loop.run_in_executor(None, next_audio)
            if chunk is None:
                continue
            if recogniser.AcceptWaveform(chunk):
                text = json.loads(recogniser.Result()).get("text", "")
                final = True
            else:
                text = json.loads(recogniser.PartialResult()).get("partial", "")
                final = False
            text = text.replace("[unk]", "").strip()
            if not text:
                continue
            show_hearing(text)

            # "Stop" acts on partial results too, so the robots freeze fast
            if heard_all_done(text):
                recogniser.Reset()
                await all_done(text)
            elif heard_stop(text):
                recogniser.Reset()
                await pause(text)
            elif final and heard_start(text):
                # run alongside listening, so "stop" works during the beeps too
                asyncio.ensure_future(start_game(text))
    finally:
        mic.stop()
        if restore_terminal:
            restore_terminal()

    say("Finished. Robots are asleep.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keepy Up voice start demo")
    parser.add_argument("--no-robots", action="store_true", help="voice only, no robots")
    parser.add_argument("--no-cozmo", action="store_true", help="skip Cozmo")
    parser.add_argument("--no-mip", action="store_true", help="skip MiP")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
