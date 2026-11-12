# StrategyBot: robot sketch

This folder contains the starter code for your **robot** in **StrategyBot – Zone Rush** Round 2, organised by the **Aerospace & Robotics Club (ARC) × Coding Club** at **IIT Delhi – Abu Dhabi** as part of **AFKAR 2026**.

In Round 2 your team plays with two halves that work together:

- **`bot.py`** (your Round 1 bot) decides your moves, exactly as in the software round.
- **`robot_sketch.ino`** (this folder) makes your robot (the Keyestudio Mini Tank Robot V2, KS0428) perform them on the arena.

They never talk to each other directly. The **game server** sits in between: it asks your bot for its move, plays the turn on the official board, and only then sends your robot the steps to act out the moves the game approved. Your robot does exactly what the server sends, and nothing else.

```
bot.py ──move──▶ game server ──steps (Bluetooth)──▶ ZoneRush.h ──▶ your step functions
                 (decides the turn)                 (do not change)  (stepForward, turnLeft, ...)
```

## Connecting to the server

You don't write any connection code. The kit's **Bluetooth module (HM-10)** handles the connection by itself: it advertises over Bluetooth, the game server connects to it, and from then on whatever the server sends comes out on your board's `Serial` (pins 0 and 1), and whatever goes into `Serial` goes back to the server. That is why your sketch only needs `Serial.begin(9600)` and `zoneRushBegin(Serial, ROBOT_NAME)`.

**Your robot tells the server which team it belongs to:** set `ROBOT_NAME` to your **team's name**, exactly as registered (write `-` instead of spaces; capitals don't matter). Before each game the server looks for the robot with your team's name and pairs it with your bot, and it checks the name every time it connects, so another team's robot can never act out your moves. If no robot answers with your team's name, your bot waits frozen at home (rulebook 4.4, late robot).

## The steps

A tank robot can only drive straight or turn on the spot, so the server breaks every move into steps. The server keeps track of which way your robot is facing and picks the steps:

| Step the server sends | Your function | What it must do |
| --- | --- | --- |
| `F` | `stepForward()` | drive **forward exactly one cell**, then stop |
| `B` | `stepBack()` | drive **backwards exactly one cell**, then stop |
| `L` | `turnLeft()` | turn **90° left** on the spot, then stop |
| `R` | `turnRight()` | turn **90° right** on the spot, then stop |
| `X` (stop) | `stopMotors()` | stop both motors **immediately** |

For example, if your robot faces north and your bot moves `EAST`, the server sends `R` then `F`. If it faces north and your bot moves `SOUTH`, it sends `B`. A blocked move, `STAY`, `SHIELD` or an illegal move sends nothing: the robot doesn't move.

## Input

Your robot doesn't receive the board or your bot's move. Each of your four step functions is called with no arguments when the server sends that step. `stopMotors()` is called after every step, and immediately whenever the server says stop.

## Output

Each step function must **return once the robot has finished the step and stopped**. `ZoneRush.h` then tells the server the step is done, and the next turn can start once every robot has finished.

## Helpers

### `waitMs(ms)`

Use **`waitMs(ms)` instead of `delay(ms)`** inside your step functions. While it waits it keeps listening to the server, so an emergency stop still works in the middle of a step. It returns `false` if the server said stop: then `return` from your function straight away (the motors are stopped for you).

```cpp
void stepForward() {
  drive(200, 200);              // your own helper: left and right motor speeds
  if (!waitMs(900)) return;     // drive for 0.9 s, unless the server says stop
  stopMotors();
}
```

### The kit's motors

The KS0428's L298P motor shield drives each track with two pins:

| Track | Direction pin | Speed pin (PWM) |
| --- | --- | --- |
| Left | `13` | `11` |
| Right | `12` | `3` |

Set both pins as `OUTPUT` in `setup()`. Direction `LOW` = forwards, `HIGH` = backwards; speed is `analogWrite(pin, 0–255)`. Turning on the spot = one track forwards, the other backwards.

## Rules

1. Write your code in **`robot_sketch.ino`** only. Do **not** change **`ZoneRush.h`**, and keep `#include "ZoneRush.h"`.
2. Keep **`zoneRushBegin(Serial, ROBOT_NAME)`** in `setup()` and **`zoneRushUpdate()`** in `loop()`.
3. Do **not** change the names of the five functions: `stepForward`, `stepBack`, `turnLeft`, `turnRight`, `stopMotors`.
4. **Your robot only moves inside the step functions.** Never start the motors anywhere else.
5. Use **`waitMs()`**, not `delay()`, for anything longer than a few milliseconds.
6. Do **not** use `Serial` yourself (no `Serial.print`, no `Serial.read`): it is your robot's Bluetooth link to the server.
7. Each step should take about **1–2 seconds**. A step that takes longer than **8 seconds** is treated as a robot fault.
8. `ROBOT_NAME` must be your **team's name** (with `-` instead of spaces): it is how the server finds your robot and pairs it with your bot.

## Safety built into `ZoneRush.h`

- The robot only moves while the server has **armed** it, and only for a step the server sent.
- The same step is never run twice, even if a message is repeated over Bluetooth.
- If your robot hears nothing from the server for **5 seconds**, it stops and disarms.
- Stop (`X`) works at any time, including in the middle of a step.

## What happens if your robot gets it wrong

The game always follows the server (rulebook 4.3). If your robot doesn't finish a step, stops answering, or ends up on the wrong cell, the game pauses, a referee puts it on the correct cell by hand, and the Head Referee decides whether it is a **time penalty** (your bot is frozen for the next 3 turns) or not your team's fault (rulebook 4.4). Poor calibration (overshooting, undershooting, drifting) is a time penalty, so **calibrate before your games**.

## Calibrating

1. Put the robot on a cell and try `stepForward()` on its own: adjust the time (and speed) until it stops in the centre of the next cell.
2. Same for `turnLeft()` and `turnRight()`: adjust until it turns exactly 90°.
3. If it drifts to one side when driving straight, give the slower track a little more speed.
4. If a track runs the wrong way, swap `LOW` and `HIGH` for that track's direction pin.
5. Batteries matter: a fresher battery drives further in the same time. Re-check after changing batteries.

## Uploading

1. Unplug the **Bluetooth module** first: it shares pins 0 and 1 with the USB cable, and the upload fails while it is connected.
2. In the Arduino IDE choose **Arduino Uno**, the right port, and upload.
3. Plug the Bluetooth module back in.

## Testing with the server

The organisers will connect your robot to the game server for the robot check (rulebook 4.1). There you can drive it step by step (`F`, `B`, `L`, `R`) and see each step's time, before your first game.
