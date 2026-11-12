"""What the big screen shows: one turn of a game as plain data (JSON-ready).

Unlike a bot's view, the screen shows everything: scores, progress, freezes and cooldowns.
"""
from .results import cells_owned, placings
from .rules import Rules
from .state import SEATS, MatchState

COLOURS = {1: "Red", 2: "Blue", 3: "Amber", 4: "Green"}   # rulebook colours, by corner (Q7)


def snapshot(state: MatchState, rules: Rules, names: dict, entry: dict = None,
             status: str = "running", robots: dict = None, fleet: dict = None) -> dict:
    """The board after a turn. `entry` is that turn's record entry (None before turn 1).
    status: "ready", "running", "paused", "finished" or "aborted"."""
    cells = cells_owned(state)
    snap = {
        "turn": state.turn - 1,              # the turn just played (0 = not started)
        "turns": rules.turns,
        "token": state.token,                # who holds the token for the next turn
        "status": status,
        "map": state.base_points,
        "owner": state.owner,
        "level": state.level,
        "seats": {
            str(seat): {
                "name": names.get(seat) or f"Seat {seat}",
                "colour": COLOURS[seat],
                "pos": state.bots[seat].pos,
                "score": state.bots[seat].score,
                "cells": cells[seat],
                "progress": state.bots[seat].progress,
                "frozen_for": state.bots[seat].frozen_for,
                "cooldown": state.bots[seat].cooldown,
            }
            for seat in SEATS
        },
        "events": entry["events"] if entry else [],
        "bots": entry["bots"] if entry else {},
        "actions": entry["actions"] if entry else {},
        "robots": robots or {},              # robot problems this turn (fleet.act_out reports)
        "fleet": fleet or {},                # each robot: believed cell, heading, camera check
    }
    if status in ("finished", "aborted"):
        snap["placings"] = {str(seat): place for seat, place in placings(state).items()}
    return snap
