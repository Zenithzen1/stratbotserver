"""Reading and checking map files.

A map file is plain text: 8 rows of 8 cell values, each 1, 2 or 3.
Spaces between values are optional. Blank lines and anything after '#' are ignored.
"""
from pathlib import Path

from .state import SIZE


class MapError(ValueError):
    """A map file is malformed or breaks the rulebook (2.1)."""


def parse_map(text: str) -> tuple[tuple[int, ...], ...]:
    """Turn map text into an 8x8 grid. Checks the format only, not mirroring."""
    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.split("#", 1)[0]          # drop comments
        line = "".join(line.split())          # drop all spaces and tabs
        if not line:
            continue                          # blank or comment-only line
        if any(ch not in "123" for ch in line):
            raise MapError(f"line {line_no}: only 1, 2 and 3 are allowed, got {line!r}")
        if len(line) != SIZE:
            raise MapError(f"line {line_no}: expected {SIZE} values, got {len(line)}")
        rows.append(tuple(int(ch) for ch in line))

    if len(rows) != SIZE:
        raise MapError(f"expected {SIZE} rows, got {len(rows)}")
    return tuple(rows)


def check_mirrored(grid) -> None:
    """Rulebook 2.1: every map is mirrored left-right and top-bottom."""
    last = SIZE - 1
    for r in range(SIZE):
        for c in range(SIZE):
            v = grid[r][c]
            if grid[r][last - c] != v:
                raise MapError(f"not mirrored left-right: ({r},{c}) is {v} "
                               f"but ({r},{last - c}) is {grid[r][last - c]}")
            if grid[last - r][c] != v:
                raise MapError(f"not mirrored top-bottom: ({r},{c}) is {v} "
                               f"but ({last - r},{c}) is {grid[last - r][c]}")


def load_map(path) -> tuple[tuple[int, ...], ...]:
    """Read a map file, check its format and mirroring, and return the grid."""
    text = Path(path).read_text(encoding="utf-8")
    grid = parse_map(text)
    check_mirrored(grid)
    return grid