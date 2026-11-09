"""The rules engine: step() plays one turn (rulebook 2.2).

Pure: no I/O, no timing, no randomness. The same input always gives the same output.
"""
import copy

from .legal import MOVES, legal_actions, move_target
from .rules import Rules
from .state import HOME_CELLS, SEATS, SIZE, BotState, MatchState


def seat_order(token: int) -> list[int]:
    """Seats in priority order, starting from the token holder (2.3). token 3 -> [3, 4, 1, 2]."""
    return [(token - 1 + i) % 4 + 1 for i in range(4)]


def is_over(state: MatchState, rules: Rules = Rules()) -> bool:
    """True once all turns have been played (2.1: 80 turns)."""
    return state.turn > rules.turns


def step(state: MatchState, actions: dict, rules: Rules = Rules()):
    """Play one turn. Returns (new_state, events). `state` itself is never changed."""
    if is_over(state, rules):
        raise ValueError("the game is over")
    s = copy.deepcopy(state)              # work on a copy: the old state stays as it was
    events = []

    chosen, frozen = _check_actions(s, actions, rules, events)
    _tick_counters(s)
    outcome = _phase_moves(s, chosen, frozen, rules, events)    # phase 1
    _phase_takes(s, outcome, rules, events)                     # phase 2
    _phase_score(s)                                             # phase 3
    _phase_end(s)                                               # phase 4
    return s, events


def penalise(state: MatchState, seat: int, rules: Rules = Rules()):
    """4.4 time penalty, applied by the referee between turns.

    The bot is frozen for the next 3 turns and its progress resets. It uses the same
    _freeze as a shield, so a penalty freeze behaves exactly like any other freeze
    (Q10: it replaces any freeze already running). Returns (new_state, events).
    """
    if seat not in SEATS:
        raise ValueError(f"no such seat: {seat}")
    s = copy.deepcopy(state)
    _freeze(s.bots[seat], rules.penalty_freeze_turns)
    return s, [{"type": "penalty", "seat": seat, "turns": rules.penalty_freeze_turns}]


def _check_actions(s: MatchState, actions: dict, rules: Rules, events: list):
    """Turn every requested action into one the rules allow.

    2.6: a frozen bot's chosen action is ignored (it STAYs).
    2.8: an illegal action plays STAY. A seat with no action also plays STAY.
    Returns (chosen action per seat, set of seats frozen this turn).
    """
    chosen = {}
    frozen = set()
    for seat in SEATS:
        requested = actions.get(seat, "STAY")
        if s.bots[seat].frozen_for > 0:
            frozen.add(seat)
            chosen[seat] = "STAY"
            if requested != "STAY":
                events.append({"type": "ignored", "seat": seat,
                               "action": requested, "reason": "frozen"})
        elif requested in legal_actions(s, seat, rules):
            chosen[seat] = requested
        else:
            chosen[seat] = "STAY"
            events.append({"type": "ignored", "seat": seat,
                           "action": requested, "reason": "illegal"})
    return chosen, frozen


def _tick_counters(s: MatchState):
    """Q6: this turn uses up one turn of every freeze and every shield cooldown."""
    for bot in s.bots.values():
        bot.frozen_for = max(0, bot.frozen_for - 1)
        bot.cooldown = max(0, bot.cooldown - 1)


def _phase_moves(s: MatchState, chosen: dict, frozen: set, rules: Rules, events: list) -> dict:
    """Phase 1 (2.3, 2.6): bots move or stay, and shields go up.

    Returns what each seat actually did this turn:
    "moved", "blocked", "stay", "shield" or "frozen".
    """
    outcome = {}
    start = {seat: bot.pos for seat, bot in s.bots.items()}
    closed = set(start.values())          # 2.3 cells with a bot on them at the start of the turn
    wants = {}                            # empty target cell -> seats trying to move there

    for seat in SEATS:
        action = chosen[seat]
        if seat in frozen:
            outcome[seat] = "frozen"
        elif action == "SHIELD":
            outcome[seat] = "shield"
            s.bots[seat].cooldown = rules.shield_cooldown     # 2.6 cooldown starts now
            events.append({"type": "shield", "seat": seat})
        elif action in MOVES:
            target = move_target(start[seat], action)
            if target in closed:
                outcome[seat] = "blocked"                     # 2.3 closed cell: no swaps
                events.append({"type": "blocked", "seat": seat, "to": target,
                               "reason": "closed"})
            else:
                wants.setdefault(target, []).append(seat)
        else:
            outcome[seat] = "stay"

    order = seat_order(s.token)
    for target, movers in wants.items():
        owner = s.owner[target[0]][target[1]]
        if owner in movers:
            winner = owner                                    # 2.3 the owner gets it
        else:
            winner = min(movers, key=order.index)             # 2.3 first from the token holder
        for seat in movers:
            if seat == winner:
                s.bots[seat].pos = target
                outcome[seat] = "moved"
                events.append({"type": "move", "seat": seat, "from": start[seat],
                               "to": target})
            else:
                outcome[seat] = "blocked"                     # 2.3 the others stay
                events.append({"type": "blocked", "seat": seat, "to": target,
                               "reason": "contest", "winner": winner})
    return outcome



def _phase_takes(s: MatchState, outcome: dict, rules: Rules, events: list):
    """Phase 2 (2.4, 2.5, 2.6): shields catch rivals, then takes and upgrades."""
    # Who counts as staying this turn
    stayed = set()
    for seat, what in outcome.items():
        if what == "stay":
            stayed.add(seat)
        elif what == "blocked" and rules.blocked_move_counts_as_stay:     # Q1
            stayed.add(seat)
        elif what == "frozen" and rules.frozen_stay_builds_progress:      # Q2
            stayed.add(seat)

    # 2.4 progress resets when you move off the cell, shield or are frozen
    for seat, what in outcome.items():
        if what in ("moved", "shield") or (what == "frozen" and seat not in stayed):
            s.bots[seat].progress = 0

    # 2.6 each shield catches the rivals staying on its land, or backfires
    shielders = [seat for seat in SEATS if outcome[seat] == "shield"]
    for x in shielders:
        caught = []
        for y in SEATS:
            r, c = s.bots[y].pos
            if (y != x and y in stayed and outcome[y] != "frozen"      # already frozen: can't be caught
                    and s.owner[r][c] == x):
                caught.append(y)
        if caught:
            for y in caught:
                _freeze(s.bots[y], rules.freeze_turns)
                stayed.discard(y)                                   # lost its progress this turn
                events.append({"type": "caught", "seat": y, "by": x})
        else:
            _freeze(s.bots[x], rules.freeze_turns)                  # caught nobody: backfire
            events.append({"type": "backfire", "seat": x})

    # 2.4 / 2.5 every remaining stay counts toward a take or an upgrade
    for seat in SEATS:
        if seat in stayed:
            _count_stay(s, seat, shielders, rules, events)


def _freeze(bot: BotState, turns: int):
    """Freeze a bot for the next `turns` turns and reset its progress.
    Q10: replaces whatever freeze was left; never adds to it."""
    bot.frozen_for = turns
    bot.progress = 0


def _count_stay(s: MatchState, seat: int, shielders: list, rules: Rules, events:list):
    """One stay by `seat` on the cell it stands on: progress toward a take or an upgrade."""
    bot = s.bots[seat]
    r, c = bot.pos
    owner = s.owner[r][c]
    level = s.level[r][c]

    # Your own cell: work toward an upgrade (2.5)
    if owner == seat:
        if level == 2:
            return                                          # already upgraded
        if (r, c) in HOME_CELLS and not rules.home_can_upgrade:
            return                                          # Q5
        bot.progress += 1
        if bot.progress >= rules.upgrade_stays:
            s.level[r][c] = 2
            bot.progress = 0
            events.append({"type": "upgrade", "seat": seat, "cell": (r, c)})
        return

    # Someone else's cell, or neutral: work toward a take (2.4)
    if (r, c) in HOME_CELLS:
        return                                              # a rival's home can never be taken
    if owner in shielders:
        return                                              # 2.6 its owner shielded this turn

    needed = rules.take_stays_level2 if level == 2 else rules.take_stays_level1
    bot.progress += 1
    if bot.progress < needed:
        return

    bonus = rules.raid_multiplier * s.base_points[r][c] * level if owner else 0   # 2.4 raid bonus
    s.owner[r][c] = seat
    s.level[r][c] = 1                                       # 2.5 a taken cell drops to level 1
    bot.score += bonus
    if rules.reset_progress_after_take:                     # Q4
        bot.progress = 0
    events.append({"type": "take", "seat": seat, "cell": (r, c), "from": owner, "bonus": bonus})


def _phase_score(s: MatchState):
    """Phase 3 (2.7): every bot scores each cell it owns: base points, x2 if upgraded.
    (Raid bonuses were already added in phase 2, when the cell was taken.)"""
    for r in range(SIZE):
        for c in range(SIZE):
            owner = s.owner[r][c]
            if owner:
                s.bots[owner].score += s.base_points[r][c] * s.level[r][c]


def _phase_end(s: MatchState):
    """Phase 4 (2.2): the token passes to the next seat (1 -> 2 -> 3 -> 4 -> 1),
    and the next turn begins."""
    s.token = s.token % 4 + 1
    s.turn += 1
