"""Printable ArUco markers.

  * One unique marker per seat, stuck flat on top of that seat's robot with the side labelled
    FRONT towards the robot's front (the camera reads the robot's heading from it).
  * Four corner markers (default ids 40-43) placed just outside the board's corners, so the
    camera can find the board (see camera.py).

Markers come from OpenCV's 4x4 dictionary (DICT_4X4_50), ids 0-49.

    python -m zonerush markers config/robots.json --out markers --size-mm 80
writes PNG files at 300 dpi: print at 100% scale ("actual size").
"""
import os

DICTIONARY = "DICT_4X4_50"
DPI = 300
CORNER_NAMES = ["top-left", "top-right", "bottom-right", "bottom-left"]


def make_marker_png(marker_id: int, size_mm: float, path: str, top: str, bottom: str):
    import cv2
    import numpy as np

    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, DICTIONARY))
    side = round(size_mm / 25.4 * DPI)                    # marker size in pixels at 300 dpi
    marker = aruco.generateImageMarker(dictionary, marker_id, side)
    margin = side // 6                                    # white quiet zone around the marker
    band = side // 5                                      # room for the labels
    page = np.full((side + 2 * margin + 2 * band, side + 2 * margin), 255, np.uint8)
    page[band + margin:band + margin + side, margin:margin + side] = marker

    def label(text, y, scale):
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 3)
        cv2.putText(page, text, ((page.shape[1] - w) // 2, y + h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, 0, 3, cv2.LINE_AA)

    label(top, band // 2, side / 500)
    label(bottom, page.shape[0] - band // 2, side / 900)
    if not cv2.imwrite(path, page):
        raise OSError(f"couldn't write {path}")


def make_markers(seat_ids: dict, out_dir: str, size_mm: float = 80.0, corner_ids=None) -> list:
    """seat -> marker id, and optionally the four corner marker ids. Returns the PNG paths."""
    ids = list(seat_ids.values()) + list(corner_ids or [])
    if len(set(ids)) != len(ids):
        raise ValueError("every marker needs a different id")
    if any(not 0 <= i < 50 for i in ids):
        raise ValueError(f"{DICTIONARY} has ids 0-49")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for seat, marker_id in sorted(seat_ids.items()):
        path = os.path.join(out_dir, f"seat{seat}_marker{marker_id}.png")
        make_marker_png(marker_id, size_mm, path, "^ FRONT ^",
                        f"Seat {seat} robot - id {marker_id} - {size_mm:g} mm - this edge faces the front")
        paths.append(path)
    for name, marker_id in zip(CORNER_NAMES, corner_ids or []):
        path = os.path.join(out_dir, f"corner_{name}_marker{marker_id}.png")
        make_marker_png(marker_id, size_mm, path, "^ TOWARDS ROW 0 ^",
                        f"Board corner {name} - id {marker_id} - {size_mm:g} mm")
        paths.append(path)
    return paths
