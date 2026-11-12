// Organisers' reference robot sketch for the Keyestudio Mini Tank Robot V2 (KS0428).
// It is robot_sketch.ino filled in: the same ZoneRush.h link, with working step functions.
// Not for teams: it is the organisers' known-good robot (and a fallback on the day).
//
// Kit: UNO-compatible board, L298P motor shield, HM-10 Bluetooth module on Serial (pins 0/1).
// Motor pins are Keyestudio's own (KS0428 docs, project 15). Direction LOW = forwards.
// Before uploading, unplug the Bluetooth module (it shares pins 0/1 with USB); plug it back after.

#include "ZoneRush.h"

#define ROBOT_NAME "KS0428-REF"

// ----- calibration: measure on the arena (python -m zonerush robot <config> <seat>) -----
const unsigned long CELL_MS = 900;    // driving time for one cell
const unsigned long TURN_MS = 520;    // turning time for 90 degrees
const int SPEED = 200;                // driving speed, 0-255
const int TURN_SPEED = 220;           // turning speed, 0-255
const int LEFT_TRIM = 0;              // added to the left motor's speed, to drive straight
const int RIGHT_TRIM = 0;             // added to the right motor's speed
const bool LEFT_REVERSED = false;     // true if the left track runs the wrong way
const bool RIGHT_REVERSED = false;    // true if the right track runs the wrong way
const unsigned long SETTLE_MS = 150;  // pause after each step so the robot is still

const int ML_Ctrl = 13, ML_PWM = 11;  // left motor: direction, speed
const int MR_Ctrl = 12, MR_PWM = 3;   // right motor: direction, speed

void motor(int ctrlPin, int pwmPin, int speed, bool reversed) {
  if (reversed) speed = -speed;                       // > 0 forwards, < 0 backwards
  digitalWrite(ctrlPin, speed >= 0 ? LOW : HIGH);
  analogWrite(pwmPin, constrain(abs(speed), 0, 255));
}

void drive(int left, int right) {
  motor(ML_Ctrl, ML_PWM, left == 0 ? 0 : left + (left > 0 ? LEFT_TRIM : -LEFT_TRIM), LEFT_REVERSED);
  motor(MR_Ctrl, MR_PWM, right == 0 ? 0 : right + (right > 0 ? RIGHT_TRIM : -RIGHT_TRIM), RIGHT_REVERSED);
}

void setup() {
  pinMode(ML_Ctrl, OUTPUT); pinMode(ML_PWM, OUTPUT);
  pinMode(MR_Ctrl, OUTPUT); pinMode(MR_PWM, OUTPUT);
  stopMotors();
  Serial.begin(9600);
  zoneRushBegin(Serial, ROBOT_NAME);
}

void loop() {
  zoneRushUpdate();
}

void stepForward() {
  drive(SPEED, SPEED);
  if (!waitMs(CELL_MS)) return;
  stopMotors();
  waitMs(SETTLE_MS);
}

void stepBack() {
  drive(-SPEED, -SPEED);
  if (!waitMs(CELL_MS)) return;
  stopMotors();
  waitMs(SETTLE_MS);
}

void turnLeft() {
  drive(-TURN_SPEED, TURN_SPEED);
  if (!waitMs(TURN_MS)) return;
  stopMotors();
  waitMs(SETTLE_MS);
}

void turnRight() {
  drive(TURN_SPEED, -TURN_SPEED);
  if (!waitMs(TURN_MS)) return;
  stopMotors();
  waitMs(SETTLE_MS);
}

void stopMotors() {
  drive(0, 0);
}
