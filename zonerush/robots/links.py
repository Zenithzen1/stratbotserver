"""How messages travel between the server and a robot.

Every link has the same small interface:
    open()              connect (raises LinkError if it can't)
    write_line(text)    send one line
    lines               a queue.Queue of the lines the robot sent back
    connected           True while the link is up
    close()

  BleLink     Bluetooth Low Energy, the way the robots really connect. It speaks to the robot's
              HM-10 style Bluetooth module (or the ESP32 stand-in, which imitates one).
  SerialLink  USB serial, handy for testing a board on the desk.
  SimLink     a robot simulated in software: same protocol and safety rules as the firmware,
              for testing without hardware and for seats that have no robot.
"""
import asyncio
import queue
import sys
import threading
import time

from .protocol import MOTION, WATCHDOG_S

# The HM-10's serial-over-Bluetooth service and characteristic (the ESP32 stand-in uses the same).
UART_SERVICE = "0000ffe0-0000-1000-8000-00805f9b34fb"
UART_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"
BLE_CHUNK = 20                     # bytes per Bluetooth write (the HM-10's packet size)


class LinkError(Exception):
    """Couldn't connect, or the link is down."""


def _need(package: str, purpose: str):
    """Import a package the link needs, or explain which Python is missing it."""
    try:
        return __import__(package)
    except ImportError:
        raise LinkError(f"{purpose} needs the '{package}' package, which this Python doesn't have "
                        f"({sys.executable}). Run the server with the Python that has it "
                        f"(python3.11 on the organisers' laptop), or install it: "
                        f"\"{sys.executable}\" -m pip install {package}") from None


class _LineBuffer:
    """Collects incoming bytes and splits them into lines."""

    def __init__(self, out: queue.Queue):
        self.out = out
        self.buf = ""

    def feed(self, data: bytes):
        self.buf += data.decode("ascii", errors="replace")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.strip()
            if line:
                self.out.put(line)


# --- Bluetooth ----------------------------------------------------------------------------

class _AsyncLoop:
    """bleak (the Bluetooth library) is asyncio-based, the rest of the server isn't. One
    background thread runs an asyncio loop, and we hand it coroutines to run."""
    _loop = None
    _lock = threading.Lock()

    @classmethod
    def run(cls, coro, timeout: float):
        with cls._lock:
            if cls._loop is None:
                cls._loop = asyncio.new_event_loop()
                threading.Thread(target=cls._loop.run_forever, daemon=True).start()
        return asyncio.run_coroutine_threadsafe(coro, cls._loop).result(timeout)


async def ble_scan(timeout: float = 6.0):
    """Every Bluetooth LE device in range: list of (name, address, signal strength)."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    return sorted(((adv.local_name or dev.name or "?", dev.address, adv.rssi)
                   for dev, adv in found.values()), key=lambda d: -d[2])


class BleLink:
    _connect_lock = threading.Lock()   # Windows copes badly with two Bluetooth connects at once

    def __init__(self, name: str = None, address: str = None, scan_timeout: float = 10.0):
        if not name and not address:
            raise ValueError("a Bluetooth robot needs a name or an address")
        self.name = name
        self.address = address
        self.scan_timeout = scan_timeout
        self.lines = queue.Queue()
        self._buffer = _LineBuffer(self.lines)
        self._client = None

    def __str__(self):
        return f"Bluetooth {self.name or self.address}"

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def open(self):
        _need("bleak", "Bluetooth")
        from bleak import BleakClient, BleakScanner

        async def connect():
            if self.address:
                device = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
            else:
                device = await BleakScanner.find_device_by_name(self.name, timeout=self.scan_timeout)
            if device is None:
                raise LinkError(f"{self}: not found (is it powered on and in range?)")
            client = BleakClient(device)
            await client.connect(timeout=15.0)
            await client.start_notify(UART_CHAR, lambda _char, data: self._buffer.feed(bytes(data)))
            self.address = device.address
            return client

        with self._connect_lock:
            try:
                self._client = _AsyncLoop.run(connect(), timeout=self.scan_timeout + 30)
            except LinkError:
                raise
            except Exception as e:                     # bleak raises many different types
                raise LinkError(f"{self}: {type(e).__name__}: {e}") from e

    def write_line(self, text: str):
        if not self.connected:
            raise LinkError(f"{self}: not connected")
        data = (text + "\n").encode("ascii")

        async def send():
            for i in range(0, len(data), BLE_CHUNK):
                await self._client.write_gatt_char(UART_CHAR, data[i:i + BLE_CHUNK], response=False)

        try:
            _AsyncLoop.run(send(), timeout=5)
        except Exception as e:
            raise LinkError(f"{self}: write failed: {e}") from e

    def close(self):
        if self._client is not None:
            try:
                _AsyncLoop.run(self._client.disconnect(), timeout=10)
            except Exception:
                pass
            self._client = None


# --- USB serial -------------------------------------------------------------------------------

class SerialLink:
    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.lines = queue.Queue()
        self._buffer = _LineBuffer(self.lines)
        self._serial = None

    def __str__(self):
        return f"serial {self.port}"

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self):
        _need("serial", "USB serial (package name: pyserial)")
        import serial
        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0.1)
        except serial.SerialException as e:
            raise LinkError(f"{self}: {e}") from e
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while self.connected:
            try:
                data = self._serial.read(256)
            except Exception:
                return
            if data:
                self._buffer.feed(data)

    def write_line(self, text: str):
        if not self.connected:
            raise LinkError(f"{self}: not connected")
        self._serial.write((text + "\n").encode("ascii"))

    def close(self):
        if self._serial is not None:
            self._serial.close()
            self._serial = None


# --- simulated robot ----------------------------------------------------------------------------

class SimLink:
    """A robot simulated in software. It follows the same rules as the firmware: numbered
    commands, ACK then DONE, repeats instead of re-running, armed-only motion, watchdog.

    For tests you can make it misbehave: set `fail_next` to "no_done" (the next step never
    finishes) or "offline" (it stops answering altogether)."""

    def __init__(self, name: str = "SIM", step_s: float = 0.05, turn_s: float = 0.04):
        self.name = name
        self.step_s = step_s
        self.turn_s = turn_s
        self.lines = queue.Queue()
        self.fail_next = None
        self.log = []                       # motion steps actually run, for tests
        self._up = False
        self._lock = threading.Lock()
        self._armed = False
        self._last_seq = 0
        self._last_reply = ""
        self._motion_seq = 0
        self._motion_state = ""             # "ACK" while moving, "DONE" when finished
        self._heard = time.monotonic()
        self._offline = False

    def __str__(self):
        return f"simulated {self.name}"

    @property
    def connected(self) -> bool:
        return self._up

    def open(self):
        self._up = True
        self._offline = False
        threading.Thread(target=self._watchdog, daemon=True).start()

    def close(self):
        self._up = False

    def write_line(self, text: str):
        if not self._up:
            raise LinkError(f"{self}: not connected")
        if self._offline:
            return
        with self._lock:
            self._heard = time.monotonic()
            self._handle(text.split())

    def _reply(self, seq, text):
        self.lines.put(f"{seq} {text}")

    def _handle(self, words):
        if len(words) != 2 or not words[0].isdigit():
            return
        seq, cmd = int(words[0]), words[1]
        if cmd == "H":                                         # new session
            self._last_seq, self._motion_seq = seq, 0
            self._last_reply = f"HELLO {self.name} sim-1"
            self._reply(seq, self._last_reply)
            return
        if seq == self._motion_seq:                            # repeat: report, don't re-run
            self._reply(seq, self._motion_state)
            return
        if seq == self._last_seq:
            self._reply(seq, self._last_reply)
            return
        if seq < self._last_seq:
            return                                             # stale: ignore
        self._last_seq = seq
        if cmd in ("A", "X", "P"):
            self._armed = cmd == "A" or (cmd == "P" and self._armed)
            if cmd == "X" and self._motion_state == "ACK":
                self._motion_state = "ERR STOPPED"            # stop cancels a running step
            self._last_reply = "OK"
        elif cmd in MOTION:
            if not self._armed:
                self._last_reply = "ERR DISARMED"
            elif self._motion_state == "ACK":
                self._last_reply = "ERR BUSY"
            else:
                if self.fail_next == "offline":
                    self.fail_next = None
                    self._offline = True
                    return
                self._motion_seq, self._motion_state = seq, "ACK"
                self._reply(seq, "ACK")
                hang = self.fail_next == "no_done"
                self.fail_next = None
                duration = self.step_s if cmd in ("F", "B") else self.turn_s
                if not hang:
                    threading.Timer(duration, self._finish, args=(seq, cmd)).start()
                return
        else:
            self._last_reply = "ERR UNKNOWN"
        self._reply(seq, self._last_reply)

    def _finish(self, seq, cmd):
        with self._lock:
            if self._motion_seq == seq and self._motion_state == "ACK":
                self._motion_state = "DONE"
                self.log.append(cmd)
                self._reply(seq, "DONE")

    def _watchdog(self):
        while self._up:
            time.sleep(0.5)
            with self._lock:
                if self._armed and time.monotonic() - self._heard > WATCHDOG_S:
                    self._armed = False
