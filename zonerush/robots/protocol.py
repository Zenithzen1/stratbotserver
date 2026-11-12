"""The robot protocol (version 1): short text lines, one message per line.

Server -> robot:   "<seq> <command>"          e.g. "17 F"
Robot  -> server:  "<seq> <reply> [detail]"   e.g. "17 ACK", then "17 DONE"

Every command has a new sequence number <seq> (1, 2, 3, ... for one connection).

Commands
    H   hello: who are you?     -> "<seq> HELLO <name> <firmware>"  (starts a new session)
    A   arm: allow motion        -> "<seq> OK"
    X   stop now and disarm      -> "<seq> OK"
    P   ping                     -> "<seq> OK"
    F   forward one cell         -> "<seq> ACK" when it starts, "<seq> DONE" when it has stopped
    B   back one cell            -> same
    L   turn left 90 degrees     -> same
    R   turn right 90 degrees    -> same

Errors: "<seq> ERR DISARMED" (a motion command while not armed), "<seq> ERR BUSY" (already
moving), "<seq> ERR UNKNOWN" (not a command).

Safety rules the firmware follows:
  * It never moves on its own. Motion only happens on F/B/L/R, and only while armed.
  * If it hears nothing from the server for 5 seconds it stops and disarms (watchdog). The
    server pings every robot about once a second, so this only happens if the server or the
    link is gone.
  * Repeating a command with the same <seq> never runs it twice: the robot just repeats its
    answer ("ACK" if still moving, "DONE" when finished). That makes resending safe over a
    radio link that can drop a message.
"""
import queue
import threading
import time

MOTION = ("F", "B", "L", "R")
WATCHDOG_S = 5.0          # the firmware's watchdog; the server pings well within it


class RobotError(Exception):
    """A robot didn't answer, or answered with an error."""


class RobotClient:
    """Talks to one robot over a link (see links.py). Thread-safe: one request at a time."""

    def __init__(self, link, ack_timeout: float = 1.5, retries: int = 2):
        self.link = link
        self.ack_timeout = ack_timeout
        self.retries = retries
        self.seq = 0
        self.lock = threading.RLock()     # the fleet's keep-alive pings take it too
        self.robot_name = None
        self.firmware = None

    # --- the commands ---------------------------------------------------------------------

    def hello(self):
        """Start a session. Returns (robot name, firmware version)."""
        self.seq = 0
        words = self.request("H")
        if words[0] != "HELLO" or len(words) < 3:
            raise RobotError(f"unexpected answer to hello: {' '.join(words)}")
        self.robot_name, self.firmware = words[1], words[2]
        return self.robot_name, self.firmware

    def arm(self):
        self._expect_ok(self.request("A"))

    def stop(self):
        """Stop now and disarm. Best effort: never raises."""
        try:
            self._expect_ok(self.request("X", retries=0))
        except (RobotError, OSError):
            pass

    def ping(self):
        self._expect_ok(self.request("P"))

    def step(self, command: str, timeout: float) -> float:
        """Run one motion step (F, B, L or R) and wait until the robot reports it has stopped.
        Re-arms once if the robot says it was disarmed (e.g. after a watchdog stop).
        Returns how long it took, in seconds."""
        assert command in MOTION
        started = time.perf_counter()
        words = self.request(command, done_timeout=timeout)
        if words[:2] == ["ERR", "DISARMED"]:
            self.arm()
            words = self.request(command, done_timeout=timeout)
        if words[0] != "DONE":
            raise RobotError(f"{command}: {' '.join(words)}")
        return time.perf_counter() - started

    # --- one request ------------------------------------------------------------------------

    def request(self, command: str, done_timeout: float = None, retries: int = None) -> list:
        """Send a command and return the robot's final answer as a list of words
        (without the sequence number). For motion commands, waits for DONE."""
        retries = self.retries if retries is None else retries
        with self.lock:
            self.seq += 1
            seq = self.seq
            line = f"{seq} {command}"
            self._drain()
            answer = None
            for _ in range(retries + 1):              # send, and resend if nothing comes back
                self.link.write_line(line)
                answer = self._wait(seq, self.ack_timeout)
                if answer is not None:
                    break
            if answer is None:
                raise RobotError(f"no answer to {command!r} after {retries + 1} tries")
            if command not in MOTION or answer[0] != "ACK":
                return answer

            # A motion step has started: wait for DONE. If it doesn't come in time, ask once
            # more with the same seq (the robot just repeats its state; it won't move again).
            answer = self._wait(seq, done_timeout, until=("DONE", "ERR"))
            if answer is None:
                self.link.write_line(line)
                answer = self._wait(seq, self.ack_timeout, until=("DONE", "ERR"))
            if answer is None:
                raise RobotError(f"{command}: started but never reported DONE")
            return answer

    def _wait(self, seq: int, timeout: float, until=None):
        """Wait for an answer to `seq`. Answers to older commands are skipped.
        With `until`, keep waiting until one of those replies arrives."""
        deadline = time.perf_counter() + timeout
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                return None
            try:
                line = self.link.lines.get(timeout=left)
            except queue.Empty:
                return None
            words = line.split()
            if len(words) < 2 or not words[0].isdigit() or int(words[0]) != seq:
                continue
            if until and words[1] not in until:
                continue
            return words[1:]

    def _drain(self):
        while True:
            try:
                self.link.lines.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _expect_ok(words):
        if words[0] != "OK":
            raise RobotError(" ".join(words))
