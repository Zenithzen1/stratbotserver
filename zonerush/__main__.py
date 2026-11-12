"""Command line:  python -m zonerush <command> ...   (run from the stratbotserver folder)

  play     play a game:
             python -m zonerush play --map maps/rulebook.txt --bots a.py b.py c.py d.py
                 [--names "Team A" "Team B" "Team C" "Team D"] [--screen 8080] [--delay 0.5]
                 [--late 3] [--out games/final] [--turns 80]
           Use - instead of a bot path for an empty seat. Or let the server draw the seats:
             python -m zonerush play --map maps/rulebook.txt --teams config/teams.json
                 [--pick "Team A" "Team B" ...] [--seed N] [--no-robots]
  resume   continue a game that crashed or was aborted:   python -m zonerush resume games/<game>
  replay   check a recorded game against the engine, and optionally watch it:
             python -m zonerush replay games/<game> [--screen 8080]

Robots (Round 2): add --robots config/<file>.json to play/resume, and
  robot    drive one robot by hand (robot check, 4.1):  python -m zonerush robot config/x.json 1
  scan     list the Bluetooth devices in range
  robots   find every robot in range and the team it belongs to (its ROBOT_NAME)
  teams    list and check the teams:  python -m zonerush teams teams/
  markers  print the ArUco markers:  python -m zonerush markers config/x.json --out markers
  camera   live camera window, to set up the arena camera:  python -m zonerush camera config/x.json
"""
import argparse
import os
import sys
import time

from .maps import load_map
from .record import RECORD_NAME, RecordError, read_record, replay
from .referee import Control, start_console
from .rules import Rules
from .screen import Screen
from .snapshot import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m zonerush", description="Zone Rush game server")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("play", help="play a game")
    p.add_argument("--map", required=True, help="map file, e.g. maps/rulebook.txt")
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--bots", nargs=4, metavar="BOT",
                     help="bot.py for seats 1-4 in order; - for an empty seat")
    who.add_argument("--teams", metavar="FILE",
                     help="teams file: the server draws the seats at random (bot + robot together)")
    p.add_argument("--names", nargs=4, metavar="NAME", help="team names for seats 1-4 (with --bots)")
    p.add_argument("--pick", nargs="+", metavar="TEAM", help="with --teams: the teams in this game")
    p.add_argument("--seed", type=int, help="with --teams: repeat an earlier draw by its number")
    p.add_argument("--no-robots", action="store_true", help="with --teams: play without the robots")
    p.add_argument("--out", help="game folder (default games/<date-time>)")
    p.add_argument("--turns", type=int, default=Rules().turns, help="turns to play (default 80)")
    _common(p)

    r = sub.add_parser("resume", help="continue a crashed or aborted game")
    r.add_argument("game", help="the game's folder")
    r.add_argument("--bots", nargs=4, metavar="BOT", help="bot files (default: the recorded ones)")
    r.add_argument("--no-robots", action="store_true", help="resume without the recorded robots")
    _common(r)

    v = sub.add_parser("replay", help="check a recorded game, optionally show it on the screen")
    v.add_argument("game", help="the game's folder (or its record.jsonl)")
    v.add_argument("--screen", type=int, metavar="PORT", help="show the replay on this port")
    v.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other computers")

    o = sub.add_parser("robot", help="drive one robot by hand (robot check)")
    o.add_argument("robots", help="robot config file")
    o.add_argument("seat", type=int, help="which seat's robot")

    sub.add_parser("scan", help="list the Bluetooth devices in range")
    k = sub.add_parser("teams", help="list the teams and check their submissions")
    k.add_argument("teams", help="teams folder (or teams file)")

    t = sub.add_parser("robots", help="find every robot in range and which team it belongs to")
    t.add_argument("--teams", metavar="FILE", help="also show which teams have no robot in range")

    c = sub.add_parser("camera", help="live camera window, to set up the arena camera")
    c.add_argument("robots", help="robot config file (its camera section)")
    c.add_argument("--source", help="override the camera: a number, a picture file, or sim")

    m = sub.add_parser("markers", help="write printable ArUco markers, one per seat")
    m.add_argument("robots", nargs="?", help="robot config (marker ids); default ids 1-4")
    m.add_argument("--out", default="markers", help="folder for the PNG files")
    m.add_argument("--size-mm", type=float, default=80.0, help="printed marker size")

    args = parser.parse_args(argv)
    try:
        return {"play": cmd_play, "resume": cmd_resume, "replay": cmd_replay,
                "robot": cmd_robot, "scan": cmd_scan, "markers": cmd_markers,
                "camera": cmd_camera, "robots": cmd_robots, "teams": cmd_teams}[args.command](args)
    except (RecordError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _common(p):
    p.add_argument("--screen", type=int, metavar="PORT", help="show the big screen on this port")
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other computers")
    p.add_argument("--delay", type=float, default=0.0, help="seconds to wait after each turn")
    p.add_argument("--late", type=int, nargs="*", default=[], metavar="SEAT",
                   help="seats whose robot isn't ready yet (4.4)")
    p.add_argument("--no-console", action="store_true", help="don't read referee commands")
    p.add_argument("--robots", metavar="CONFIG", help="robot config file: act the game out on robots")


# --- play / resume --------------------------------------------------------------------------

def cmd_play(args):
    extra = {}
    robot_config = None
    if args.teams:
        from .teams import describe_draw, draw_seats, game_setup, load_teams, pick
        teams, robot_defaults = load_teams(args.teams)
        from .teams import check_team
        chosen = pick(teams, args.pick)
        for team in chosen:
            for problem in check_team(team):
                print(f"Warning, {team['name']}: {problem}")
        seed, draw = draw_seats(chosen, args.seed)
        bot_paths, names, robot_config = game_setup(draw, robot_defaults)
        if args.no_robots:
            robot_config = None
        print("\n".join(describe_draw(seed, draw)))
        extra["draw"] = {"seed": seed, "teams_file": os.path.abspath(args.teams),
                         "seats": {str(s): (t["name"] if t else None) for s, t in draw.items()}}
    else:
        bot_paths = {seat: path for seat, path in enumerate(args.bots, start=1) if path != "-"}
        for path in bot_paths.values():
            if not os.path.isfile(path):
                raise ValueError(f"bot file not found: {path}")
        names = {seat: name for seat, name in enumerate(args.names or [], start=1)}
    game_dir = args.out or os.path.join("games", time.strftime("%Y%m%d-%H%M%S"))
    if os.path.exists(os.path.join(game_dir, RECORD_NAME)):
        raise ValueError(f"{game_dir} already has a game in it (use resume, or another --out)")
    return _run(args, load_map(args.map), bot_paths, names, game_dir, Rules(turns=args.turns),
                robot_config=robot_config, header_extra=extra)


def cmd_resume(args):
    header = read_record(os.path.join(args.game, RECORD_NAME))[0]
    if args.bots:
        bot_paths = {seat: path for seat, path in enumerate(args.bots, start=1) if path != "-"}
    else:
        bot_paths = {int(s): v["bot"] for s, v in header["seats"].items() if v}   # the snapshots
    robot_config = None if (args.robots or args.no_robots) else header.get("robots")
    return _run(args, None, bot_paths, None, args.game, None, resume=True,
                robot_config=robot_config)


def _run(args, grid, bot_paths, names, game_dir, rules, resume=False, robot_config=None,
         header_extra=None):
    from .match import play_game                       # imported here: it starts processes

    control = Control(late=args.late)
    console = not args.no_console and sys.stdin.isatty()
    fleet = None
    if args.robots and robot_config is None:
        import json
        with open(args.robots, encoding="utf-8") as f:
            robot_config = json.load(f)
    if robot_config:
        from .robots.fleet import Fleet
        fleet = Fleet(robot_config)
        header_extra = {**(header_extra or {}), "robots": robot_config}
        print("Connecting robots...")
        for seat, error in fleet.connect(skip=control.late).items():
            print(f"Seat {seat}: robot not connected ({error}). Its bot stays frozen at home "
                  f"until you type  ready {seat}  (4.4 late robot).")
            control.late.add(seat)
        if console:
            control.pause_now()
    screen = Screen(args.screen, args.host).start() if args.screen else None
    if screen:
        print(f"Big screen: {screen.url}")
    if console:
        start_console(control)

    def on_update(snap):
        if screen:
            screen.publish(snap)
        if snap["status"] != "running":
            return                                     # repeats of the last turn: nothing new
        for seat, report in snap["bots"].items():
            if report.get("result") in ("late", "error", "dead"):
                name = snap["seats"][seat]["name"]
                print(f"  turn {snap['turn']}: {name}'s bot {report['result']}")
        if snap["status"] == "running" and snap["turn"] % 10 == 0:
            print(f"turn {snap['turn']}: " + "  ".join(
                f"{s['name']} {s['score']}" for s in snap["seats"].values()))

    print(f"{'Resuming' if resume else 'Playing'} game in {game_dir}")
    try:
        state, _ = play_game(grid, bot_paths, game_dir, names=names, rules=rules or Rules(),
                             control=control, on_update=on_update, delay=args.delay,
                             resume=resume, robots=fleet, header_extra=header_extra)
    except KeyboardInterrupt:
        print(f"\nInterrupted. The record is kept: continue with  python -m zonerush resume {game_dir}")
        return 130
    finally:
        if fleet:
            fleet.close()

    _print_result(os.path.join(game_dir, RECORD_NAME))
    if screen:
        _hold_screen(screen)
    return 0


# --- replay -------------------------------------------------------------------------------

def cmd_replay(args):
    path = args.game if args.game.endswith(".jsonl") else os.path.join(args.game, RECORD_NAME)
    entries = read_record(path)
    header, rules, frames = replay(entries)       # raises RecordError if anything doesn't match
    print(f"{path}: {len(frames) - 1} turns replayed, every turn matches the record.")
    _print_result(path)
    if args.screen:
        names = {int(s): v["name"] for s, v in header["seats"].items() if v}
        end = next((e for e in reversed(entries) if e["type"] == "end"), None)
        last_status = end["status"] if end else "aborted"
        snaps = [snapshot(state, rules, names, entry,
                          "ready" if i == 0 else last_status if i == len(frames) - 1 else "running")
                 for i, (state, entry) in enumerate(frames)]
        screen = Screen(args.screen, args.host, replay_frames=snaps).start()
        print(f"Replay on the screen: {screen.url}")
        _hold_screen(screen)
    return 0


# --- robots ---------------------------------------------------------------------------------

def cmd_robot(args):
    """Drive one robot by hand: the robot check before the first game (4.1)."""
    from .robots.fleet import Fleet
    from .robots.links import LinkError
    from .robots.protocol import RobotError
    fleet = Fleet.from_file(args.robots)
    if args.seat not in fleet.robots:
        raise ValueError(f"seat {args.seat} isn't in {args.robots}")
    robot = fleet.robots[args.seat]
    print(f"Connecting seat {args.seat} ({robot.link})...")
    error = fleet._connect(robot)
    if error:
        raise ValueError(error)
    print("Commands: F forward, B back, L left, R right (one cell / 90 degrees), several at "
          "once like LFRF;  P ping, X stop, A arm, Q quit")
    try:
        while True:
            try:
                line = input(f"seat {args.seat}> ").strip().upper()
            except EOFError:
                break
            if line in ("Q", "QUIT"):
                break
            for command in line.replace(" ", ""):
                try:
                    if command in "FBLR":
                        took = robot.client.step(command, fleet.step_timeout)
                        print(f"  {command}: done in {took:.2f} s")
                    elif command == "P":
                        started = time.perf_counter()
                        robot.client.ping()
                        print(f"  ping: {(time.perf_counter() - started) * 1000:.0f} ms")
                    elif command == "X":
                        robot.client.stop()
                        print("  stopped and disarmed")
                    elif command == "A":
                        robot.client.arm()
                        print("  armed")
                    else:
                        print(f"  unknown command {command!r}")
                except (RobotError, LinkError) as e:
                    print(f"  {command}: {e}")
                    break
    finally:
        fleet.close()
    return 0


def cmd_scan(args):
    from .robots.links import _AsyncLoop, ble_scan
    print("Scanning for Bluetooth devices (6 s)...")
    for name, address, rssi in _AsyncLoop.run(ble_scan(6.0), timeout=30):
        print(f"  {name:24} {address}   signal {rssi} dBm")
    return 0


def cmd_teams(args):
    from .teams import check_team, load_teams
    teams, _ = load_teams(args.teams)
    for team in teams:
        robot = team["robot"]
        kind = "no robot" if not robot else ("own robot (found by name)" if robot.get("link") == "auto"
                                            else f"robot: {robot.get('link') or robot.get('name')}")
        problems = check_team(team)
        print(f"  {team['name']:20} {kind:28} {'OK' if not problems else 'CHECK: ' + '; '.join(problems)}")
    return 0


def cmd_robots(args):
    """Scan, ask every robot its name, and match the names to teams."""
    from .robots.directory import RobotDirectory, norm
    directory = RobotDirectory(log=lambda m: None)
    print("Looking for robots (scan, then a quick hello to each)...")
    found = directory.refresh(min_gap=0)
    if not found:
        print("  no robots found")
    for entry in found.values():
        print(f"  {entry['name']:20} {entry['address']}")
    if args.teams:
        from .teams import load_teams
        teams, _ = load_teams(args.teams)
        for team in teams:
            robot = team["robot"]
            if robot and robot.get("link") == "auto":
                status = "robot found" if norm(team["name"]) in found else "NO ROBOT IN RANGE"
                print(f"  team {team['name']:20} {status}")
    return 0


def cmd_markers(args):
    import json
    from .robots.markers import make_markers
    ids = {seat: seat for seat in (1, 2, 3, 4)}
    corners = [40, 41, 42, 43]
    if args.robots:
        with open(args.robots, encoding="utf-8") as f:
            config = json.load(f)
        ids = {int(s): cfg.get("marker", int(s)) for s, cfg in config["robots"].items()}
        corners = config.get("camera", {}).get("corner_markers", corners)
    for path in make_markers(ids, args.out, args.size_mm, corners):
        print(f"  wrote {path}")
    print(f"Print at 100% scale (actual size): each marker is {args.size_mm:g} mm wide.")
    print("Robot markers: flat on top, the FRONT edge towards the robot's front.")
    print("Corner markers: just outside each board corner (centre half a cell out, diagonally),")
    print("the TOWARDS ROW 0 edge pointing to the board's top side (row 0).")
    return 0


def cmd_camera(args):
    """Live camera window for setting up the arena: shows what the camera reads."""
    import json
    import cv2
    from .robots.camera import ArenaView, open_camera
    with open(args.robots, encoding="utf-8") as f:
        config = json.load(f)
    cam_cfg = config.get("camera") or {}
    if args.source is not None:
        cam_cfg["source"] = args.source
    markers = {cfg.get("marker", int(s)): int(s) for s, cfg in config["robots"].items()}
    corners = cam_cfg.get("corner_markers", [40, 41, 42, 43])
    offset = cam_cfg.get("corner_offset", 0.5)
    homes = {1: ((0, 0), "S"), 2: ((0, 7), "S"), 3: ((7, 7), "N"), 4: ((7, 0), "N")}
    source = open_camera(cam_cfg.get("source", 0),
                         lambda: {m: homes[s] for m, s in markers.items()}, corners, offset)
    view = ArenaView(corners, offset)
    print("Camera window open. Press q in the window to quit.")
    try:
        while True:
            image = source.picture()
            shown = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            board, found = view.read(image)
            lines = ["board: FOUND" if board else "board: corner markers not all visible"]
            for marker_id, m in sorted(found.items()):
                seat = markers.get(marker_id, "?")
                heading = "NESW"[round(m["angle"] / 90) % 4]
                lines.append(f"marker {marker_id} (seat {seat}): cell ({int(m['row'] // 1)},"
                             f"{int(m['col'] // 1)}) facing {heading}  [{m['row']:.2f}, {m['col']:.2f}]")
            for i, text in enumerate(lines):
                cv2.putText(shown, text, (10, 25 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 200, 0) if board else (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imshow("Zone Rush camera", shown)
            if cv2.waitKey(30) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        cv2.destroyAllWindows()
    return 0


# --- helpers --------------------------------------------------------------------------------

def _print_result(record_path):
    entries = read_record(record_path)
    end = next((e for e in reversed(entries) if e["type"] == "end"), None)
    if not end:
        print("No result recorded (the game didn't finish).")
        return
    seats = entries[0]["seats"]
    print(f"Result ({end['status']}, {end['turns_played']} turns):")
    for seat in sorted(end["placings"], key=lambda s: end["placings"][s]):
        name = seats[seat]["name"] if seats[seat] else f"Seat {seat} (empty)"
        print(f"  {end['placings'][seat]}. {name:20} {end['scores'][seat]:>6} points  "
              f"{end['cells'][seat]:>2} {'cell' if end['cells'][seat] == 1 else 'cells'}")


def _hold_screen(screen):
    print("The screen stays up. Press Ctrl+C to quit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        screen.stop()


if __name__ == "__main__":
    sys.exit(main())
