"""Overhead camera check (Q19): robots are tracked by their ArUco markers.

After every turn (and before the first one, and after every pause) the server takes a picture
of the arena, finds every marker, and checks that each robot is on the cell the server says,
facing the way the server thinks. Anything else is a robot fault: the game pauses and the
referee puts the robot right (4.4).

How the camera knows where the board is: four extra markers (default ids 40, 41, 42, 43) sit
just outside the board's corners: top-left, top-right, bottom-right, bottom-left, as seen with
row 0 at the top. Their centres are `corner_offset` cells outside the board's corner points
(0.5 = half a cell out, diagonally). From them the camera works out the board in every picture,
so a bumped camera doesn't matter. Each robot marker is stuck on flat, with its printed "FRONT"
edge pointing to the robot's front.

Camera config (in the robot config, optional):
    "camera": {
      "source": 0,                  webcam number, a video URL, an image file, or "sim"
      "corner_markers": [40, 41, 42, 43],
      "corner_offset": 0.5,         cells outside each board corner, diagonally
      "cell_tolerance": 0.35,       how far (in cells) a marker may sit from its cell's centre
      "heading_tolerance": 35,      degrees a robot may be off straight
      "settle_s": 0.3               wait after the robots stop before taking the picture
    }
"""
import math
import threading
import time

HEADING_ANGLE = {"N": 0, "E": 90, "S": 180, "W": 270}
DICTIONARY = "DICT_4X4_50"


def _cv():
    import cv2                       # OpenCV is only needed when a camera is used
    return cv2


class ArenaView:
    """Turns one camera picture into marker positions on the board.

    Board coordinates: x = column, y = row, in cells; cell (r, c) covers x in [c, c+1] and
    y in [r, r+1], so its centre is (c + 0.5, r + 0.5)."""

    def __init__(self, corner_ids=(40, 41, 42, 43), corner_offset: float = 0.5):
        import numpy as np
        cv2 = _cv()
        self.corner_ids = [int(i) for i in corner_ids]
        o = corner_offset
        self.board_corners = np.float32([[-o, -o], [8 + o, -o], [8 + o, 8 + o], [-o, 8 + o]])
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTIONARY))
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        self.homography = None               # picture -> board; kept from the last good picture

    def read(self, image):
        """Returns (board_found, {marker_id: {"row": y, "col": x, "angle": degrees}}).
        angle is where the marker's FRONT edge points: 0 = north (row - 1), 90 = east."""
        import numpy as np
        cv2 = _cv()
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        found = {} if ids is None else {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners)}

        if all(i in found for i in self.corner_ids):
            centres = np.float32([found[i].mean(axis=0) for i in self.corner_ids])
            self.homography = cv2.getPerspectiveTransform(centres, self.board_corners)
        if self.homography is None:
            return False, {}

        markers = {}
        for marker_id, pts in found.items():
            if marker_id in self.corner_ids:
                continue
            front = (pts[0] + pts[1]) / 2           # aruco corner order: TL, TR, BR, BL
            back = (pts[2] + pts[3]) / 2
            board = cv2.perspectiveTransform(
                np.float32([pts.mean(axis=0), front, back]).reshape(-1, 1, 2), self.homography).reshape(-1, 2)
            (x, y), (fx, fy), (bx, by) = board
            angle = math.degrees(math.atan2(fx - bx, -(fy - by))) % 360
            markers[marker_id] = {"row": float(y), "col": float(x), "angle": float(angle)}
        return True, markers


def check_robots(markers: dict, expected: dict, cell_tolerance: float, heading_tolerance: float):
    """expected: seat -> (marker id, (row, col), heading). Returns str(seat) -> result:
        {"result": "ok"}
        {"result": "not_seen"}
        {"result": "wrong_cell" | "wrong_heading", "seen": [row, col], "facing": "E", ...}"""
    results = {}
    for seat, (marker_id, pos, heading) in expected.items():
        m = markers.get(marker_id)
        if m is None:
            results[str(seat)] = {"result": "not_seen", "marker": marker_id}
            continue
        cell = [math.floor(m["row"]), math.floor(m["col"])]
        off_centre = max(abs(m["row"] - (cell[0] + 0.5)), abs(m["col"] - (cell[1] + 0.5)))
        seen_heading = min(HEADING_ANGLE, key=lambda h: _angle_gap(m["angle"], HEADING_ANGLE[h]))
        info = {"seen": cell, "facing": seen_heading, "angle": round(m["angle"]),
                "at": [round(m["row"], 2), round(m["col"], 2)]}
        if tuple(cell) != tuple(pos) or off_centre > cell_tolerance:
            results[str(seat)] = {"result": "wrong_cell", **info}
        elif _angle_gap(m["angle"], HEADING_ANGLE[heading]) > heading_tolerance:
            results[str(seat)] = {"result": "wrong_heading", **info}
        else:
            results[str(seat)] = {"result": "ok", **info}
    return results


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


# --- picture sources ------------------------------------------------------------------------

class LiveCamera:
    """A webcam (or video URL). A background thread keeps only the newest picture, so a check
    never looks at an old one."""

    def __init__(self, source):
        cv2 = _cv()
        self.capture = (cv2.VideoCapture(source, cv2.CAP_DSHOW) if isinstance(source, int)
                        else cv2.VideoCapture(source))
        if not self.capture.isOpened():
            raise OSError(f"camera {source!r} can't be opened")
        self._frame = None
        self._stamp = 0.0
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._grab, daemon=True).start()

    def _grab(self):
        while self._running:
            ok, frame = self.capture.read()
            if ok:
                with self._lock:
                    self._frame, self._stamp = frame, time.monotonic()
            else:
                time.sleep(0.05)

    def picture(self, newer_than: float = 0.0, timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None and self._stamp > newer_than:
                    return self._frame.copy()
            time.sleep(0.02)
        raise OSError("no picture from the camera")

    def close(self):
        self._running = False
        self.capture.release()


class FileCamera:
    """A fixed picture from a file (for testing the camera setup with a photo)."""

    def __init__(self, path):
        self.image = _cv().imread(path)
        if self.image is None:
            raise OSError(f"can't read picture {path!r}")

    def picture(self, newer_than: float = 0.0, timeout: float = 2.0):
        return self.image.copy()

    def close(self):
        pass


class SimCamera:
    """Draws the arena as an overhead camera would see it, from where the robots are believed
    to be, with a slight perspective tilt and noise. For testing without a camera.
    `misplace[marker_id] = (row, col, heading)` puts a robot somewhere else, to test faults."""

    def __init__(self, positions, corner_ids=(40, 41, 42, 43), corner_offset: float = 0.5):
        self.positions = positions           # callable -> {marker_id: ((row, col), heading)}
        self.corner_ids = list(corner_ids)
        self.corner_offset = corner_offset
        self.misplace = {}

    def picture(self, newer_than: float = 0.0, timeout: float = 2.0):
        import numpy as np
        cv2 = _cv()
        cell, margin = 70, 110
        size = 8 * cell + 2 * margin
        img = np.full((size, size), 235, np.uint8)
        to_px = lambda x, y: (int(round(margin + x * cell)), int(round(margin + y * cell)))
        for i in range(9):                                       # the grid
            cv2.line(img, to_px(0, i), to_px(8, i), 120, 2)
            cv2.line(img, to_px(i, 0), to_px(i, 8), 120, 2)
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTIONARY))
        o = self.corner_offset
        for marker_id, (x, y) in zip(self.corner_ids, [(-o, -o), (8 + o, -o), (8 + o, 8 + o), (-o, 8 + o)]):
            self._paste(img, cv2.aruco.generateImageMarker(dictionary, marker_id, 56), to_px(x, y))
        placed = {m: (pos[0] + 0.5, pos[1] + 0.5, heading)
                  for m, (pos, heading) in self.positions().items()}
        placed.update(self.misplace)
        turns = {"N": 0, "E": -1, "S": 2, "W": 1}                # np.rot90 k: E = clockwise
        for marker_id, (row, col, heading) in placed.items():
            marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 44)
            self._paste(img, np.rot90(marker, turns[heading]), to_px(col, row))
        src = np.float32([[0, 0], [size, 0], [size, size], [0, size]])
        dst = np.float32([[25, 10], [size - 15, 30], [size - 30, size - 5], [5, size - 25]])
        img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (size, size),
                                  borderValue=235)
        noise = np.random.default_rng(0).normal(0, 6, img.shape)
        return np.clip(img + noise, 0, 255).astype(np.uint8)

    @staticmethod
    def _paste(img, marker, centre):
        h, w = marker.shape
        x0, y0 = centre[0] - w // 2, centre[1] - h // 2
        pad = 6
        img[y0 - pad:y0 + h + pad, x0 - pad:x0 + w + pad] = 255   # white border around it
        img[y0:y0 + h, x0:x0 + w] = marker

    def close(self):
        pass


def open_camera(source, positions, corner_ids, corner_offset):
    if source == "sim":
        return SimCamera(positions, corner_ids, corner_offset)
    if isinstance(source, int) or str(source).isdigit():
        return LiveCamera(int(source))
    if str(source).lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
        return FileCamera(source)
    return LiveCamera(source)                                     # a video URL


class ArenaCamera:
    """The camera check used by the fleet."""

    def __init__(self, config: dict, positions):
        self.corner_ids = config.get("corner_markers", [40, 41, 42, 43])
        self.corner_offset = config.get("corner_offset", 0.5)
        self.cell_tolerance = config.get("cell_tolerance", 0.35)
        self.heading_tolerance = config.get("heading_tolerance", 35)
        self.settle_s = config.get("settle_s", 0.3)
        self.view = ArenaView(self.corner_ids, self.corner_offset)
        self.source = open_camera(config.get("source", 0), positions, self.corner_ids,
                                  self.corner_offset)

    def check(self, expected: dict, tries: int = 5):
        """Look at the arena and compare with `expected` (seat -> (marker, pos, heading)).
        Takes a few pictures if a marker is missing (someone's hand, a reflection)."""
        time.sleep(self.settle_s)
        stamp = time.monotonic()
        results = {}
        for _ in range(tries):
            image = self.source.picture(newer_than=stamp)
            stamp = time.monotonic()
            board, markers = self.view.read(image)
            if not board:
                results = {str(s): {"result": "board_not_seen"} for s in expected}
                continue
            results = check_robots(markers, expected, self.cell_tolerance, self.heading_tolerance)
            if all(r["result"] != "not_seen" for r in results.values()):
                break
        return results

    def close(self):
        self.source.close()
