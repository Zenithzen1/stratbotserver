"""Runs each bot in its own process and asks it for one action per turn, within the time limit.

Rulebook 2.8: 200 ms per turn (2 s on the first), and a bot that crashes, is late or returns
an illegal action plays STAY. README: a bot's global variables last for the whole game and
are cleared before the next one, so each bot gets one fresh process per game.

A bot only runs during its own turn. The rest of the time its process is paused, so it can't
keep thinking in the background (Q14).
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import asdict

from .rules import TimeLimits
from .view import Game

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
REPLY_LIMIT = 64 * 1024     # longest reply line we read; anything longer is junk
MAX_RESTARTS = 3            # Q13: how many times a dead bot is restarted in one game


class BotProcess:
    """One team's bot, running in its own process for one game."""

    def __init__(self, seat: int, bot_path: str, log_path: str, limits: TimeLimits = TimeLimits()):
        self.seat = seat
        self.bot_path = os.path.abspath(bot_path)
        self.log_path = os.path.abspath(log_path)
        self.limits = limits
        self.proc = None
        self.replies = None         # lines coming back from the bot (filled by a reader thread)
        self.requests = None        # lines going to the bot (sent by a writer thread)
        self.needs_load = True      # the next answer includes loading bot.py: first-turn time
        self.restarts = 0
        self.ended = False          # its output closed: the process is gone (or going)

    # --- starting and stopping ----------------------------------------------------

    def start(self):
        """Start the bot's process. It waits, idle, for its first request."""
        mode = "w" if self.restarts == 0 else "a"
        with open(self.log_path, mode, encoding="utf-8") as f:
            f.write(f"--- seat {self.seat}: {self.bot_path} (start {self.restarts + 1}) ---\n")
        self.proc = subprocess.Popen(
            [sys.executable, "-I", WORKER, self.bot_path, self.log_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(self.log_path),
        )
        self.replies = queue.Queue()
        self.requests = queue.Queue()
        threading.Thread(target=_read_lines, args=(self.proc, self.replies), daemon=True).start()
        threading.Thread(target=_write_lines, args=(self.proc, self.requests), daemon=True).start()
        self.needs_load = True
        self.ended = False

    def stop(self):
        """End the bot's process (end of game)."""
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            _forget(self.proc)

    # --- one turn -------------------------------------------------------------------

    def ask(self, view: Game, turn: int):
        """Ask the bot for its action this turn.

        Returns (action, report). `action` is the string the bot returned, or None if it
        crashed, was late, or isn't running. `report` says what happened, for the game record:
        {"result": "ok" | "error" | "late" | "dead", "ms": ..., "error": ...}
        """
        if self.proc is None or self.ended or self.proc.poll() is not None:
            if self.proc is not None:               # Q13: it died since its last turn
                if self.restarts >= MAX_RESTARTS:
                    return None, {"result": "dead", "ms": 0, "error": "too many restarts"}
                self.restarts += 1
                try:                                # Windows may still be closing it: make sure
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                _forget(self.proc)
            self.start()

        limit_ms = self.limits.first_turn_ms if self.needs_load else self.limits.turn_ms
        started = time.perf_counter()
        deadline = started + limit_ms / 1000
        _resume(self.proc)
        self.requests.put(json.dumps({"turn": turn, "view": asdict(view)}) + "\n")

        while True:
            try:
                line = self.replies.get(timeout=max(deadline - time.perf_counter(), 0))
            except queue.Empty:
                _pause(self.proc)                   # Q12: late. Paused until its next turn
                self.needs_load = False
                return None, {"result": "late", "ms": limit_ms, "error": None}
            if line is None:                        # the process died during its turn
                self.ended = True                   # restart it next turn, even if Windows is slow
                return None, {"result": "dead", "ms": _ms(started), "error": "process ended"}
            try:
                reply = json.loads(line)
                if reply.get("turn") != turn:
                    continue                        # a late answer to an earlier turn: ignore it
            except (ValueError, AttributeError):
                continue                            # junk on the line: ignore it
            ms = _ms(started)
            _pause(self.proc)
            self.needs_load = False
            if reply.get("error"):
                return None, {"result": "error", "ms": ms, "error": reply["error"]}
            return reply.get("action"), {"result": "ok", "ms": ms, "error": None}


def _read_lines(proc, replies):
    """Background thread: pass every line the bot process writes to `replies`.
    A None at the end means the process has died."""
    while True:
        line = proc.stdout.readline(REPLY_LIMIT)
        if not line:
            break
        replies.put(line)
    replies.put(None)


def _write_lines(proc, requests):
    """Background thread: send each request to the bot process. Done here, not in ask(),
    so that a bot stuck in a loop (not reading) can never block the server."""
    while True:
        line = requests.get()
        try:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
        except OSError:
            return                                  # the process has ended


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


# --- pausing and resuming a process --------------------------------------------------
# Windows has no simple built-in for this, so we call the system directly through ctypes.
# Elsewhere (Linux, macOS) the STOP and CONT signals do the same job.

if os.name == "nt":
    import ctypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    _ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    _PROCESS_SUSPEND_RESUME = 0x0800
    _handles = {}

    def _handle(proc):
        if proc.pid not in _handles:
            _handles[proc.pid] = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, proc.pid)
        return _handles[proc.pid]

    def _pause(proc):
        if proc.poll() is None:
            _ntdll.NtSuspendProcess(_handle(proc))

    def _resume(proc):
        if proc.poll() is None:
            _ntdll.NtResumeProcess(_handle(proc))

    def _forget(proc):
        if proc.pid in _handles:
            _kernel32.CloseHandle(_handles.pop(proc.pid))

else:
    import signal

    def _pause(proc):
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGSTOP)

    def _resume(proc):
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGCONT)

    def _forget(proc):
        pass
