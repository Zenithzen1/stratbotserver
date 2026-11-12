"""Runs inside one bot's own process: loads its bot.py and answers the server, one turn at a time.

The server (runner.py) starts it as:   python -I worker.py <bot.py> <log file>

It talks to the server in JSON lines: one request line in on stdin, one reply line out on stdout.
  request: {"turn": 5, "view": {...the Game object as plain data...}}
  reply:   {"turn": 5, "action": "NORTH", "error": null}
Everything the bot prints goes to the log file instead, so it can't get mixed into the replies.
"""
import importlib.util
import json
import os
import sys
import traceback

sys.dont_write_bytecode = True     # no __pycache__ next to the bot's copy in the game folder

# python -I leaves the script's own folder off sys.path, so add the folder that holds the
# zonerush package. That lets us reuse the exact Game and Cell classes from view.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zonerush.view import Cell, Game  # noqa: E402

# Forget the zonerush modules again, so a bot can't `import zonerush` and run our engine:
# it isn't standard library. Cell and Game stay usable because we hold them directly.
for _name in [n for n in sys.modules if n == "zonerush" or n.startswith("zonerush.")]:
    del sys.modules[_name]

LOG_LIMIT = 200_000        # characters of bot output kept per game; the rest is dropped
ACTION_LIMIT = 30          # longest action string passed back (real ones are at most 6)


class CappedLog:
    """Stands in for print()'s output. Writes to the log file until the limit, then drops the rest,
    so a bot that prints in a loop can't fill the disk."""

    def __init__(self, f, limit):
        self.f = f
        self.left = limit

    def write(self, text):
        if self.left > 0:
            piece = text[:self.left]
            self.f.write(piece)
            self.left -= len(piece)
            if self.left <= 0:
                self.f.write("\n[log cut off: output limit reached]\n")
            self.f.flush()
        return len(text)

    def flush(self):
        self.f.flush()


class StdlibOnly:
    """Import guard (rulebook 2.8: standard library only). Any import of a module that isn't part
    of Python's standard library fails with ModuleNotFoundError, as if it weren't installed."""

    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top in sys.stdlib_module_names:
            return None                    # standard library: let Python import it normally
        raise ModuleNotFoundError(
            f"No module named {name!r} (only the standard library is allowed, rulebook 2.8)")


def load_bot(path):
    """Import bot.py from its file path and return its act function."""
    spec = importlib.util.spec_from_file_location("bot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot"] = module
    spec.loader.exec_module(module)
    return module.act


def to_game(view):
    """Rebuild the README's Game object from the plain data the server sent."""
    board = [[Cell(**cell) for cell in row] for row in view["board"]]
    return Game(board=board, bot_id=view["bot_id"],
                is_priority_token=view["is_priority_token"],
                legal_actions=list(view["legal_actions"]))


def main():
    bot_path, log_path = sys.argv[1], sys.argv[2]

    # Keep the real stdin/stdout for talking to the server; give the bot harmless stand-ins.
    requests, replies = sys.stdin, sys.stdout
    log = CappedLog(open(log_path, "a", encoding="utf-8"), LOG_LIMIT)
    sys.stdout = sys.stderr = log
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.meta_path.insert(0, StdlibOnly())

    act = None
    load_error = None
    for line in requests:
        request = json.loads(line)
        reply = {"turn": request["turn"], "action": None, "error": None}

        if act is None and load_error is None:
            try:
                act = load_bot(bot_path)   # the first request loads the bot, inside its time limit
            except BaseException:
                load_error = "bot.py failed to load:\n" + traceback.format_exc(limit=-3)
                print(load_error)

        if load_error:
            reply["error"] = load_error
        else:
            try:
                result = act(to_game(request["view"]))
                if isinstance(result, str):
                    reply["action"] = result[:ACTION_LIMIT]
                else:
                    reply["error"] = f"act returned {type(result).__name__}, not a string"
            except BaseException:          # includes sys.exit() inside act: the bot keeps running
                reply["error"] = traceback.format_exc(limit=-3)
                print(f"turn {request['turn']}: act raised\n{reply['error']}")

        replies.write(json.dumps(reply) + "\n")
        replies.flush()


if __name__ == "__main__":
    main()
