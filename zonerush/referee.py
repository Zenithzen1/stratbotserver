"""Referee commands during a game (rulebook 4.3, 4.4).

The referee types short commands into the console while the game runs. They take effect
between turns, never in the middle of one:

    p            pause before the next turn          (4.4: safety, hardware fault, system error)
    r            resume
    pen 2        time penalty for seat 2: frozen for the next 3 turns (4.4)
    late 3       seat 3's robot isn't ready: its bot stays frozen at home (4.4 late robot)
    ready 3      seat 3's robot is placed: it plays normally again
    abort        stop the game now. The record is kept and the game can be resumed (section 6)
    help         list the commands

Commands typed in the console are only queued here. The game loop picks them up before each
turn, so everything that changes the game happens in one place, in order, and is recorded.
"""
import queue
import threading

from .state import SEATS

HELP = """Referee commands (they take effect between turns):
  p           pause            r          resume
  pen <seat>  time penalty     late <seat> / ready <seat>   robot missing / placed
  abort       stop the game (it can be resumed later)        help       this list"""


class Control:
    def __init__(self, late=()):
        self._inbox = queue.Queue()
        self.paused = False
        self.aborted = False
        self.late = set(late)               # seats whose robot isn't on the arena yet
        self.waited = False                 # did the last before_turn wait for a resume?
        self._penalties = []

    # --- called from the console (any thread) -------------------------------------------

    def send(self, text: str) -> str:
        """Queue one typed command. Returns a short reply for the console."""
        words = text.strip().lower().split()
        if not words:
            return ""
        cmd = words[0]
        if cmd in ("p", "pause"):
            self._inbox.put(("pause",))
            return "pausing before the next turn"
        if cmd in ("r", "resume"):
            self._inbox.put(("resume",))
            return "resuming"
        if cmd == "abort":
            self._inbox.put(("abort",))
            return "aborting before the next turn"
        if cmd in ("pen", "late", "ready"):
            if len(words) != 2 or not words[1].isdigit() or int(words[1]) not in SEATS:
                return f"usage: {cmd} <seat 1-4>"
            seat = int(words[1])
            self._inbox.put((cmd, seat))
            return {"pen": f"seat {seat}: time penalty before the next turn",
                    "late": f"seat {seat}: robot missing, bot held at home",
                    "ready": f"seat {seat}: robot placed, bot plays again"}[cmd]
        if cmd in ("help", "h", "?"):
            return HELP
        return f"unknown command {cmd!r} (type help)"

    # --- called by the game loop, between turns --------------------------------------------

    def before_turn(self, show_paused=lambda: None) -> list:
        """Apply queued commands, wait here while paused, then return the referee actions
        for the coming turn, e.g. [{"type": "penalty", "seat": 2}]."""
        self._apply_all()
        self.waited = self.paused             # the game loop re-checks the robots after a pause
        while self.paused and not self.aborted:
            show_paused()
            try:
                self._apply(self._inbox.get(timeout=0.5))
            except queue.Empty:
                pass
            self._apply_all()
        actions = [{"type": "penalty", "seat": seat} for seat in self._penalties]
        actions += [{"type": "late_robot", "seat": seat} for seat in sorted(self.late)]
        self._penalties = []
        return actions

    def pause_now(self):
        """Pause before the next turn (used by the game loop itself, e.g. for a robot fault)."""
        self.paused = True

    def _apply_all(self):
        while True:
            try:
                self._apply(self._inbox.get_nowait())
            except queue.Empty:
                return

    def _apply(self, command):
        kind = command[0]
        if kind == "pause":
            self.paused = True
        elif kind == "resume":
            self.paused = False
        elif kind == "abort":
            self.aborted = True
        elif kind == "pen":
            self._penalties.append(command[1])
        elif kind == "late":
            self.late.add(command[1])
        elif kind == "ready":
            self.late.discard(command[1])


def start_console(control: Control, prompt: str = "referee> "):
    """Read referee commands from the keyboard in a background thread."""
    def loop():
        print(HELP)
        while True:
            try:
                line = input(prompt)
            except (EOFError, KeyboardInterrupt):
                return
            reply = control.send(line)
            if reply:
                print(reply)

    threading.Thread(target=loop, daemon=True).start()
