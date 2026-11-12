"""Teams for a game, and the random seat draw.

In Round 2 every team brings two halves that always go together: its bot.py and its robot.
Rulebook 4.3: "The organisers assign each team's corner for every game." The server does that
by drawing the seats at random, so nobody has to think about it. The draw (and the number it
was drawn from) goes into the game record, so it can be checked or repeated.

Teams FOLDER (the easy way): one subfolder per team, named after the team.
    teams/
      Krauts/
        bot.py              the team's bot, as handed in before the code lock (4.2)
        robot_sketch/       optional: a copy of what is on their robot (checked, see check_team)
        team.json           optional: {"bot": "other/path/bot.py"} and/or {"robot": ...} as below
The folder name is the team's name, so it is also what the team's robot must answer with.
Folders starting with "_" or "." are ignored.

Or a teams FILE (JSON). Paths are relative to the teams file itself:
    {
      "robot_defaults": {"link": "ble", "step_timeout": 8.0, "ack_timeout": 1.5, "allow_reverse": true},
      "teams": [
        {"name": "Krauts",  "bot": "../../krautbot/bot.py"},
        {"name": "Falcons", "bot": "falcons/bot.py", "robot": {"link": "sim"}},
        {"name": "Nebula",  "bot": "nebula/bot.py",  "robot": "none"}
      ]
    }
  robot   left out (the normal case): the team's robot is FOUND AUTOMATICALLY. It is whichever
          robot answers with the team's name (the ROBOT_NAME in its sketch), and the server
          checks that on every connect, so a team's bot always drives that team's robot.
          {"link": "sim"}: a simulated robot. "none": no robot. Or a Bluetooth "name"/"address"
          (see robots/fleet.py) to point at one device by hand.
A game needs at most 4 teams; with fewer, the empty seats are drawn too.
"""
import json
import os
import random
import secrets

from .state import HOMES, SEATS

CORNERS = {1: "top-left", 2: "top-right", 3: "bottom-right", 4: "bottom-left"}


def load_teams(path: str):
    """Returns (teams, robot_defaults). Each team: {"name", "bot" (absolute path), "robot",
    "folder"}. `path` is a teams folder or a teams file."""
    if os.path.isdir(path):
        data, base = _read_folder(path), os.path.abspath(path)
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        base = os.path.dirname(os.path.abspath(path))
    teams = []
    for team in data["teams"]:
        bot = os.path.normpath(os.path.join(base, team["bot"]))
        if not os.path.isfile(bot):
            raise ValueError(f"team {team['name']!r}: bot file not found: {bot}")
        robot = team.get("robot", "auto")
        if robot == "auto":
            robot = {"link": "auto", "identity": team["name"]}
        elif robot == "none":
            robot = None
        teams.append({"name": team["name"], "bot": bot, "robot": robot,
                      "folder": team.get("folder")})
    names = [t["name"] for t in teams]
    if len(set(names)) != len(names):
        raise ValueError("every team needs a different name")
    return teams, data.get("robot_defaults", {})


def _read_folder(path: str) -> dict:
    """A teams folder as the same data a teams file holds."""
    data = {"robot_defaults": {}, "teams": []}
    settings = os.path.join(path, "settings.json")          # optional: robot_defaults
    if os.path.isfile(settings):
        with open(settings, encoding="utf-8") as f:
            data["robot_defaults"] = json.load(f).get("robot_defaults", {})
    for name in sorted(os.listdir(path)):
        folder = os.path.join(path, name)
        if name.startswith(("_", ".")) or not os.path.isdir(folder):
            continue
        team = {"name": name, "bot": f"{name}/bot.py", "folder": os.path.abspath(folder)}
        extra = os.path.join(folder, "team.json")
        if os.path.isfile(extra):
            with open(extra, encoding="utf-8") as f:
                more = json.load(f)
            if "bot" in more:
                team["bot"] = os.path.join(name, more["bot"])
            if "robot" in more:
                team["robot"] = more["robot"]
        data["teams"].append(team)
    if not data["teams"]:
        raise ValueError(f"no team folders in {path}")
    return data


def check_team(team: dict) -> list:
    """Problems with a team's submission, as short sentences (empty list = all fine):
    the bot must load as Python; a robot sketch copy, if there is one, must use the team's name
    as ROBOT_NAME and an unchanged ZoneRush.h."""
    import re
    problems = []
    try:
        with open(team["bot"], "rb") as f:
            compile(f.read(), team["bot"], "exec")             # syntax check only; nothing runs
    except SyntaxError as e:
        problems.append(f"bot.py has a syntax error on line {e.lineno}: {e.msg}")
    except (OSError, ValueError) as e:
        problems.append(f"bot.py can't be read: {e}")
    folder = team.get("folder")
    sketch_dir = os.path.join(folder, "robot_sketch") if folder else None
    if sketch_dir and os.path.isdir(sketch_dir):
        from .robots.directory import same_name
        inos = [f for f in os.listdir(sketch_dir) if f.endswith(".ino")]
        text = ""
        for ino in inos:
            with open(os.path.join(sketch_dir, ino), encoding="utf-8", errors="replace") as f:
                text += f.read()
        m = re.search(r'#define\s+ROBOT_NAME\s+"([^"]*)"', text)
        if not inos:
            problems.append("robot_sketch has no .ino file")
        elif not m:
            problems.append("robot sketch has no ROBOT_NAME")
        elif not same_name(m.group(1), team["name"]):
            problems.append(f"robot sketch's ROBOT_NAME is {m.group(1)!r}, not the team's name "
                            f"{team['name']!r}: the server won't find their robot")
        header = os.path.join(sketch_dir, "ZoneRush.h")
        official = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "firmware", "robot_sketch", "ZoneRush.h")
        if not os.path.isfile(header):
            problems.append("robot sketch has no ZoneRush.h")
        elif _text(header) != _text(official):
            problems.append("robot sketch's ZoneRush.h has been changed")
    return problems


def _text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return "\n".join(line.rstrip() for line in f.read().splitlines()).strip()


def pick(teams: list, names: list = None) -> list:
    """The teams playing this game: the named ones, or all of them if there are at most 4."""
    if names:
        by_name = {t["name"]: t for t in teams}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"no team called {', '.join(missing)} (teams: {', '.join(by_name)})")
        chosen = [by_name[n] for n in names]
    else:
        chosen = teams
    if not 1 <= len(chosen) <= 4:
        raise ValueError(f"a game has 1 to 4 teams, not {len(chosen)}; choose them with --pick "
                         f"(teams: {', '.join(t['name'] for t in teams)})")
    return chosen


def draw_seats(chosen: list, seed: int = None):
    """Draw a random seat for every team. Returns (seed, {seat: team or None})."""
    if seed is None:
        seed = secrets.randbelow(10**9)
    seats = list(SEATS)
    random.Random(seed).shuffle(seats)
    draw = {seat: None for seat in SEATS}
    for team, seat in zip(chosen, seats):
        draw[seat] = team
    return seed, draw


def game_setup(draw: dict, robot_defaults: dict):
    """From a draw: (bot_paths, names, robots config or None) for play_game and the Fleet.
    Each robot carries its seat's marker (marker id = seat number)."""
    bot_paths = {seat: t["bot"] for seat, t in draw.items() if t}
    names = {seat: t["name"] for seat, t in draw.items() if t}
    robots = {str(seat): {**t["robot"], "marker": seat}
              for seat, t in draw.items() if t and t.get("robot")}
    config = {**robot_defaults, "robots": robots} if robots else None
    return bot_paths, names, config


def describe_draw(seed: int, draw: dict) -> list:
    """The draw as lines for the console."""
    lines = [f"Seat draw (number {seed}):"]
    for seat in SEATS:
        team = draw[seat]
        where = f"seat {seat}, {CORNERS[seat]} {HOMES[seat]}"
        if team is None:
            lines.append(f"  {where}: empty")
        else:
            robot = team.get("robot")
            if not robot:
                robot_text = "no robot"
            elif robot.get("link") == "auto":
                robot_text = f"its own robot, found by name, marker {seat} on it"
            else:
                robot_text = (f"robot {robot.get('name') or robot.get('address') or robot.get('link')}, "
                              f"marker {seat} on it")
            lines.append(f"  {where}: {team['name']}  ({robot_text})")
    return lines
