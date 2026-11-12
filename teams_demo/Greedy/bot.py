turns_seen = 0          # a global: should keep counting for the whole game

def act(state):
    global turns_seen
    turns_seen += 1
    if turns_seen % 20 == 0:
        print("greedy: I have seen", turns_seen, "turns")
    me = next((r, c) for r in range(8) for c in range(8) if state.board[r][c].occupant == state.bot_id)
    cell = state.board[me[0]][me[1]]
    if cell.owner != state.bot_id and not cell.is_home and "STAY" in state.legal_actions:
        return "STAY"
    best, best_val = "STAY", -1
    for a, (dr, dc) in {"NORTH": (-1, 0), "EAST": (0, 1), "SOUTH": (1, 0), "WEST": (0, -1)}.items():
        if a in state.legal_actions:
            t = state.board[me[0] + dr][me[1] + dc]
            v = t.base_points if t.owner != state.bot_id else 0
            if v > best_val:
                best, best_val = a, v
    return best
