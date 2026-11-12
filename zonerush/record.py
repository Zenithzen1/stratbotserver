"""The official game record, and replaying it.

Section 6: "The server's game record is the reference" for disputes. A record is a text file
with one JSON object per line, written and flushed as the game goes, so it survives a crash:

    {"type": "header", ...}     map, rules, time limits, the bots (with a fingerprint of each file)
    {"type": "turn", ...}       one per turn: referee actions, what each bot sent and how it went,
                                the engine's events, and a fingerprint ("hash") of the new state
    {"type": "resume", ...}     if a crashed or aborted game was continued
    {"type": "end", ...}        final scores, cells and placings ("finished" or "aborted")

replay() rebuilds the game from the record by running the engine again on the recorded actions,
and checks after every turn that it gets exactly the recorded state. That proves the record
and the engine agree, and gives the screen every turn of the game to show.
"""
import hashlib
import json
from dataclasses import asdict

from .engine import referee_action, step
from .rules import Rules
from .state import MatchState, new_match

FORMAT = 1
RECORD_NAME = "record.jsonl"


class RecordError(Exception):
    """A record is unreadable, or replaying it doesn't give the recorded game."""


def state_hash(state: MatchState) -> str:
    """A short fingerprint of the full game state. Any difference gives a different hash."""
    text = json.dumps(asdict(state), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_hash(path) -> str:
    """Fingerprint of a bot file, so the record shows exactly which code played."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class RecordWriter:
    """Appends entries to a record file, one line each, flushed straight away."""

    def __init__(self, path, append: bool = False):
        self.f = open(path, "a" if append else "w", encoding="utf-8")

    def write(self, entry: dict):
        self.f.write(json.dumps(entry) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def read_record(path) -> list:
    """Read a record. A half-written last line (the server died while writing it) is dropped."""
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    entries = []
    for i, line in enumerate(lines):
        try:
            entries.append(json.loads(line))
        except ValueError:
            if i == len(lines) - 1:
                break                        # cut off mid-write: ignore it
            raise RecordError(f"line {i + 1} of {path} is not valid JSON")
    if not entries or entries[0].get("type") != "header":
        raise RecordError(f"{path} doesn't start with a header")
    if entries[0].get("format") != FORMAT:
        raise RecordError(f"{path} uses record format {entries[0].get('format')}, expected {FORMAT}")
    return entries


def replay(entries: list):
    """Re-run the engine on a record's actions.

    Returns (header, rules, frames). frames[0] is (state before turn 1, None), then one
    (state after the turn, turn entry) per recorded turn. Raises RecordError if any turn
    doesn't give exactly the recorded state.
    """
    header = entries[0]
    rules = Rules(**header["rules"])
    state = new_match(header["map"], rules)
    frames = [(state, None)]
    for entry in entries[1:]:
        if entry.get("type") != "turn":
            continue
        if entry["turn"] != state.turn:
            raise RecordError(f"expected turn {state.turn}, record has turn {entry['turn']}")
        for action in entry["referee"]:
            state, _ = referee_action(state, action, rules)
        actions = {int(seat): action for seat, action in entry["actions"].items()}
        state, _ = step(state, actions, rules)
        if state_hash(state) != entry["hash"]:
            raise RecordError(f"turn {entry['turn']}: replaying gives a different state "
                              "than the record (the record or the engine has changed)")
        frames.append((state, entry))
    return header, rules, frames
