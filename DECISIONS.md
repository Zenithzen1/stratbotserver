# Rule decisions

The game server follows the StrategyBot rulebook and the starter README. Where they are
silent or ambiguous, the server follows the decisions below. Every decision that could be
changed is a setting in `zonerush/rules.py`. Clause numbers (2.3, 4.4, ...) refer to the
rulebook.

If the organisers announce a clarification, update the setting and this file together.

## Game rules

| # | Question | Decision | Setting | Basis |
|---|---|---|---|---|
| Q1 | Does a blocked move count as a stay for take/upgrade progress? | **Yes.** | `blocked_move_counts_as_stay = True` | 2.3: "A blocked move counts as `STAY`." |
| Q2 | Does the forced `STAY` of a frozen bot build progress? | **No.** Progress is reset by the freeze and stays at 0 while frozen. | `frozen_stay_builds_progress = False` | 2.4: progress resets when you "are frozen"; 2.6: a frozen bot's "chosen action is ignored". |
| Q3 | Is a bot that shields while standing on a rival's land "staying" there? | **No**, so that rival's shield can't catch it. | rulebook text (no setting) | 2.6: "a Shield turn is not a stay". |
| Q4 | Does progress reset after a take, or does the taking stay also count toward upgrading? | **Resets.** Upgrading a freshly taken cell needs 3 new stays. | `reset_progress_after_take = True` | Simplest reading of 2.4 and 2.5. |
| Q5 | Can a home cell be upgraded? | **Yes**, like any other cell you own. | `home_can_upgrade = True` | 2.5 makes no exception for homes. |
| Q6 | What do "frozen for 2 turns" and "can't shield for the next 4 turns" cover? | The turns **after** the one where it happens. A bot frozen on turn 10 can only `STAY` on turns 11 and 12. A bot that shields on turn 10 can't shield on turns 11 to 14. | engine behaviour | Wording of 2.6 and 4.4 ("the next 3 turns"). |
| Q7 | Which seat starts in which corner? | Seat 1 top-left `(0,0)`, seat 2 top-right `(0,7)`, seat 3 bottom-right `(7,7)`, seat 4 bottom-left `(7,0)`. | `HOMES` in `zonerush/state.py` | Not stated anywhere. |
| Q8 | Who holds the priority token on turn 1? | **Seat 1.** | `first_token_seat = 1` | Not stated anywhere. |
| Q9 | Is a move into a cell that has a bot on it listed in `legal_actions`? | **Yes.** It is a legal move that gets blocked, not an illegal one. Moves off the board are not listed. `SHIELD` is not listed during its cooldown, and a frozen bot is offered only `STAY`. | `occupied_moves_are_legal = True` | 2.3 treats it as a blocked move. Leaving it out would tell bots something the rules don't. |
| Q10 | A frozen bot is frozen again (e.g. a time penalty). Does the freeze stack? | **No.** The new freeze replaces whatever was left: the bot is frozen for the full new length from now. | engine behaviour | Organiser decision (9 Nov 2026). |
| Q11 | What is a home cell worth per turn? | Whatever the map file says, like any other cell. | map file | Not stated. Homes are mirrored and can never change hands, so every bot gets the same amount and no result changes. |

## Running bots

Rulebook 2.8 says a bot that crashes, is late or returns an illegal action plays `STAY` that
turn. These decisions cover what happens around that. None of them changes the skeleton:
bots still write `act(state)` exactly as in `bot.py`.

| # | Question | Decision | Setting | Basis |
|---|---|---|---|---|
| Q12 | A bot doesn't answer within its time (200 ms, or 2 s on its first turn). | **`STAY` that turn.** The bot is paused where it is and resumed at its next turn, keeping its global variables. Any work left over from the late turn uses up part of its next turn's time. | `zonerush/runner.py` | 2.8. Organiser decision (9 Nov 2026). |
| Q13 | A bot's whole process dies (e.g. `os._exit()`, or Python itself crashing). | **`STAY` that turn** (there is no reply). At its next turn it is restarted fresh, with the 2 s first-turn time to load, and plays on; its global variables are lost. **At most 3 restarts per game**, after that it plays `STAY` for the rest of the game. An error or `sys.exit()` inside `act` is not a process death: it only costs that turn. | `MAX_RESTARTS = 3` in `zonerush/runner.py` | 2.8 ("plays `STAY` that turn", so the bot carries on). Organiser decision (9 Nov 2026). |
| Q14 | How are four bots asked "at the same time"? | Every bot gets the same start-of-turn board. They are asked **one at a time**, each with its own time slot and the machine to itself. No bot sees another's action until the engine resolves all four together. Outside its own slot, a bot's process is paused, so it can't keep thinking in the background. | `zonerush/match.py`, `zonerush/runner.py` | 2.2 (simultaneous actions), 2.8 (200 ms per turn). Organiser decision (9 Nov 2026). |
| Q15 | A bot imports a module that isn't in the standard library. | The import fails as if the module weren't installed. If that stops `bot.py` from loading, the bot plays `STAY` every turn. No extra penalty and no submission checker: teams were told to use the standard library only, and the organisers remind them in the announcement. | import guard in `zonerush/worker.py` | 2.8, 3.1 ("a bot that doesn't run plays `STAY` every turn"). Organiser decision (9 Nov 2026). |

## Refereeing

| # | Question | Decision | Setting | Basis |
|---|---|---|---|---|
| Q16 | A robot isn't ready when its game starts. | The game starts without it. Until the referee marks it ready, its bot is **frozen at home**: other bots see `is_frozen` on its cell, its progress resets, and it is still asked each turn but only offered `STAY`. Referee commands `late <seat>` / `ready <seat>`, or `--late` when starting. | `hold()` in `zonerush/engine.py` | 4.4 "its bot stays frozen at home until the robot is placed". Organiser decision (9 Nov 2026). |
| Q17 | A game is stopped (crash, power cut, `abort`) and resumed. | The game continues from the last completed turn, rebuilt from the record. The bots restart fresh, so their **global variables are lost**; they get the 2 s first-turn time to load again. The record notes the resume and the bot files used. | `python -m zonerush resume` | Section 6: "A game spoiled by a system error may be resumed or replayed." A stopped process can't be brought back. Organiser decision (9 Nov 2026). |

## Robots (Round 2)

| # | Question | Decision | Setting | Basis |
|---|---|---|---|---|
| Q18 | When may a robot move? | **Only to act out a move the engine has already approved** (a `move` event on the official board). A blocked move, `STAY`, `SHIELD` or an illegal action never produces motion. The robot never decides anything: it runs single steps (forward / back one cell, turn 90 degrees) sent by the server, only while armed by the server, and stops and disarms by itself if it hears nothing for 5 s. | `zonerush/robots/fleet.py`, firmware | 4.3 "the game server runs the game and its board is official". Organiser decision (9 Nov 2026). |
| Q19 | How are robots tracked, and how are shields and freezes shown? | **Everything goes through ArUco markers; no lights on the robots.** Each seat's robot carries a unique marker (4x4 dictionary, ids = seat numbers by default), its FRONT edge to the robot's front. Four corner markers (ids 40-43) let an overhead camera find the board. After every turn, before the first turn and after every pause, the camera checks that every robot is on the server's cell and facing the server's heading; anything else is a robot fault (Q20). Shields and freezes are shown on the big screen. The operator's map view (`/map`) shows the board colour-coded, with each robot's heading, marker and camera result. | `camera` and `marker` in the robot config; `zonerush/robots/camera.py`; `python -m zonerush markers` / `camera` | 4.3 asks robots to "show their colour and signal when they shield or are frozen"; the organisers chose markers, the camera check and the big screen instead. Organiser decision (9 Nov 2026). |
| Q20 | A robot doesn't finish a step, stops answering, is offline, or the camera sees it in the wrong place. | The game **pauses before the next turn** and the console (and the map view) say where the robot should be and which way it must face (its seat's home heading). The referee places it, types `pen <seat>` if it was the team's fault (4.4), then `r`. After the pause the camera checks again; if a robot is still wrong, or an offline robot still can't connect, the game carries on and the referee has the final say. | `zonerush/match.py` | 4.4. Organiser decision (9 Nov 2026); the "face the home heading" detail is the server's convention. |
| Q21 | Who writes the robot's code, and who controls it? | **Each team writes its robot's sketch** (`firmware/robot_sketch/robot_sketch.ino`): the five step functions `stepForward`, `stepBack`, `turnLeft`, `turnRight`, `stopMotors`, using `waitMs()` instead of `delay()`. **The server controls the robot**: the organisers' `ZoneRush.h` (identical for every team, not to be changed) receives the server's steps over Bluetooth and calls those functions. A robot never takes orders from its team's `bot.py`, which only ever talks to the server. | `firmware/robot_sketch/` (team), `ZoneRush.h` (organisers) | 4.2, 4.3. Organiser decision (10 Nov 2026). |
| Q22 | Which team plays which corner in a game? | **Drawn at random by the server.** A team's bot and its robot always go together. With `play --teams <file>` the server shuffles the seats, prints the draw (where each robot goes and which seat marker it carries), and writes the draw and its number into the game record, so it can be checked or repeated (`--seed`). Every team is equally likely to get every corner. | `zonerush/teams.py`; `play --teams` / `--pick` / `--seed` | 4.3 "The organisers assign each team's corner for every game"; maps are mirrored, so all corners are equal. Organiser decision (10 Nov 2026). |
| Q23 | How does the server know which robot belongs to which team? | **The robot says so.** A robot's `ROBOT_NAME` (in its sketch) is its team's name, and it answers the server's hello with it. Before a game the server scans for robots, asks each its name, and pairs it with the team of that name (case, spaces and punctuation ignored). It checks the name on every connect and refuses any other robot, so a team's bot only ever drives that team's robot. A team whose robot isn't found is a late robot (Q16). Found robots are remembered per laptop (`config/robots.found.json`); `python -m zonerush robots` lists them. | `zonerush/robots/directory.py`; teams without a `robot` entry | 4.3. Organiser decision (10 Nov 2026). |

## Documentation mismatches

The skeleton (`bot.py`) and README are released and frozen, so these are handled by an
organiser announcement, not by editing the starter repo. The server follows the README.

| # | Where | What it says | What is true (and what the server does) |
|---|---|---|---|
| D1 | `bot.py` docstring | `cell.is_frozen` "tells whether the cell is currently frozen" | Cells are never frozen. `is_frozen` is `True` when **the bot standing on the cell** is frozen, and `False` on an empty cell. This is what the README says ("freezing affects bots, not ownership or the cell itself"). |
| D2 | `bot.py` docstring | `state.board: List[cell]` | `state.board` is an 8 x 8 grid, read as `state.board[row][col]`, with `(0, 0)` top-left. This is what the README says. |
| D3 | `bot.py` docstring | `state.bot_id` is an "ID number" | It is the seat number, 1 to 4. Its home corner is given by Q7. |
| D4 | README, section "Memory between turns" | (formatting) | The section was pasted with invisible characters (U+2060) and `•` bullets, so its code formatting and the `my_position` example don't display properly on GitHub. Whoever owns the starter repo should repaste it as plain Markdown. The content is correct. |
| D5 | Rulebook and README | (not stated) | Which corner each seat starts in (Q7) and who holds the token on turn 1 (Q8). Bots can work both out from `state`, but stating them avoids questions. |

### Suggested announcement

> **StrategyBot: clarifications to the starter code**
>
> 1. `cell.is_frozen` is `True` when the **bot standing on that cell** is frozen. Cells
>    themselves are never frozen, and an empty cell always has `is_frozen == False`.
>    (The comment in `bot.py` is out of date; the README is correct.)
> 2. `state.board` is an 8 x 8 grid: use `state.board[row][col]`, with `(0, 0)` at the
>    top-left. `NORTH` is row - 1, `SOUTH` row + 1, `WEST` col - 1, `EAST` col + 1.
> 3. `state.bot_id` is your seat, 1 to 4. Seat 1 starts top-left, seat 2 top-right,
>    seat 3 bottom-right, seat 4 bottom-left.
> 4. Seat 1 holds the priority token on turn 1. It then passes 1 -> 2 -> 3 -> 4 -> 1.
> 5. A blocked move counts as `STAY`, including for take and upgrade progress (rulebook 2.3).
> 6. **Standard library only.** Importing anything else (numpy, etc.) fails during the
>    game as if it weren't installed. If your bot can't load because of it, it plays `STAY`
>    every turn. Test your bot with a plain Python installation before you submit.
> 7. **Time limits.** Each bot is asked on its own, with 200 ms to answer (2 s on the first
>    turn, which includes loading your file). A late answer plays `STAY` that turn. Your bot
>    keeps running and keeps its global variables, but any work it hadn't finished eats into
>    its next turn. Your bot is paused outside its own turn, so background threads don't
>    help.
> 8. **Crashes.** An error in `act` plays `STAY` that turn and your bot carries on as
>    normal. If your bot's whole process dies, it plays `STAY` that turn and is restarted
>    for the next one with its global variables reset (at most 3 times per game).
