"""All the robots of one game.

The fleet is told what the engine decided and makes the robots act it out. It only ever moves
a robot for a "move" event, i.e. a move the engine has checked and carried out on the official
board. A blocked move, STAY, SHIELD or an illegal request never produces any motion.

Robot config (JSON):
    {
      "link": "ble",                  default link for every robot: ble, serial or sim
      "step_timeout": 8.0,            seconds a single step (F/B/L/R) may take
      "ack_timeout": 1.5,             seconds to wait for a robot to answer a message
      "allow_reverse": true,          drive backwards instead of turning round
      "robots": {
        "1": {"name": "ZR-ROBOT-1", "marker": 1, "heading": "S"},
        "2": {"address": "AA:BB:CC:DD:EE:FF", "marker": 2},
        "3": {"link": "serial", "port": "COM5"},
        "4": {"link": "auto", "identity": "Krauts"}
      }
    }
  link "auto"     find the robot whose ROBOT_NAME is `identity` (the team's name) by scanning; no
                  Bluetooth name or address needed (see directory.py)
  name / address  how to find a Bluetooth robot (its Bluetooth name, or its address)
  identity        the robot's own name (ROBOT_NAME in its sketch). If given, the server checks
                  it on every connect and refuses any other robot
  marker          the ArUco marker id on top of this seat's robot (see markers.py)
  heading         the way the robot faces when placed on its home (default: towards the
                  middle of the board, so seats 1-2 face S and seats 3-4 face N)
  "camera": {...} optional overhead camera check, see camera.py
"""
import json
import threading
import time

from ..state import HOMES, SEATS
from .links import BleLink, LinkError, SerialLink, SimLink
from .planner import HEADINGS, plan_move
from .protocol import RobotClient, RobotError

HOME_HEADINGS = {1: "S", 2: "S", 3: "N", 4: "N"}


def _same_name(a: str, b: str) -> bool:
    from .directory import same_name
    return same_name(a, b)
KEEPALIVE_S = 1.0


def make_link(seat: int, cfg: dict, default_kind: str, directory=None):
    kind = cfg.get("link", default_kind)
    if kind == "auto":
        from .directory import AutoBleLink
        if not cfg.get("identity"):
            raise ValueError(f"seat {seat}: an automatic robot needs an identity (its team's name)")
        return AutoBleLink(cfg["identity"], directory)
    if kind == "ble":
        return BleLink(name=cfg.get("name"), address=cfg.get("address"))
    if kind == "serial":
        return SerialLink(cfg["port"], cfg.get("baud", 115200))
    if kind == "sim":
        return SimLink(cfg.get("name", f"SIM-{seat}"), cfg.get("step_s", 0.05), cfg.get("turn_s", 0.04))
    raise ValueError(f"seat {seat}: unknown link {kind!r} (use auto, ble, serial or sim)")


class Robot:
    """One seat's robot, and what the server knows about it."""

    def __init__(self, seat: int, cfg: dict, default_kind: str, ack_timeout: float, directory=None):
        self.seat = seat
        self.identity = cfg.get("identity")      # the name this robot must answer with
        self.marker = cfg.get("marker", seat)
        self.home_heading = cfg.get("heading", HOME_HEADINGS[seat])
        if self.home_heading not in HEADINGS:
            raise ValueError(f"seat {seat}: heading must be one of {HEADINGS}")
        self.link = make_link(seat, cfg, default_kind, directory)
        self.client = RobotClient(self.link, ack_timeout=ack_timeout)
        self.pos = HOMES[seat]
        self.heading = self.home_heading
        self.online = False
        self.needs_placing = False         # after a fault: the referee puts it back by hand
        self.gave_up = False               # reconnecting failed; only retried after a pause
        self.camera = None                 # the last camera check of this robot

    def __str__(self):
        return f"seat {self.seat} robot ({self.client.robot_name or self.link})"


class Fleet:
    def __init__(self, config: dict, log=print):
        self.log = log
        self.step_timeout = config.get("step_timeout", 8.0)
        self.allow_reverse = config.get("allow_reverse", True)
        kind = config.get("link", "ble")
        ack = config.get("ack_timeout", 1.5)
        self.directory = None
        if any(cfg.get("link", kind) == "auto" for cfg in config["robots"].values()):
            from .directory import RobotDirectory
            self.directory = RobotDirectory(log)
        self.robots = {int(seat): Robot(int(seat), cfg, kind, ack, self.directory)
                       for seat, cfg in config["robots"].items()}
        for seat in self.robots:
            if seat not in SEATS:
                raise ValueError(f"no such seat: {seat}")
        markers = [robot.marker for robot in self.robots.values()]
        if len(set(markers)) != len(markers):
            raise ValueError("every robot needs a different marker")
        self.camera = None
        if config.get("camera"):
            from .camera import ArenaCamera
            self.camera = ArenaCamera(config["camera"], self._believed_positions)
        self._running = True
        threading.Thread(target=self._keepalive, daemon=True).start()

    @classmethod
    def from_file(cls, path, log=print):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), log)

    # --- connecting -------------------------------------------------------------------------

    def connect(self, skip=()) -> dict:
        """Connect every robot (one at a time). Returns seat -> error message for the ones
        that failed; they can be retried later with prepare()."""
        failed = {}
        for seat, robot in self.robots.items():
            if seat in skip:
                continue
            error = self._connect(robot)
            if error:
                failed[seat] = error
        return failed

    def _connect(self, robot: Robot):
        attempts = 2 if self.directory and robot.identity else 1
        for attempt in range(attempts):
            try:
                if not robot.link.connected:
                    robot.link.open()
                name, firmware = robot.client.hello()
                if robot.identity and not _same_name(name, robot.identity):
                    # Never let another team's robot act out this team's moves.
                    robot.link.close()
                    if self.directory:
                        self.directory.forget(robot.identity)   # look for the right one again
                    if attempt + 1 < attempts:
                        continue
                    raise RobotError(f"this is robot {name!r}, not {robot.identity!r}")
                robot.client.arm()
                break
            except (LinkError, RobotError, OSError) as e:
                robot.online = False
                return str(e)
        robot.online = True
        self.log(f"Seat {robot.seat}: robot {name} connected ({robot.link}, firmware {firmware})")
        return None

    def place_all(self, state):
        """Robots are about to be placed by hand (start of a game, or a resumed game): each one
        goes on its seat's current cell, facing its home heading."""
        for seat, robot in self.robots.items():
            robot.pos = tuple(state.bots[seat].pos)
            robot.heading = robot.home_heading
            robot.needs_placing = False
        return {seat: (robot.pos, robot.heading) for seat, robot in self.robots.items()}

    def prepare(self, state, skip=(), retry=False) -> list:
        """Before a turn: robots the referee has put back after a fault take the server's
        position again, and robots that are offline are reconnected (once; a robot that
        failed to reconnect is only tried again with retry=True, i.e. after the referee had
        a chance to fix it). Returns (seat, problem) for robots that failed to reconnect."""
        problems = []
        for seat, robot in self.robots.items():
            if seat in skip:
                continue
            if robot.needs_placing:
                robot.pos = tuple(state.bots[seat].pos)
                robot.heading = robot.home_heading
                robot.needs_placing = False
            if robot.online and robot.link.connected:
                continue
            robot.online = False
            if robot.gave_up and not retry:
                continue
            error = self._connect(robot)
            robot.gave_up = error is not None
            if error:
                problems.append((seat, f"robot offline ({error})"))
        return problems

    # --- acting out a turn ---------------------------------------------------------------------

    def act_out(self, events: list) -> dict:
        """Make the robots act out the engine's "move" events, all at the same time, and wait
        until they have finished. Returns str(seat) -> report:
            {"result": "ok", "steps": "LF", "seconds": 1.9}
            {"result": "fault", "error": ..., "steps_done": "L", "place_at": [r, c], "facing": "S"}
            {"result": "offline", "place_at": [r, c], "facing": "S"}
        On a fault or an offline robot, the referee must place it by hand (4.4)."""
        moves = {e["seat"]: (tuple(e["from"]), tuple(e["to"]))
                 for e in events if e["type"] == "move" and e["seat"] in self.robots}
        reports = {}
        threads = [threading.Thread(target=lambda s=seat, m=move: reports.__setitem__(
                        str(s), self._act(self.robots[s], *m)))
                   for seat, move in moves.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return reports

    def _act(self, robot: Robot, frm, to) -> dict:
        if not robot.online:
            robot.needs_placing = True
            return {"result": "offline", "place_at": list(to), "facing": robot.home_heading}
        if robot.pos != frm:
            robot.needs_placing = True
            return self._fault(robot, to, f"robot is at {robot.pos}, but the move starts at {frm}", "")

        steps, _ = plan_move(robot.heading, frm, to, self.allow_reverse)
        done = ""
        started = time.perf_counter()
        try:
            for step in steps:
                robot.client.step(step, self.step_timeout)
                done += step
                if step == "L":
                    robot.heading = HEADINGS[(HEADINGS.index(robot.heading) - 1) % 4]
                elif step == "R":
                    robot.heading = HEADINGS[(HEADINGS.index(robot.heading) + 1) % 4]
                else:
                    robot.pos = to
        except (RobotError, LinkError, OSError) as e:
            robot.client.stop()
            robot.needs_placing = True
            if not robot.link.connected:
                robot.online = False
            return self._fault(robot, to, str(e), done)
        return {"result": "ok", "steps": done, "seconds": round(time.perf_counter() - started, 2)}

    @staticmethod
    def _fault(robot, to, error, done):
        return {"result": "fault", "error": error, "steps_done": done,
                "place_at": list(to), "facing": robot.home_heading}

    # --- the camera check (Q19) ---------------------------------------------------------------

    def _believed_positions(self):
        """Where the server believes each robot is: marker -> ((row, col), heading)."""
        return {robot.marker: (robot.pos, robot.heading) for robot in self.robots.values()}

    def verify(self, skip=()) -> dict:
        """Ask the camera whether every robot is where the server believes it is.
        Returns str(seat) -> camera result (see camera.check_robots); {} without a camera."""
        if self.camera is None:
            return {}
        expected = {seat: (robot.marker, robot.pos, robot.heading)
                    for seat, robot in self.robots.items() if seat not in skip}
        results = self.camera.check(expected)
        for seat, result in results.items():
            self.robots[int(seat)].camera = result
        return results

    def describe(self, seat: int, result: dict) -> str:
        """A camera result in words, for the referee."""
        robot = self.robots[seat]
        should = f"it should be on {robot.pos} facing {robot.heading}"
        kind = result["result"]
        if kind == "not_seen":
            return f"the camera can't see its marker ({result['marker']}); {should}"
        if kind == "board_not_seen":
            return "the camera can't see the board's corner markers"
        return f"the camera sees it on {tuple(result['seen'])} facing {result['facing']}; {should}"

    def status(self) -> dict:
        """What the operator's map view shows about each robot."""
        return {str(seat): {"pos": list(robot.pos), "heading": robot.heading,
                            "marker": robot.marker, "online": robot.online,
                            "needs_placing": robot.needs_placing, "camera": robot.camera}
                for seat, robot in self.robots.items()}

    # --- stopping ------------------------------------------------------------------------------

    def stop_all(self):
        """Emergency stop: every robot stops and disarms."""
        for robot in self.robots.values():
            if robot.online:
                robot.client.stop()

    def close(self):
        self._running = False
        self.stop_all()
        for robot in self.robots.values():
            robot.link.close()
            robot.online = False
        if self.camera is not None:
            self.camera.close()

    def _keepalive(self):
        """Ping idle robots about once a second, so their watchdog knows the server is alive."""
        while self._running:
            time.sleep(KEEPALIVE_S)
            for robot in list(self.robots.values()):
                if not robot.online or not robot.client.lock.acquire(blocking=False):
                    continue                        # offline, or busy acting out a move
                try:
                    robot.client.ping()
                except (RobotError, LinkError, OSError):
                    if not robot.link.connected:
                        robot.online = False
                finally:
                    robot.client.lock.release()
