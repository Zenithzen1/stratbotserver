// You may implement your robot's code in this file
// Please read the README file for the rules and implementation support

/*
How your robot plays:
    Your bot.py decides your moves. The game server checks them, plays the turn on the official
    board, and only then sends your robot the steps to act out an approved move, over Bluetooth.
    ZoneRush.h (do not change it) receives those steps and calls the functions below.

Steps (input):
    stepForward()  = drive forward exactly one cell, then stop
    stepBack()     = drive backwards exactly one cell, then stop
    turnLeft()     = turn 90 degrees left on the spot, then stop
    turnRight()    = turn 90 degrees right on the spot, then stop
    stopMotors()   = stop both motors immediately (also used for emergency stops)

Expected behaviour (output):
    Each step function returns once the robot has finished that step and stopped.
    Use waitMs(ms) instead of delay(ms). If waitMs returns false, the server said STOP:
    return from the function straight away.
*/

#include "ZoneRush.h" // The link to the game server. Do not change or remove this line

#define ROBOT_NAME "MY-TEAM" // Your TEAM'S NAME, exactly as registered (use - instead of spaces).
                             // The server pairs your robot with your bot by this name

void setup() {
  // Set up your motor pins here

  stopMotors();
  Serial.begin(9600);                 // The Bluetooth module is on Serial, at 9600 baud
  zoneRushBegin(Serial, ROBOT_NAME);  // Do not remove this line
}

void loop() {
  zoneRushUpdate();                   // Do not remove this line: it listens to the server and runs your steps
}

void stepForward() {
  // Write this function
}

void stepBack() {
  // Write this function
}

void turnLeft() {
  // Write this function
}

void turnRight() {
  // Write this function
}

void stopMotors() {
  // Write this function
}

// You are allowed to add your own functions and variables in the rest of this file.
// But the robot only moves when the server sends a step: never start the motors anywhere else.
// Do not use Serial yourself (no Serial.print): it is your robot's Bluetooth link to the server.
