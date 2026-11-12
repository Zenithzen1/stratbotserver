/*
  ZoneRush.h: the organisers' link between your robot and the game server.
  DO NOT CHANGE THIS FILE. It is the same for every team.

  What it does
    It listens to the server over Bluetooth, and when the server sends a step it calls one of
    YOUR functions (stepForward, stepBack, turnLeft, turnRight), then tells the server the
    robot has finished. The server only sends steps for moves the game has already approved:
    your robot never decides anything on its own.

  What your sketch must have
    void stepForward();   drive forward exactly one cell, then stop
    void stepBack();      drive backwards exactly one cell, then stop
    void turnLeft();      turn 90 degrees left on the spot, then stop
    void turnRight();     turn 90 degrees right on the spot, then stop
    void stopMotors();    stop both motors immediately
    setup(): Serial.begin(9600); zoneRushBegin(Serial, "YOUR-NAME");
    loop():  zoneRushUpdate();

  What you can use
    waitMs(ms)   use instead of delay() inside your step functions. While it waits it keeps
                 answering the server. It returns false if the server said STOP: then return
                 from your function straight away (the motors are stopped for you).

  Protocol v1 (for the curious): the server sends "<seq> <cmd>" lines. Commands: H hello,
  A arm, X stop+disarm, P ping, F forward, B back, L left, R right. The robot answers
  "<seq> HELLO <name> <firmware>", "<seq> OK", or "<seq> ACK" when a step starts and
  "<seq> DONE" when it has finished ("<seq> ERR ..." on errors). Safety: motion only while
  armed by the server, a repeated <seq> never runs twice, and 5 s without hearing from the
  server stops and disarms the robot.
*/
#ifndef ZONERUSH_H
#define ZONERUSH_H

#include <Arduino.h>

#define ZONERUSH_FIRMWARE "zr-1"

// ---- your sketch defines these ----
void stepForward();
void stepBack();
void turnLeft();
void turnRight();
void stopMotors();

// ---- the link ------------------------------------------------------------------------------
namespace zonerush {

const unsigned long WATCHDOG_MS = 5000;

static Stream *link = nullptr;
static const char *robotName = "ROBOT";
static bool armed = false;
static bool moving = false;
static bool stopRequested = false;
static unsigned long lastSeq = 0;
static unsigned long motionSeq = 0;
static unsigned long lastHeard = 0;
static char lastReply[32] = "";
static char motionState[16] = "";
static char lineBuf[24];
static int lineLen = 0;

static void send(unsigned long seq, const char *text) {
  link->print(seq);
  link->print(' ');
  link->print(text);
  link->print('\n');
}

static void reply(unsigned long seq, const char *text) {
  strncpy(lastReply, text, sizeof(lastReply) - 1);
  lastReply[sizeof(lastReply) - 1] = 0;
  send(seq, lastReply);
}

static void runStep(unsigned long seq, char cmd);

// One complete line from the server.
static void handleLine(char *line) {
  lastHeard = millis();
  char *space = strchr(line, ' ');
  if (space == NULL) return;
  *space = 0;
  unsigned long seq = strtoul(line, NULL, 10);
  char cmd = space[1];
  if (seq == 0 || cmd == 0 || space[2] != 0) return;          // not a command: ignore it

  if (cmd == 'H') {                                            // a new session
    if (moving) stopRequested = true;
    lastSeq = seq;
    motionSeq = 0;
    char hello[32];
    snprintf(hello, sizeof(hello), "HELLO %s %s", robotName, ZONERUSH_FIRMWARE);
    reply(seq, hello);
    return;
  }
  if (seq == motionSeq) { send(seq, motionState); return; }   // asked again: repeat, never re-run
  if (seq == lastSeq) { send(seq, lastReply); return; }
  if (seq < lastSeq) return;                                   // an old message: ignore it
  lastSeq = seq;

  switch (cmd) {
    case 'A': armed = true; reply(seq, "OK"); break;
    case 'X': armed = false; if (moving) stopRequested = true; stopMotors(); reply(seq, "OK"); break;
    case 'P': reply(seq, "OK"); break;
    case 'F': case 'B': case 'L': case 'R':
      if (!armed) reply(seq, "ERR DISARMED");
      else if (moving) reply(seq, "ERR BUSY");
      else runStep(seq, cmd);
      break;
    default: reply(seq, "ERR UNKNOWN");
  }
}

// Read whatever the server has sent so far.
static void service() {
  while (link->available()) {
    char ch = link->read();
    if (ch == '\n' || ch == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = 0;
        lineLen = 0;
        handleLine(lineBuf);
      }
    } else if (lineLen < (int)sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = ch;
    }
  }
}

// Run one of the team's step functions, answering ACK before and DONE after.
static void runStep(unsigned long seq, char cmd) {
  motionSeq = seq;
  strcpy(motionState, "ACK");
  send(seq, "ACK");
  moving = true;
  stopRequested = false;
  if (cmd == 'F') stepForward();
  if (cmd == 'B') stepBack();
  if (cmd == 'L') turnLeft();
  if (cmd == 'R') turnRight();
  stopMotors();
  moving = false;
  strcpy(motionState, stopRequested ? "ERR STOPPED" : "DONE");
  send(seq, motionState);
  lastHeard = millis();
}

}  // namespace zonerush

// ---- what your sketch calls ------------------------------------------------------------------

inline void zoneRushBegin(Stream &link, const char *robotName) {
  zonerush::link = &link;
  zonerush::robotName = robotName;
  zonerush::lastHeard = millis();
  stopMotors();
}

inline void zoneRushUpdate() {
  zonerush::service();
  if (zonerush::armed && millis() - zonerush::lastHeard > zonerush::WATCHDOG_MS) {
    zonerush::armed = false;                // the server has gone quiet: stop and disarm
    stopMotors();
  }
}

// Wait `ms` milliseconds while still listening to the server.
// Returns true when the time is up, false straight away if the server said STOP.
inline bool waitMs(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) {
    if (zonerush::stopRequested) return false;
    zonerush::service();
  }
  return !zonerush::stopRequested;
}

#endif
