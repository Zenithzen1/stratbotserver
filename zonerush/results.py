"""Final placings of a game.

2.7: after 80 turns the highest total wins, and equal totals share a place.
5.3 (Round 2): on the same score, the bot that owns more cells at the end ranks higher.
(5.3 step 3, "the team that finished higher in Round 1", is a tournament matter, not a game one.)
"""
from .state import SEATS, SIZE, MatchState


def cells_owned(state: MatchState) -> dict:
    """Seat -> number of cells it owns (home included)."""
    counts = {seat: 0 for seat in SEATS}
    for r in range(SIZE):
        for c in range(SIZE):
            if state.owner[r][c]:
                counts[state.owner[r][c]] += 1
    return counts


def placings(state: MatchState, cells_tiebreak: bool = True) -> dict:
    """Seat -> place (1 to 4). Seats that are still level share a place, and the next place is
    skipped: scores 412, 380, 380, 201 give places 1, 2, 2, 4.

    cells_tiebreak=True  : Round 2 (5.3), score first, then cells owned.
    cells_tiebreak=False : 2.7 only, score alone.
    """
    cells = cells_owned(state)

    def key(seat):
        return (state.bots[seat].score, cells[seat] if cells_tiebreak else 0)

    return {seat: 1 + sum(1 for other in SEATS if key(other) > key(seat)) for seat in SEATS}
