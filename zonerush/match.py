"""Plays one whole game: real bots, the engine, the referee, the record and the screen.

Each turn every bot is shown the same start-of-turn board and asked for its action, one at a
time (Q14: each gets the machine to itself while its clock runs). Then the engine resolves all
four actions together, exactly as if they had been chosen at the same moment (2.2).

Each game lives in its own folder:  record.jsonl (the official record) + seatN.log per bot.
"""
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone

from .engine import is_over, referee_action, step
from .record import RECORD_NAME, RecordWriter, file_hash, read_record, replay, state_hash
from .referee import Control
from .results import cells_owned, placings
from .rules import Rules, TimeLimits
from .runner import BotProcess
from .snapshot import snapshot
from .state import SEATS, new_match
from .view import make_view


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def play_game(base_points, bot_paths: dict, game_dir: str, names: dict = None,
              rules: Rules = Rules(), limits: TimeLimits = TimeLimits(),
              control: Control = None, on_update=None, delay: float = 0.0,
              resume: bool = False, robots=None, log=print, header_extra: dict = None):
    """Play a full game (or continue one), writing its record as it goes.

    base_points: the map grid (from maps.load_map). Ignored when resuming: the record has it.
    bot_paths:   seat -> path to that team's bot.py. A seat left out plays STAY every turn.
    game_dir:    folder for this game's record and bot logs.
    names:       seat -> team name, for the record and the screen.
    control:     referee commands (referee.Control). None = no referee input.
    on_update:   called with a snapshot after every turn (e.g. the big screen).
    delay:       seconds to wait after each turn, so people can follow it on the screen.
    resume:      continue the game recorded in game_dir instead of starting a new one.
                 The bots restart fresh, so their global variables are lost (section 6).
    robots:      a robots.fleet.Fleet (already connected) to act out every turn, or None.
                 Robots only ever move for the engine's "move" events.
    log:         where messages for the referee go (the console).
    header_extra: more facts for the record's header (e.g. the seat draw, the robot config).
    Returns (final_state, turns): `turns` is the list of turn entries, as in the record.
    """
    os.makedirs(game_dir, exist_ok=True)
    record_path = os.path.join(game_dir, RECORD_NAME)
    submitted = dict(bot_paths)
    if not resume:
        bot_paths = _snapshot_bots(bot_paths, game_dir)
    control = control or Control()
    publish = on_update or (lambda snap: None)

    if resume:
        header, rules, frames = replay(read_record(record_path))
        names = names or {int(s): v["name"] for s, v in header["seats"].items() if v}
        state = frames[-1][0]
        turns = [entry for _, entry in frames[1:]]
        if is_over(state, rules):
            raise ValueError("that game already finished all its turns")
        writer = RecordWriter(record_path, append=True)
        writer.write({"type": "resume", "time": _now(), "at_turn": state.turn,
                      "bots": {str(s): {"bot": os.path.abspath(p), "sha256": file_hash(p)}
                               for s, p in bot_paths.items()}})
    else:
        names = names or {}
        state = new_match(base_points, rules)
        turns = []
        writer = RecordWriter(record_path)
        writer.write({
            "type": "header", "format": 1, "started": _now(),
            "map": [list(row) for row in state.base_points],
            "rules": asdict(rules), "limits": asdict(limits),
            "seats": {str(seat): ({"name": names.get(seat) or f"Seat {seat}",
                                   "bot": os.path.abspath(bot_paths[seat]),
                                   "submitted": os.path.abspath(submitted[seat]),
                                   "sha256": file_hash(bot_paths[seat])}
                                  if seat in bot_paths else None)
                      for seat in SEATS},
            **(header_extra or {}),
        })

    last = turns[-1] if turns else None

    def show(status, report=None):
        publish(snapshot(state, rules, names, last, status, robots=report,
                         fleet=robots.status() if robots else None))

    if robots:
        for seat, (pos, heading) in robots.place_all(state).items():
            log(f"Place seat {seat}'s robot on {pos}, facing {heading}.")
        if control.paused:
            log(">>> The game is waiting. Place the robots, then type  r  and press Enter to start. <<<")
    show("ready")
    show_paused = lambda: show("paused")
    first = True

    bots = {seat: BotProcess(seat, path, os.path.join(game_dir, f"seat{seat}.log"), limits)
            for seat, path in bot_paths.items()}
    for bot in bots.values():
        bot.start()

    try:
        while not is_over(state, rules):
            referee = control.before_turn(show_paused)
            if control.aborted:
                break
            if robots:
                referee = _check_robots(robots, state, control, referee, show_paused, log, first)
                if control.aborted:
                    break
            first = False

            referee_events = []
            for action in referee:
                state, events = referee_action(state, action, rules)
                referee_events += events

            actions, reports = {}, {}
            for seat in SEATS:
                if seat not in bots:
                    actions[str(seat)], reports[str(seat)] = "STAY", {"result": "empty seat"}
                    continue
                action, report = bots[seat].ask(make_view(state, seat, rules), state.turn)
                actions[str(seat)] = action if action is not None else "STAY"  # 2.8: STAY
                reports[str(seat)] = report

            turn = state.turn
            state, events = step(state, {int(s): a for s, a in actions.items()}, rules)
            last = {"type": "turn", "turn": turn, "referee": referee, "actions": actions,
                    "bots": reports, "events": referee_events + events,
                    "hash": state_hash(state)}
            writer.write(last)
            turns.append(last)
            show("running")
            if robots:
                _act_out(robots, turn, events, writer, control, log,
                         lambda report: show("running", report))
            if delay:
                time.sleep(delay)
    finally:
        for bot in bots.values():
            bot.stop()
        if robots:
            robots.stop_all()

    status = "finished" if is_over(state, rules) else "aborted"
    writer.write({"type": "end", "time": _now(), "status": status, "turns_played": state.turn - 1,
                  "scores": {str(s): state.bots[s].score for s in SEATS},
                  "cells": {str(s): n for s, n in cells_owned(state).items()},
                  "placings": {str(s): p for s, p in placings(state).items()}})
    writer.close()
    show(status)
    return state, turns


def _snapshot_bots(bot_paths: dict, game_dir: str) -> dict:
    """Copy every bot into the game folder (seatN_bot.py) and play those copies. A game always runs
    the code as it was when it started, even if a bot has to be restarted mid-game (Q13), and the
    copy stays in the game folder as the record of exactly what played."""
    import shutil
    copies = {}
    for seat, path in bot_paths.items():
        copy = os.path.join(game_dir, f"seat{seat}_bot.py")
        shutil.copyfile(path, copy)
        copies[seat] = copy
    return copies


def _check_robots(robots, state, control, referee, show_paused, log, first):
    """Before a turn: every robot that should play must be connected, and (with a camera) be
    where the server says. If not, pause so the referee can fix it. After that pause, carry on:
    the referee has the final say (4.4)."""
    waited = control.waited
    problems = robots.prepare(state, skip=control.late)
    if problems:
        for seat, problem in problems:
            log(f"Seat {seat}: {problem}.")
        log("Game paused. Fix the robot and type r, or type r to carry on without it "
            "(the referee then moves it by hand).")
        referee = _wait_for_referee(control, referee, show_paused)
        waited = True
        for seat, problem in robots.prepare(state, skip=control.late, retry=True):
            log(f"Seat {seat}: still {problem}. Carrying on without it.")

    if robots.camera is not None and (first or waited) and not control.aborted:
        wrong = _camera_problems(robots, robots.verify(skip=control.late))
        if wrong:
            for seat, text in wrong:
                log(f"Seat {seat}: {text}.")
            log("Game paused. Put the robots right, then type r.")
            referee = _wait_for_referee(control, referee, show_paused)
            for seat, text in _camera_problems(robots, robots.verify(skip=control.late)):
                log(f"Seat {seat}: still {text}. Carrying on (the referee's call).")
    return referee


def _wait_for_referee(control, referee, show_paused):
    """Pause now and wait for the referee to resume. Penalties queued before the pause still
    apply; late-robot holds come from the latest call."""
    control.pause_now()
    more = control.before_turn(show_paused)
    return [a for a in referee if a["type"] == "penalty"] + more


def _camera_problems(robots, results):
    return [(int(seat), robots.describe(int(seat), r))
            for seat, r in results.items() if r["result"] != "ok"]


def _act_out(robots, turn, events, writer, control, log, show):
    """After a turn: the robots act out the engine's moves. Any robot that didn't make it
    pauses the game, and the console says where the referee should put it (4.4)."""
    report = robots.act_out(events)
    camera = robots.verify(skip=control.late)              # Q19: is every robot where it should be?
    for seat, result in camera.items():
        if result["result"] != "ok" and report.get(seat, {}).get("result", "ok") == "ok":
            robot = robots.robots[int(seat)]
            report[seat] = {"result": "misplaced", "error": robots.describe(int(seat), result),
                            "place_at": list(robot.pos), "facing": robot.home_heading}
            robot.needs_placing = True
    if not report and not camera:
        return
    writer.write({"type": "robots", "turn": turn, "robots": report, "camera": camera})
    trouble = {seat: r for seat, r in report.items() if r["result"] != "ok"}
    if not trouble:
        return
    for seat, r in trouble.items():
        what = r.get("error") or "robot offline"
        log(f"Turn {turn}, seat {seat}: {what}. Place it on {tuple(r['place_at'])} facing "
            f"{r['facing']}.")
    log("Game paused. After placing: pen <seat> if it was the team's fault (4.4), then r.")
    control.pause_now()
    show(report)
