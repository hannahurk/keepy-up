"""
Keepy Up Soccer launcher: the friendly screen behind the Desktop button.

    .venv/bin/python play_soccer.py            # what the Desktop button runs
    .venv/bin/python play_soccer.py --dry-run  # pretend robots, for testing

It asks which robots are playing, checks Cozmo's Wi-Fi, starts the ceiling
camera (tracker.py), the scoreboard (soccer.py) and the robots (chase.py), and
shows one calm screen: the score, what each robot is doing, MiP's battery.
Keys: p = pause / carry on, q = stop the game. Ctrl+C or closing the window
also stops everything (the robots stop their wheels first). Works offline.

Voice (11 Nov): say "start" to start the game (on the menu, the checklist and
the end screen; it also carries on after a pause) and "stop" to stop it. The
laptop's microphone listens offline with Vosk, for those two words only;
nothing is recorded or saved. "Stop" acts as soon as it's heard.

Everything the programs print is saved in keepy-up/logs/, one set per game.
"""

import argparse
import collections
import fcntl
import json
import os
import queue
import re
import select
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

from room import play_on_mac

HERE = Path(__file__).resolve().parent
PY = sys.executable
LAST_CHOICE = HERE.parent / "logs" / "last_choice.txt"
COZMO_IP = "172.31.1.1"          # Cozmo's own address on its Wi-Fi
CAMERA_PORT = 8765               # tracker.py
ROBOT_PORT = 8766                # chase.py listens here for game moments and pause
BOARD_PORT = 8767                # soccer.py listens here for pause / new game

CHOICES = {
    "a": ("both robots", ["cozmo", "mip"]),
    "c": ("Cozmo", ["cozmo"]),
    "m": ("MiP", ["mip"]),
}
# Both robots drive at the same top speed: 0.20 m/s, Cozmo's fastest (12 Nov; was 0.18).
SPEED_ARGS = ["--max-speed", "0.20", "--max-turn", "180"]
LOW_BATTERY = 25                 # %: below this, warn that MiP's battery is low (11 Nov: 11% made it weak)

# ------------------------------------------------------------------ look
B, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED, BLUE, PINK = "\033[92m", "\033[93m", "\033[91m", "\033[94m", "\033[95m"
WIDTH = 64

DIGITS = {
    "0": ["###", "# #", "# #", "# #", "###"], "1": [" # ", "## ", " # ", " # ", "###"],
    "2": ["###", "  #", "###", "#  ", "###"], "3": ["###", "  #", "###", "  #", "###"],
    "4": ["# #", "# #", "###", "  #", "  #"], "5": ["###", "#  ", "###", "  #", "###"],
    "6": ["###", "#  ", "###", "# #", "###"], "7": ["###", "  #", "  #", "  #", "  #"],
    "8": ["###", "# #", "###", "# #", "###"], "9": ["###", "# #", "###", "  #", "###"],
    "-": ["   ", "   ", "###", "   ", "   "],
}


def big(text):
    """Text in big block digits, 5 lines tall."""
    rows = []
    for r in range(5):
        rows.append("  ".join(DIGITS.get(ch, DIGITS["-"])[r] for ch in text)
                    .replace("#", "\u2588\u2588").replace(" ", "  "))
    return rows


def rule():
    return DIM + "\u2500" * WIDTH + RESET


def header(subtitle=""):
    title = f"{B}{PINK}\u26bd  KEEPY UP SOCCER{RESET}"
    return ["", "  " + title + (f"   {DIM}{subtitle}{RESET}" if subtitle else ""), "  " + rule()]


def draw(lines):
    """Redraw the whole window without flicker."""
    out = "\033[H" + "\n".join(line + "\033[K" for line in lines) + "\n\033[J"
    sys.stdout.write(out)
    sys.stdout.flush()


def clear():
    sys.stdout.write("\033[H\033[2J")
    sys.stdout.flush()


# ------------------------------------------------------------------ voice
VOSK_MODEL = Path.home() / ".cache" / "vosk" / "vosk-model-small-en-us-0.15"   # saved by the voice app


class Voice:
    """Listens on the laptop's microphone for "start" and "stop", offline (Vosk).
    Only those two words are listened for; anything else is ignored. Nothing is saved."""

    def __init__(self):
        self.words = queue.Queue()
        self.ready = False
        self.problem = None
        self.heard = ""          # last word heard, for the screen
        self.heard_at = 0
        self.last = {}

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def take(self):
        try:
            return self.words.get_nowait()
        except queue.Empty:
            return None

    def _say(self, word):
        now = time.monotonic()
        if now - self.last.get(word, 0) < 1.5:      # one word, said once
            return
        self.last[word] = now
        self.heard, self.heard_at = word, now
        self.words.put("voice_" + word)

    def _listen(self):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(VOSK_MODEL)) if VOSK_MODEL.exists() else Model(lang="en-us")
            rec = KaldiRecognizer(model, 16000, json.dumps(["start", "stop", "[unk]"]))
            audio = queue.Queue()
            stream = sd.RawInputStream(samplerate=16000, blocksize=4000, dtype="int16", channels=1,
                                       callback=lambda data, frames, when, status: audio.put(bytes(data)))
            stream.start()
            self.ready = True
            while True:
                chunk = audio.get()
                final = rec.AcceptWaveform(chunk)
                text = json.loads(rec.Result())["text"] if final else json.loads(rec.PartialResult())["partial"]
                said = text.replace("[unk]", "").split()
                if "stop" in said:                    # act at once, even mid-word
                    rec.Reset()
                    self._say("stop")
                elif final and "start" in said:       # only once the word is finished
                    self._say("start")
        except Exception as e:                          # no microphone, no model...: keys still work
            self.problem = e.__class__.__name__

    def hint(self, words):
        """A line for the screen: what to say, or why voice isn't working."""
        if self.problem:
            return f"{DIM}Voice commands are off ({self.problem}). Use the keys.{RESET}"
        if not self.ready:
            return f"{DIM}\U0001f3a4 Starting the microphone...{RESET}"
        heard = ""
        if self.heard and time.monotonic() - self.heard_at < 3:
            heard = f"   {GREEN}heard \u201c{self.heard}\u201d{RESET}"
        return f"{BLUE}\U0001f3a4 {words}{RESET}{heard}"


# ------------------------------------------------------------------ keys
class Keys:
    """Read single key presses without Return (the window stays in this mode
    while the game runs). Ctrl+C still works as usual."""

    def __init__(self, voice=None):
        self.voice = voice
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd) if os.isatty(self.fd) else None

    def __enter__(self):
        if self.saved:
            tty.setcbreak(self.fd)
            sys.stdout.write("\033[?25l")       # hide the cursor
        return self

    def __exit__(self, *exc):
        self.restore()

    def restore(self):
        if self.saved:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def get(self, timeout):
        """A key pressed (lower case) or a word said ("voice_start" / "voice_stop")
        within `timeout` seconds, or None."""
        end = time.monotonic() + timeout
        while True:
            said = self.voice.take() if self.voice else None
            if said:
                return said
            left = end - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([sys.stdin], [], [], min(0.1, left))
            if ready:
                ch = os.read(self.fd, 1).decode(errors="ignore")
                return "\n" if ch in ("\r", "\n") else ch.lower()


def wait_key(keys, allowed, timeout=None, tick=None):
    """Wait for one of `allowed`. Calls tick() every half second (for live checks);
    tick() may return a key to act as if pressed."""
    start = time.monotonic()
    while True:
        k = keys.get(0.5)
        if k == "voice_start" and "\n" in allowed:
            return "\n"                   # "start" = Return on these screens
        if k in allowed:
            return k
        if tick:
            k = tick()
            if k:
                return k
        if timeout and time.monotonic() - start > timeout:
            return None


# ------------------------------------------------------------------ helpers
def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cozmo_reachable():
    return subprocess.run(["ping", "-c", "1", "-t", "1", COZMO_IP],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def scoreboard_running():
    # "soccer.py" on its own, not inside "play_soccer.py" (12 Nov: two game windows
    # each took the other for the scoreboard, so no scoreboard started)
    return subprocess.run(["pgrep", "-f", "(^|[ /])soccer\\.py"], stdout=subprocess.DEVNULL).returncode == 0


def send(port, text):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(text.encode(), ("127.0.0.1", port))
    except OSError:
        pass


def bring_terminal_forward():
    """The scoreboard window opens on top; put this window back in front so the
    keys (p, q) reach it."""
    if os.environ.get("TERM_PROGRAM") == "Apple_Terminal":
        subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_into(proc, source, log, q):
    """Copy a program's output to its log file and to the screen's queue."""
    for line in proc.stdout:
        log.write(line)
        log.flush()
        q.put((source, line.rstrip("\n")))
    q.put((source, None))      # finished


def load_last():
    try:
        c = LAST_CHOICE.read_text().strip()
        return c if c in CHOICES else "a"
    except OSError:
        return "a"


def save_last(c):
    try:
        LAST_CHOICE.write_text(c)
    except OSError:
        pass


# ------------------------------------------------------------------ the game's state
class State:
    def __init__(self, robots, own_board):
        self.robots = {n: {"mark": "\u2026", "colour": YELLOW, "doing": "waiting to connect",
                           "battery": None, "posture": None} for n in robots}
        self.own_board = own_board
        self.score = (0, 0) if own_board else None
        self.board = "Starting the scoreboard..." if own_board else "Scores are on the scoreboard window"
        self.winner = None
        self.last_moment = ""
        self.paused = False
        self.camera_trouble = False
        self.connected_at = None    # when both robots were ready
        self.waiting_start = True   # robots and scoreboard held until the 1-2-3 countdown ends
        self.countdown = None       # "1", "2", "3" or "START!" while the start sequence shows
        self.listening = False      # the robot program is ready for "go" (it said "Listening to")
        self.charger_wait = False   # Cozmo just connected on his charger: waiting for him to be moved
        self.tail = collections.deque(maxlen=40)   # recent robot-program lines, to explain failures
        self.unseen = collections.Counter()        # times the camera lost each robot
        self.bt_drops = collections.Counter()      # Bluetooth drops that reconnected by themselves

    def set(self, name, mark, colour, doing):
        r = self.robots.get(name)
        if r:
            r["mark"], r["colour"], r["doing"] = mark, colour, doing

    def all_ready(self):
        return all(r["mark"] == "\u2713" for r in self.robots.values())


ROBOT_LINE = re.compile(r"^(?:\d\d:\d\d:\d\d )?\[(cozmo|mip)\] (.*)$")
DOING = [  # (start of chase.py's status, words on screen, colour)
    ("stopped: camera can't see it", "camera can't see it", RED),
    ("stopped: hidden under the balloon", "under the balloon", YELLOW),
    ("stopped: balloon not seen", "waiting to see the balloon", DIM),
    ("stopped: no soccer job", "standing by", DIM),
    ("driving back inside", "coming back inside the tape", YELLOW),
    ("paused", "paused", YELLOW),
    ("stopped: Bluetooth reconnecting", "Bluetooth dropped: reconnecting by itself...", YELLOW),
]
JOBS = {"push": "pushing the balloon!", "get behind": "getting behind the balloon",
        "guard": "guarding the goal", "chase": "chasing the balloon",
        "wait": "waiting: the balloon is on the other robot's side"}
MOMENTS = {"play": "Play!", "out": "Out!", "robots_goal": "The robots scored!",
           "people_goal": "You scored!", "robots_win": "The robots win!",
           "people_win": "You win!", "new_game": "New game", "near_miss": "So close!"}


def robot_line(st, line):
    st.tail.append(line)
    m = re.search(r"moment: (\w+)", line)
    if m:
        st.last_moment = MOMENTS.get(m.group(1), st.last_moment)
        return
    if "Looking for MiP" in line:
        st.set("mip", "\u2026", YELLOW, "looking for MiP over Bluetooth...")
        return
    if "MiP not found" in line:
        st.set("mip", "\u2717", RED, "not found: is it switched on and standing up?")
        return
    if "Can't reach the tracker" in line:
        st.camera_trouble = True
        return
    if line.startswith("Listening to"):
        st.camera_trouble = False
        return
    m = ROBOT_LINE.match(line)
    if not m:
        return
    name, status = m.groups()
    r = st.robots.get(name)
    if not r:
        return
    if status.startswith("connecting"):
        st.set(name, "\u2026", YELLOW, "connecting over Cozmo's Wi-Fi...")
    elif status.startswith("connected") or status.startswith("dry run") or status.startswith("reconnected"):
        st.set(name, "\u2713", GREEN, "ready")
        if name == "cozmo" and not status.startswith("reconnected"):
            st.charger_wait = True          # he connected on his charger: ask for him to be moved
        if st.all_ready() and not st.connected_at:
            st.connected_at = time.monotonic()
    # --- fix 2: MiP's Bluetooth drops and comes back without stopping the game
    elif status.startswith("Bluetooth lost") or status.startswith("still reconnecting"):
        st.set(name, "\u2026", YELLOW, "Bluetooth dropped: reconnecting by itself...")
        st.bt_drops[name] += status.startswith("Bluetooth lost")
    elif status.startswith("battery"):
        b = re.match(r"battery (\d+)%(?:, (.*))?", status)
        if b:
            r["battery"] = int(b.group(1))
            r["posture"] = b.group(2)
    elif r["mark"] == "\u2713":
        for start, words, colour in DOING:
            if status.startswith(start):
                r["doing"], r["colour"] = words, colour
                if start.startswith("stopped: camera"):
                    st.unseen[name] += 1
                return
        job, _, rest = status.partition(":")
        job = job.replace(" (there)", "")
        if job in JOBS:
            if "too close" in rest:
                r["doing"], r["colour"] = "waiting: too close to the other robot", YELLOW
            else:
                r["doing"], r["colour"] = JOBS[job], GREEN


BOARD_EVENT = re.compile(r"^\d\d:\d\d:\d\d (.*)$")


def board_line(st, line):
    m = BOARD_EVENT.match(line)
    text = m.group(1) if m else line
    if not m and text not in ("Paused", "Resumed"):
        return                      # the scoreboard's help text
    s = re.search(r"People (\d+) - (\d+) Robots", text)
    if s:
        st.score = (int(s.group(1)), int(s.group(2)))
    w = re.search(r"The (people|robots) win (\d+) - (\d+)", text)
    if w:
        st.winner = w.group(1)
        hi, lo = int(w.group(2)), int(w.group(3))
        st.score = (hi, lo) if st.winner == "people" else (lo, hi)
    if text in ("Paused", "Resumed"):
        return
    st.board = re.sub(r"\s+Press .*new game", "", text).replace("  ", " ")


def why_it_stopped(st, robots):
    """Which robot made the robot program stop, and why, from its last lines."""
    text = "\n".join(st.tail)
    if "MiP not found" in text:
        return "mip", "MiP wasn't found over Bluetooth"
    if re.search(r"Failed to (connect to|initialize) Cozmo|ConnectionTimeout", text):
        return "cozmo", "Cozmo didn't answer over Wi-Fi"
    if re.search(r"[Bb]leak|Service Discovery|GATT|not connected|disconnected", text):
        return "mip", "MiP's Bluetooth connection dropped"
    if re.search(r"pycozmo|Cozmo", text) and "cozmo" in robots:
        return "cozmo", "the connection to Cozmo dropped"
    return None, "the robot program stopped unexpectedly"


# ------------------------------------------------------------------ the launcher
class Launcher:
    def __init__(self, args):
        self.args = args
        self.logdir = Path(args.logdir)
        self.logdir.mkdir(parents=True, exist_ok=True)
        self.started = []           # programs this launcher started (only these get stopped)
        self.chase = None
        self.chase_reader = None
        self.voice = None if args.no_voice else Voice()
        self.keys = Keys(self.voice)

    # -------------------------------------------------------------- screens
    def choose(self, last):
        names = {"a": "Both robots", "c": "Cozmo only", "m": "MiP only"}
        lines = header() + ["", f"  {B}Who's playing today?{RESET}", ""]
        for k in ("a", "c", "m"):
            mark = f"  {DIM}(last time){RESET}" if k == last else ""
            lines.append(f"     {B}{k}{RESET}   {names[k]}{mark}")
        lines += ["", f"  Press a, c or m.  {DIM}Return = {names[last].lower()}.  q = close.{RESET}"]
        show = lambda: draw(lines + ["", "  " + self.voice_hint(f"Say \u201cstart\u201d for {names[last].lower()}")])
        show()
        k = wait_key(self.keys, set("acmq\n"), tick=show)
        return last if k == "\n" else k

    def checklist(self, choice):
        robots = CHOICES[choice][1]
        items = []
        if "mip" in robots:
            items += ["MiP is on, standing up and balancing",
                      "The MiP app is closed (on this Mac and your phone)"]
        if "mip" in robots:
            items += ["MiP is in its pink square, facing the centre line"]
        if "cozmo" in robots:
            items += ["Cozmo is ON his charger (the game says when to move him)"]
        items += [
                  "The balloon is in the arena; nothing else is on the floor",
                  "A grown-up is watching"]
        lines = header(CHOICES[choice][0]) + ["", f"  {B}Before we start, check:{RESET}", ""]
        lines += [f"     \u25a1  {t}" for t in items]
        lines += ["", f"  {GREEN}{B}Return{RESET} = all set, let's play    {DIM}b = back    q = close{RESET}"]
        show = lambda: draw(lines + ["", "  " + self.voice_hint("Say \u201cstart\u201d to start the game")])
        show()
        return wait_key(self.keys, set("\nbq"), tick=show)

    def wifi_check(self, choice):
        """Make sure Cozmo can be reached before starting. Returns the choice to
        play with (it may become MiP only), or None to go back."""
        if "cozmo" not in CHOICES[choice][1] or self.args.dry_run:
            return choice
        if cozmo_reachable():
            return choice
        other = "  m = play with MiP only instead\n" if choice == "a" else ""
        lines = header(CHOICES[choice][0]) + [
            "", f"  {YELLOW}{B}This Mac isn't on Cozmo's Wi-Fi yet.{RESET}", "",
            "     1.  Put Cozmo on its charger and lift its arm up and down:",
            "         its face shows its Wi-Fi name (Cozmo_...) and password.",
            "     2.  Click the Wi-Fi icon at the top of the screen and join it.",
            "         \"No internet\" is normal.",
            "     3.  Leave Cozmo on his charger: the game tells you when to move him.",
            "", f"  {DIM}Checking again every couple of seconds...{RESET}", "",
        ]
        lines += [f"  {DIM}{t}{RESET}" for t in other.splitlines()] + [f"  {DIM}b = back    q = close{RESET}"]
        draw(lines)
        k = wait_key(self.keys, set("bq" + ("m" if choice == "a" else "")),
                     tick=lambda: "ok" if cozmo_reachable() else None)
        if k == "ok":
            draw(header(CHOICES[choice][0]) + ["", f"  {GREEN}\u2713 Found Cozmo's Wi-Fi.{RESET}"])
            time.sleep(1)
            return choice
        if k == "m":
            return "m"
        if k == "q":
            raise SystemExit
        return None

    def voice_hint(self, words):
        return self.voice.hint(words) if self.voice else ""

    def message(self, title, colour=YELLOW, body=(), wait=None):
        draw(header() + ["", f"  {colour}{B}{title}{RESET}", ""] + [f"     {t}" for t in body])
        if wait:
            time.sleep(wait)

    # -------------------------------------------------------------- programs
    def start_camera(self, stamp):
        if port_open(CAMERA_PORT):
            return True                          # already running (e.g. started elsewhere)
        self.message("Starting the camera...", BLUE)
        log = open(self.logdir / f"camera_{stamp}.log", "w")
        p = subprocess.Popen([PY, "-u", "tracker.py", "--source", "0"], cwd=HERE,
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self.started.append(p)
        for _ in range(40):
            if port_open(CAMERA_PORT):
                return True
            if p.poll() is not None:
                break
            time.sleep(0.5)
        self.message("The camera didn't start.", RED, [
            "If macOS asked to let Terminal use the camera, click OK, then try again.",
            "Is the camera plugged in? Is another program using it?",
            f"{DIM}Details: {self.logdir}/camera_{stamp}.log{RESET}", "",
            f"{B}Return{RESET} = back to the start"])
        wait_key(self.keys, set("\nq"))
        return False

    def start_board(self, stamp, q):
        if scoreboard_running():
            return False                          # someone else's scoreboard: use it
        log = open(self.logdir / f"scoreboard_{stamp}.log", "w")
        p = subprocess.Popen([PY, "-u", "soccer.py", "--no-keys"], cwd=HERE, text=True, bufsize=1,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self.started.append(p)
        threading.Thread(target=read_into, args=(p, "board", log, q), daemon=True).start()
        time.sleep(1.5)
        bring_terminal_forward()
        return True

    def start_robots(self, robots, log, q):
        extra = ["--only", robots[0]] if len(robots) == 1 else []
        if self.args.dry_run:
            extra.append("--dry-run")
        extra.append("--start-paused")        # wait for the 1-2-3 countdown (and Cozmo off his charger)
        log.write(f"===== {time.strftime('%H:%M:%S')} starting robots: {', '.join(robots)} =====\n")
        log.flush()
        self.chase = subprocess.Popen([PY, "-u", "chase.py", "--game", "soccer", *SPEED_ARGS, *extra],
                                      cwd=HERE, text=True, bufsize=1, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.chase_reader = threading.Thread(target=read_into, args=(self.chase, "robots", log, q), daemon=True)
        self.chase_reader.start()

    def stop_robots(self):
        """Ctrl+C for the robot program: it stops the wheels itself, then exits."""
        p = self.chase
        if p and p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                p.terminate()
                try:
                    p.wait(4)
                except subprocess.TimeoutExpired:
                    p.kill()

    def stop_everything(self):
        self.stop_robots()
        for p in self.started:
            if p.poll() is None:
                p.terminate()
        for p in self.started:
            try:
                p.wait(4)
            except subprocess.TimeoutExpired:
                p.kill()
        self.started = []

    # -------------------------------------------------------------- the game screen
    def game_screen(self, st, choice, attempt_note=""):
        who = CHOICES[choice][0]
        played = ""
        if st.connected_at:
            secs = int(time.monotonic() - st.connected_at)
            played = f"playing {secs // 60}:{secs % 60:02d}"
        lines = header(f"{who}    {played}")
        if st.score is not None or st.countdown:
            lines += ["", f"         {B}PEOPLE{RESET}                        {B}ROBOTS{RESET}"]
        if st.countdown:                       # 1, 2, 3, START! just below the team names
            spaced = "  ".join(st.countdown)
            lines += ([f"                            {GREEN}{r}{RESET}" for r in big(st.countdown)]
                      if st.countdown.isdigit() else
                      ["", "", " " * max(2, (64 - len(spaced)) // 2) + f"{GREEN}{B}{spaced}{RESET}", "", ""])
        elif st.score is not None:
            p, r = st.score
            left, right = big(str(min(p, 9))), big(str(min(r, 9)))
            for a, b in zip(left, right):
                lines.append(f"         {BLUE}{a}{RESET}" + " " * 24 + f"{PINK}{b}{RESET}")
        lines += ["", f"  {B}{st.board}{RESET}"]
        if st.last_moment:
            lines.append(f"  {DIM}Last: {st.last_moment}{RESET}")
        lines += ["", f"  {B}Robots{RESET}"]
        for name, r in st.robots.items():
            label = "Cozmo" if name == "cozmo" else "MiP  "
            extra = ""
            if r["battery"] is not None:
                colour = RED if r["battery"] < 25 else (YELLOW if r["battery"] < 45 else DIM)
                extra = f"   {colour}battery {r['battery']}%{RESET}"
            if r["posture"]:
                extra += f"   {RED}{r['posture']}!{RESET}"
            lines.append(f"   {r['colour']}{r['mark']}{RESET} {B}{label}{RESET}  {r['colour']}{r['doing']}{RESET}{extra}")
        bat = st.robots.get("mip", {}).get("battery")
        if bat is not None and bat < LOW_BATTERY:
            lines += ["", f"  {RED}{B}MiP's battery is low ({bat}%).{RESET}{RED} It may move slowly or drop its",
                      f"  {RED}Bluetooth. Charging it before playing works best.{RESET}"]
        if st.camera_trouble:
            lines += ["", f"  {RED}The camera isn't sending pictures. Is it plugged in?{RESET}"]
        if attempt_note:
            lines += [""] + [f"  {YELLOW}{t.strip()}{RESET}" for t in attempt_note.split("\n")]
        if st.charger_wait:
            lines += ["", f"  {GREEN}{B}Cozmo is awake and connected.{RESET}",
                      f"  {B}Lift him off the charger into his pink square,{RESET}",
                      f"  {B}then press Return or say \u201cstart\u201d.{RESET}  {DIM}(The robots wait till then.){RESET}"]
        elif st.paused:
            lines += ["", f"  {YELLOW}{B}\u23f8  PAUSED{RESET}{YELLOW}: the robots are stopped. "
                          f"Press p or say \u201cstart\u201d to carry on.{RESET}"]
        lines += ["", "  " + rule(),
                  f"  {B}p{RESET} pause / carry on    {B}n{RESET} new game    {B}q{RESET} stop the game    {DIM}Ctrl+C stops at once{RESET}"]
        if self.voice:
            lines.append("  " + self.voice_hint("Say \u201cstop\u201d to stop the game"))
        draw(lines)

    def count_in(self, st, choice):
        """The start sequence, for every game (first or new): the scoreboard's "Get ready...",
        then 1, 2, 3 (a beep each), then START! with the start sound."""
        send(BOARD_PORT, "get_ready")           # "Get ready..." on the scoreboard, as before
        time.sleep(1.5)
        for n in ("1", "2", "3"):
            st.countdown = n
            send(BOARD_PORT, f"count {n}")      # the scoreboard counts along
            play_on_mac("count")
            self.game_screen(st, choice)
            time.sleep(1)
        st.countdown = "START!"
        send(BOARD_PORT, "count START!")
        play_on_mac("start")
        self.game_screen(st, choice)
        time.sleep(0.8)
        st.countdown = None

    def play(self, choice):
        """One game, from connecting to stopping. Returns a summary."""
        stamp = time.strftime("%Y-%m-%d_%H%M")
        robots = CHOICES[choice][1]
        q = queue.Queue()
        if not self.start_camera(stamp):
            return None
        own_board = self.start_board(stamp, q)
        send(BOARD_PORT, "get_ready")           # no "Play!" until the countdown is done
        st = State(robots, own_board)
        log = open(self.logdir / f"robots_{stamp}.log", "a")
        fails = collections.Counter()           # failed connects / drops per robot, in a row
        total_restarts, drops = 0, collections.Counter()
        reasons = []
        started_at = time.monotonic()
        stop = False
        note = ""
        self.start_robots(robots, log, q)

        def hold(on):
            send(ROBOT_PORT, "pause" if on else "resume")
            send(BOARD_PORT, "pause" if on else "resume")

        try:
            def take_lines():
                nonlocal note
                while True:
                    try:
                        source, line = q.get_nowait()
                    except queue.Empty:
                        return
                    if line is None:
                        continue
                    if source == "robots":
                        robot_line(st, line)
                        if line.startswith("Listening to"):
                            st.listening = True
                        if line.startswith("Listening to") and st.paused:
                            send(ROBOT_PORT, "pause")     # paused while it was connecting
                        if st.all_ready():
                            fails.clear()
                            note = ""
                    else:
                        board_line(st, line)
                        if "New game" in line:          # a new game (n): hold the robots for the
                            st.waiting_start = True     # start sequence again, and 0 - 0 on screen
                            send(ROBOT_PORT, "pause")
                            if st.own_board:
                                st.score, st.winner = (0, 0), None

            while not stop:
                take_lines()                    # what the programs said
                if st.waiting_start and time.monotonic() - getattr(st, "told_board", 0) > 1:
                    st.told_board = time.monotonic()
                    send(BOARD_PORT, "get_ready")   # again each second, in case the scoreboard started late
                if st.waiting_start and st.listening and st.all_ready() and not st.charger_wait and not st.paused:
                    self.count_in(st, choice)   # 1, 2, 3, START! Then the robots are off
                    st.waiting_start = False
                    hold(False)
                self.game_screen(st, choice, note)

                k = self.keys.get(0.25)
                if st.charger_wait and k in ("\n", "voice_start", "p"):
                    st.charger_wait = False          # Cozmo is in the arena: the countdown comes next
                    continue
                if k == "voice_start" and st.paused:
                    k = "p"                          # "start" carries on after a pause
                if k == "voice_stop":
                    k = "q"
                if k == "n" and st.own_board and not st.waiting_start:
                    send(BOARD_PORT, "new_game")     # the scoreboard resets; "New game" brings the start sequence
                elif k == "p":
                    st.paused = not st.paused
                    send(ROBOT_PORT, "pause" if st.paused else "resume")
                    send(BOARD_PORT, "pause" if st.paused else "resume")
                elif k == "q":
                    play_on_mac("stop")              # q or "stop": game over sound
                    st.board = "Stopping..."
                    self.game_screen(st, choice)
                    stop = True
                    break

                if self.chase and self.chase.poll() is not None:
                    # The robot program stopped by itself: a robot didn't answer or dropped out.
                    self.chase_reader.join(3)    # its last words (the error) first
                    take_lines()
                    who, why = why_it_stopped(st, robots)
                    reasons.append(why)
                    total_restarts += 1
                    if who:
                        fails[who] += 1
                        if st.connected_at:
                            drops[who] += 1
                        st.set(who, "\u2717", RED, why)
                    # Playing with both and one keeps failing: offer to carry on without it.
                    if len(robots) == 2 and who and fails[who] >= 2:
                        other = "cozmo" if who == "mip" else "mip"
                        oname = "Cozmo" if other == "cozmo" else "MiP"
                        wname = "MiP" if who == "mip" else "Cozmo"
                        self.message(f"{why[0].upper() + why[1:]} ({fails[who]} times).", YELLOW, [
                            tip_for(who), "",
                            f"{B}y{RESET} = play with {oname} only     {B}n{RESET} = keep trying {wname}     {DIM}q = stop{RESET}"])
                        k = wait_key(self.keys, set("ynq"))
                        if k == "q":
                            stop = True
                            break
                        if k == "y":
                            choice = "c" if other == "cozmo" else "m"
                            robots = CHOICES[choice][1]
                            st.robots = {n: v for n, v in st.robots.items() if n in robots}
                        fails.clear()
                    note = f"{why[0].upper() + why[1:]}. Trying again in a moment..."
                    if who == "cozmo" or "cozmo" in robots and st.robots.get("cozmo", {}).get("mark") != "\u2713":
                        note += "\n  Put Cozmo on his charger to wake him up."
                    for n in robots:
                        if st.robots[n]["mark"] == "\u2713":
                            st.set(n, "\u2026", YELLOW, "reconnecting...")
                    self.game_screen(st, choice, note)
                    if wait_key(self.keys, {"q"}, timeout=3) == "q":
                        stop = True
                        break
                    st.tail.clear()
                    st.waiting_start, st.listening = True, False   # restarted robots wait for a new countdown
                    send(BOARD_PORT, "get_ready")
                    self.start_robots(robots, log, q)
        except KeyboardInterrupt:
            play_on_mac("stop")      # Ctrl+C: the robot program got it too and is stopping its wheels
        st.board = "Stopping the robots..."
        self.game_screen(st, choice)
        self.stop_everything()
        log.write(f"===== {time.strftime('%H:%M:%S')} game ended =====\n")
        log.close()
        minutes = (time.monotonic() - started_at) / 60
        return {"st": st, "minutes": minutes, "restarts": total_restarts, "drops": drops,
                "reasons": reasons, "log": self.logdir / f"robots_{stamp}.log", "choice": choice}

    def summary(self, s):
        st = s["st"]
        lines = header("game over") + [""]
        if st.score is not None:
            p, r = st.score
            if st.winner == "people":
                lines.append(f"  {GREEN}{B}You won!{RESET}")
            elif st.winner == "robots":
                lines.append(f"  {PINK}{B}The robots won!{RESET}")
            lines.append(f"  {B}People {p} \u2013 {r} Robots{RESET}")
        else:
            lines.append(f"  {DIM}The score is on the scoreboard window.{RESET}")
        lines.append(f"  {DIM}Played for about {max(1, round(s['minutes']))} min.{RESET}")
        tips = []
        for name in ("mip", "cozmo"):
            if s["drops"][name]:
                n = s["drops"][name]
                tips.append(f"{'MiP' if name == 'mip' else 'Cozmo'} lost its connection {n} time{'s' if n > 1 else ''}. "
                            + tip_for(name))
        if s["restarts"] and not tips:
            tips.append(f"The robots had to reconnect {s['restarts']} time(s): {s['reasons'][-1]}.")
        for name, n in st.bt_drops.items():
            if n:
                tips.append(f"MiP's Bluetooth dropped {n} time{'s' if n > 1 else ''} and reconnected by itself. "
                            "If it happens a lot, charge MiP and keep the laptop closer.")
        bat = st.robots.get("mip", {}).get("battery")
        if bat is not None and bat < 35:
            tips.append(f"MiP's battery is low ({bat}%): charge it before the next game.")
        for name, n in st.unseen.items():
            if n >= 5:
                tips.append(f"The camera often lost {'Cozmo' if name == 'cozmo' else 'MiP'}: check its green "
                            "patch is flat, clean and facing up.")
        if tips:
            lines += ["", f"  {YELLOW}{B}Worth checking{RESET}"] + [f"   \u2022 {t}" for t in tips]
        lines += ["", f"  {DIM}Everything the robots said is saved in:{RESET}", f"  {DIM}{s['log']}{RESET}",
                  "", "  " + rule(),
                  f"  {GREEN}{B}Return{RESET} = play again      {B}r{RESET} = change robots      {B}q{RESET} = close"]
        show = lambda: draw(lines + ["  " + self.voice_hint("Say \u201cstart\u201d to play again")])
        show()
        return wait_key(self.keys, set("\nrq"), tick=show)

    def run(self):
        sys.stdout.write("\033]0;Keepy Up Soccer\007\033[8;32;72t")   # window title and size
        clear()
        if self.voice:
            self.voice.start()
        choice = None
        with self.keys:
            while True:
                if choice is None:
                    choice = self.choose(load_last())
                    if choice == "q":
                        break
                    save_last(choice)
                k = self.checklist(choice)
                if k == "q":
                    break
                if k == "b":
                    choice = None
                    continue
                playing = self.wifi_check(choice)
                if playing is None:
                    choice = None
                    continue
                result = self.play(playing)
                if result is None:
                    choice = None
                    continue
                k = self.summary(result)
                if k == "q":
                    break
                if k == "r":
                    choice = None
        clear()
        print("  Thanks for playing Keepy Up Soccer!\n")


def tip_for(name):
    if name == "mip":
        return "Check MiP's battery, that it's standing up, and that the MiP app is closed."
    return "Put Cozmo on his charger to wake him up, and check this Mac is on Cozmo's Wi-Fi."


def main():
    p = argparse.ArgumentParser(description="Start Keepy Up Soccer with a friendly screen.")
    p.add_argument("--dry-run", action="store_true", help="Pretend robots (for testing)")
    p.add_argument("--no-voice", action="store_true", help="Don't listen for 'start' and 'stop'")
    p.add_argument("--logdir", default=str(HERE.parent / "logs"), help="Where to save the game logs")
    args = p.parse_args()

    # Only one game window at a time (12 Nov: two were open, both heard "start", and
    # two robot programs fought over Cozmo). The lock goes when this window closes.
    Path(args.logdir).mkdir(parents=True, exist_ok=True)
    lock = open(Path(args.logdir) / ".game_window.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"\n  {YELLOW}{B}Keepy Up Soccer is already open in another window.{RESET}")
        print("  Please use that one (only one game can run at a time).\n")
        try:
            input("  Press Return to close this window. ")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    launcher = Launcher(args)

    def closing(signum, frame):
        raise SystemExit      # window closed: the 'finally' below stops everything
    signal.signal(signal.SIGHUP, closing)
    signal.signal(signal.SIGTERM, closing)
    try:
        launcher.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        launcher.stop_everything()
        launcher.keys.restore()


if __name__ == "__main__":
    main()
