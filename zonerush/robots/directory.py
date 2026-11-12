"""Finding each team's robot automatically.

Every robot says who it is: the ROBOT_NAME in its sketch is its team's name, and the robot
answers the server's hello with it. So the server never needs to be told which Bluetooth
device belongs to which team:

  1. scan for robot-like Bluetooth devices (an HM-10 style serial service, FFE0, or an HM-10
     style name),
  2. connect to each one, ask its name, disconnect,
  3. pair it with the team of that name. Names match ignoring case, spaces and punctuation,
     so "Team Krauts", "TEAM-KRAUTS" and "teamkrauts" are the same name.

What was found is remembered in config/robots.found.json (name -> Bluetooth address), so next
time the server tries the remembered address first and only scans again if that fails. Every
connection is still checked against the name (fleet.py), so a stale or wrong address can never
make the wrong robot play a team's moves.
"""
import json
import os
import re
import threading
import time

from .links import UART_SERVICE, BleLink, LinkError, _AsyncLoop, _need
from .protocol import RobotClient, RobotError

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "config", "robots.found.json")
HM10_NAMES = ("hmsoft", "bt05", "mltbt05", "jdy", "zr", "hm10", "cc41", "bt04")


def same_name(a: str, b: str) -> bool:
    return norm(a) == norm(b)


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


async def _scan(timeout: float):
    """Robot-like devices in range: list of (advertised name, address)."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    robots = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        services = [u.lower() for u in (adv.service_uuids or [])]
        if UART_SERVICE in services or norm(name).startswith(HM10_NAMES):
            robots.append((name, device.address))
    return robots


def identify(address: str):
    """Connect to one device, ask its robot name, disconnect. Returns the name or None."""
    link = BleLink(address=address, scan_timeout=5.0)
    try:
        link.open()
        name, _firmware = RobotClient(link, ack_timeout=1.5, retries=1).hello()
        return name
    except (LinkError, RobotError, OSError):
        return None
    finally:
        link.close()


class RobotDirectory:
    """Robot name -> Bluetooth address, found by scanning and remembered between runs."""

    def __init__(self, log=print):
        self.log = log
        self.found = {}                    # norm(name) -> {"name": ..., "address": ...}
        self._lock = threading.Lock()
        self._scanned_at = 0.0
        try:
            with open(CACHE, encoding="utf-8") as f:
                self.found = json.load(f)
        except (OSError, ValueError):
            pass

    def lookup(self, name: str):
        entry = self.found.get(norm(name))
        return entry["address"] if entry else None

    def forget(self, name: str):
        with self._lock:
            if self.found.pop(norm(name), None) is not None:
                self._scanned_at = 0.0          # the next lookup may scan again straight away
                self._save()

    def refresh(self, scan_timeout: float = 6.0, min_gap: float = 20.0):
        """Scan, identify every robot in range, and remember them. Skipped if a scan ran in
        the last `min_gap` seconds (several robots asking at once share one scan)."""
        _need("bleak", "Bluetooth")
        with self._lock:
            if time.monotonic() - self._scanned_at < min_gap:
                return self.found
            self.log("Scanning for robots...")
            for adv_name, address in _AsyncLoop.run(_scan(scan_timeout), timeout=scan_timeout + 20):
                name = identify(address)
                if name:
                    self.found[norm(name)] = {"name": name, "address": address}
                    self.log(f"  found robot {name} ({address})")
            self._scanned_at = time.monotonic()
            self._save()
            return self.found

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(self.found, f, indent=2)
        except OSError:
            pass


class AutoBleLink(BleLink):
    """A Bluetooth link to "the robot called <identity>", wherever it is: it uses the
    remembered address, and scans for it if that doesn't work."""

    def __init__(self, identity: str, directory: RobotDirectory):
        super().__init__(address="unknown")
        self.identity = identity
        self.directory = directory
        self.address = None

    def __str__(self):
        return f"Bluetooth robot {self.identity!r}" + (f" ({self.address})" if self.address else "")

    def open(self):
        address = self.directory.lookup(self.identity)
        if address:
            self.address = address
            try:
                return super().open()
            except LinkError:
                self.directory.forget(self.identity)     # moved or switched off: look again
        self.directory.refresh()
        address = self.directory.lookup(self.identity)
        if not address:
            raise LinkError(f"no robot called {self.identity!r} found (is it switched on, in range, "
                            f"and is its ROBOT_NAME the team's name?)")
        self.address = address
        super().open()
