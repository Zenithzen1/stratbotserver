"""Which actions a bot may take this turn (rulebook 2.3, 2.6, 2.8; README)."""
from .rules import Rules
from .state import MatchState

# The six actions, in the order the README lists them. Keep this order stable:
# bots may rely on the order of state.legal_actions.
ACTIONS = ("NORTH", "EAST", "SOUTH", "WEST", "STAY", "SHIELD")

# How each move changes (row, col). README: NORTH = row - 1, SOUTH = row + 1,
# WEST = col - 1, EAST = col + 1.
MOVES = {
    "NORTH": (-1, 0),
    "EAST": (0, 1),
    "SOUTH": (1, 0),
    "WEST": (0, -1),
}


def move_target(pos: tuple[int, int], action: str) -> tuple[int, int]:
    """The cell a move would land on. It may be off the board; callers check."""
    dr, dc = MOVES[action]
    return (pos[0] + dr, pos[1] + dc)


def legal_actions(state: MatchState, seat: int, rules: Rules = Rules()) -> list[str]:
    """The actions `seat` may take this turn, in README order. Never empty."""
    bot = state.bots[seat]

    if bot.frozen_for > 0:
        return ["STAY"]                                   # 2.6 frozen: only STAY

    legal = []
    for action in MOVES:                                  # NORTH, EAST, SOUTH, WEST
        r, c = move_target(bot.pos, action)
        if not state.in_bounds(r, c):
            continue                                      # README: no moves off
        if state.occupant(r, c) and not rules.occupied_moves_are_legal:
            continue                                      # only if Q9 is switch
        legal.append(action)

    legal.append("STAY")                                  # README: always available
    if bot.cooldown == 0:
        legal.append("SHIELD")                            # 2.6 not while cooling down
    return legal
