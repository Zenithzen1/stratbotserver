# Raider: a test opponent for Zone Rush.
# Goes after rivals' cells first (raid bonus = 8 x points x level), otherwise the most valuable
# cells it can reach. Rarely shields. Remembers blocked moves and cells where it got frozen, so it
# doesn't get stuck. Standard library only; paste it in as bot.py.

from collections import deque

SIZE = 8
MOVES = {"NORTH": (-1, 0), "EAST": (0, 1), "SOUTH": (1, 0), "WEST": (0, -1)}

turn = 0
last_pos = None
last_action = None
stay_count = 0          # turns in a row we have stayed on the current cell
was_frozen = False
blocked = {}            # cell -> turn until which we don't try to move into it
avoid = {}              # cell -> turn until which we don't try to take it


def act(state): # Do not change or modify this function signature
    global turn, last_pos, last_action, stay_count, was_frozen
    turn += 1
    pos = my_position(state)
    frozen = cell_at(state, pos).is_frozen

    # Learn from last turn: always trust state, not what we asked for.
    if last_action in MOVES and pos == last_pos and not frozen:
        blocked[target(pos, last_action)] = turn + 2          # that move was blocked
    if frozen and not was_frozen:
        avoid[pos] = turn + 12                                # caught here: try elsewhere
    stay_count = stay_count + 1 if (pos == last_pos and last_action == "STAY") else 0
    was_frozen = frozen

    action = choose(state, pos, frozen)
    if action not in state.legal_actions:
        action = "STAY"
    last_pos, last_action = pos, action
    return action


def choose(state, pos, frozen):
    if frozen:
        return "STAY"
    me = state.bot_id
    # Shield only to protect an upgraded cell a rival is standing on.
    if "SHIELD" in state.legal_actions:
        for r in range(SIZE):
            for c in range(SIZE):
                cell = state.board[r][c]
                if (cell.owner == me and cell.is_upgraded and cell.occupant
                        and cell.occupant != me and not cell.is_frozen):
                    return "SHIELD"

    best, best_score = None, 0.0
    for cell_pos, (dist, first) in reachable(state, pos).items():
        value, stays = worth(state, cell_pos, me)
        if value <= 0:
            continue
        if cell_pos == pos:
            stays = max(1, stays - stay_count)                # we are part-way through
        score = value / (dist + stays)
        if score > best_score:
            best, best_score = (cell_pos, first), score
    if best is None:
        return "STAY"
    cell_pos, first = best
    return "STAY" if cell_pos == pos else first


def worth(state, pos, me):
    """(value, stays needed) of taking this cell, for a raider."""
    if avoid.get(pos, 0) > turn:
        return 0, 0
    cell = cell_at(state, pos)
    if cell.is_home or cell.owner == me:
        return 0, 0
    if cell.owner == 0:
        return cell.base_points, 1                            # neutral
    level = 2 if cell.is_upgraded else 1
    bonus = 8 * cell.base_points * level                      # raid bonus
    return cell.base_points + bonus / 4, (3 if level == 2 else 1)


def reachable(state, start):
    """Every cell we can walk to: cell -> (steps, first action). Cells with a bot on them and
    cells we were just blocked from are treated as walls."""
    seen = {start: (0, None)}
    queue = deque([start])
    while queue:
        pos = queue.popleft()
        dist, first = seen[pos]
        for action, (dr, dc) in MOVES.items():
            nxt = (pos[0] + dr, pos[1] + dc)
            if not on_board(nxt) or nxt in seen:
                continue
            if cell_at(state, nxt).occupant or blocked.get(nxt, 0) > turn:
                continue
            if dist == 0 and action not in state.legal_actions:
                continue
            seen[nxt] = (dist + 1, first or action)
            queue.append(nxt)
    return seen


def my_position(state):
    for r in range(SIZE):
        for c in range(SIZE):
            if state.board[r][c].occupant == state.bot_id:
                return (r, c)


def cell_at(state, pos):
    return state.board[pos[0]][pos[1]]


def target(pos, action):
    dr, dc = MOVES[action]
    return (pos[0] + dr, pos[1] + dc)


def on_board(pos):
    return 0 <= pos[0] < SIZE and 0 <= pos[1] < SIZE
