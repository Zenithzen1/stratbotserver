"""What a bot sees: the Game and Cell objects described in the starter README.

make_view() builds a fresh copy for one seat at the start of every turn. Nothing a
bot does to its copy can reach the real MatchState (README rule 4).
"""
from dataclasses import dataclass, field

from .legal import legal_actions
from .rules import Rules
from .state import HOME_CELLS, SIZE, MatchState


@dataclass
class Cell:
    """One square of the board, exactly as the README describes it."""
    occupant: int        # seat of the bot standing here, 0 if empty
    owner: int           # seat that owns it, 0 if neutral
    is_upgraded: bool    # level 2: worth double
    is_home: bool        # one of the four corners
    is_frozen: bool      # the bot standing here is frozen (README: bots freeze, not cells)
    base_points: int     # 1, 2 or 3


@dataclass
class Game:
    """The `state` passed to act(state)."""
    board: list = field(repr=False)   # 8x8, board[row][col]; not printed (64 cells)
    bot_id: int                       # this bot's seat, 1-4
    is_priority_token: bool           # does this bot hold the token this turn?
    legal_actions: list               # from legal.py, README order, never empty


def make_view(state: MatchState, seat: int, rules: Rules = Rules()) -> Game:
    """Build what `seat` is allowed to see at the start of this turn."""
    board = []
    for r in range(SIZE):
        row = []
        for c in range(SIZE):
            occupant = state.occupant(r, c)
            row.append(Cell(
                occupant=occupant,
                owner=state.owner[r][c],
                is_upgraded=state.level[r][c] == 2,
                is_home=(r, c) in HOME_CELLS,
                is_frozen=occupant != 0 and state.bots[occupant].frozen_for > 0,
                base_points=state.base_points[r][c],
            ))
        board.append(row)

    return Game(
        board=board,
        bot_id=seat,
        is_priority_token=(state.token == seat),
        legal_actions=legal_actions(state, seat, rules),
    )
