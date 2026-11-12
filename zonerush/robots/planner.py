"""Turns a move on the board into robot steps.

A tank robot can only drive straight or turn on the spot, so a move "one cell north" becomes
"turn to face north, then forward one cell". The server keeps track of which way each robot is
facing (its heading): N, E, S or W, with north = up the board (row - 1), as in the README.

    facing the way it needs to go     -> F
    needs to go the way it came from  -> B (drive backwards; no turn) if allowed, else R R F
    needs to go left / right of it    -> L F / R F
"""
HEADINGS = ("N", "E", "S", "W")                      # clockwise
DELTA = {"N": (-1, 0), "E": (0, 1), "S": (1, 0), "W": (0, -1)}


def direction(frm, to) -> str:
    """The heading of a one-cell move from `frm` to `to`."""
    step = (to[0] - frm[0], to[1] - frm[1])
    for heading, delta in DELTA.items():
        if delta == step:
            return heading
    raise ValueError(f"{tuple(frm)} -> {tuple(to)} is not a one-cell move")


def plan_move(heading: str, frm, to, allow_reverse: bool = True):
    """Steps to move one cell. Returns (steps, heading afterwards), e.g. (["L", "F"], "W")."""
    want = direction(frm, to)
    turn = (HEADINGS.index(want) - HEADINGS.index(heading)) % 4   # quarter turns clockwise
    if turn == 0:
        return ["F"], heading
    if turn == 2:
        return (["B"], heading) if allow_reverse else (["R", "R", "F"], want)
    return (["R", "F"] if turn == 1 else ["L", "F"]), want
