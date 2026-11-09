"""The full state of a match: everything the server knows, including what bots never see."""
from dataclasses import dataclass

from .rules import Rules

# --- Fixed facts about the board (set by the README, never change) --------
SIZE = 8
SEATS = (1, 2, 3, 4)
HOMES = {1: (0, 0), 2: (0, 7), 3: (7, 7), 4: (7, 0)}   # Q7: clockwise from top-left
HOME_CELLS = set(HOMES.values())


@dataclass
class BotState:
    """Everything about one seat's bot."""
    seat: int
    pos: tuple[int, int]     # (row, col)
    score: int = 0           # total so far, raid bonuses included
    progress: int = 0        # stays counted on the cell it is standing on
    frozen_for: int = 0      # turns left of forced STAY
    cooldown: int = 0        # turns left before SHIELD is allowed again


@dataclass
class MatchState:
    """The whole game at the start of a turn."""
    base_points: tuple[tuple[int, ...], ...]   # 8x8 map values, never changes
    owner: list[list[int]]                    # seat owning each cell, 0 = neutral
    level: list[list[int]]                    # 1 or 2 (neutral cells stay at 1)
    bots: dict[int, BotState]                 # seat -> its bot
    turn: int = 1                             # the turn about to be played; 81
    token: int = 1                            # seat holding the priority token this turn

    def in_bounds(self, r: int, c: int) -> bool:
        """True if (r, c) is on the board."""
        return 0 <= r < SIZE and 0 <= c < SIZE

    def occupant(self, r: int, c: int) -> int:
        """Seat of the bot standing on (r, c), or 0 if the cell is empty."""
        for seat, bot in self.bots.items():
            if bot.pos == (r, c):
                return seat
        return 0


def new_match(base_points, rules: Rules = Rules()) -> MatchState:
    """Build the state before turn 1 from an 8x8 grid of cell values."""
    if len(base_points) != SIZE or any(len(row) != SIZE for row in base_points):
        raise ValueError("map must be 8 x 8")
    if any(v not in (1, 2, 3) for row in base_points for v in row):
        raise ValueError("every cell must be worth 1, 2 or 3")

    owner = [[0] * SIZE for _ in range(SIZE)]
    level = [[1] * SIZE for _ in range(SIZE)]
    bots = {}
    for seat, (r, c) in HOMES.items():
        owner[r][c] = seat                        # 2.1 you always own your home
        bots[seat] = BotState(seat=seat, pos=(r, c))

    return MatchState(
        base_points=tuple(tuple(row) for row in base_points),
        owner=owner,
        level=level,
        bots=bots,
        turn=1,
        token=rules.first_token_seat,             # Q8
    )
