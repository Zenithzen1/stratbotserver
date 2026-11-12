from dataclasses import dataclass


@dataclass(frozen=True) #True so that none of this changes mid game due to any kind of mishap
class Rules:
    # --- Game rules ------------------------------------------------------
    turns: int = 80                 # 2.1  a game lasts 80 turns
    take_stays_level1: int = 1      # 2.4  stays to take a neutral or rival level-1 cell
    take_stays_level2: int = 3      # 2.4  stays to take a rival's upgraded cell
    upgrade_stays: int = 3          # 2.5  stays on your own level-1 cell to upgrade it
    raid_multiplier: int = 8        # 2.4  raid bonus = 8 x cell value x cell level
    freeze_turns: int = 2           # 2.6  a caught (or backfired) bot is frozen 2 turns
    shield_cooldown: int = 4        # 2.6  no shield again for the next 4 turns
    penalty_freeze_turns: int = 3   # 4.4  time penalty: frozen for the next 3 turns

    # --- Our decisions (DECISIONS.md) ------------------------------------
    blocked_move_counts_as_stay: bool = True    # Q1
    frozen_stay_builds_progress: bool = False   # Q2
    reset_progress_after_take: bool = True      # Q4
    home_can_upgrade: bool = True               # Q5
    first_token_seat: int = 1                   # Q8
    occupied_moves_are_legal: bool = True       # Q9

    def __post_init__(self):
        """Reject impossible settings as soon as a Rules object is made."""
        if self.first_token_seat not in (1, 2, 3, 4):
            raise ValueError("first_token_seat must be 1, 2, 3 or 4")
        counts = {
            "turns": self.turns,
            "take_stays_level1": self.take_stays_level1,
            "take_stays_level2": self.take_stays_level2,
            "upgrade_stays": self.upgrade_stays,
            "freeze_turns": self.freeze_turns,
            "penalty_freeze_turns": self.penalty_freeze_turns,
        }
        for name, value in counts.items():
            if value < 1:
                raise ValueError(f"{name} must be at least 1")


@dataclass(frozen=True)
class TimeLimits:
    first_turn_ms: int = 2000       # 2.8  time allowed on the first turn
    turn_ms: int = 200              # 2.8  time allowed on every other turn

    def __post_init__(self):
        if self.first_turn_ms <= 0 or self.turn_ms <= 0:
            raise ValueError("time limits must be positive")
