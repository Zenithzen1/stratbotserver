/*
  Zone Rush stand-in robot for the ESP32 (Keyestudio ESP32 Plus, board "esp32da").

  It is a robot sketch like any team's: the same ZoneRush.h link to the server, and the same five
  step functions. It has no motors, so each step just takes time. Over Bluetooth it imitates the
  kit's HM-10 module (service FFE0, characteristic FFE1), so the server talks to it exactly as it
  will to a real robot.

  Its robot name (what a team's ROBOT_NAME would be) can be changed without reflashing, so it can
  stand in for any team: the server pairs robots with teams by this name.

  USB serial (115200) shows every message, and takes test commands (type them, then Enter):
    name Krauts  answer as team "Krauts" from now on (kept after power-off; restarts the board)
    d            the next step never finishes on its own (to test a stuck robot; the server stops it)
    o            go silent / answer again (to test a robot that stops responding)
    k            drop the Bluetooth connection
    s            status
*/
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Preferences.h>
#include "ZoneRush.h"

#define DEFAULT_NAME "ZR-STANDIN"
char robotName[24] = DEFAULT_NAME;     // set with "name <team>" over USB, kept in flash
Preferences prefs;

const unsigned long STEP_MS = 700;   // pretend time for one cell
const unsigned long TURN_MS = 450;   // pretend time for 90 degrees

// ---- Bluetooth, as a Stream (what ZoneRush.h reads and writes) --------------------------------
BLECharacteristic *uart = nullptr;
volatile bool bleConnected = false;
bool advertising = false;
unsigned long disconnectedAt = 0;

class BleUartStream : public Stream {
 public:
  // incoming bytes are queued by the Bluetooth task (put) and read by the sketch
  void put(const uint8_t *data, size_t n) {
    portENTER_CRITICAL(&mux);
    for (size_t i = 0; i < n; i++) {
      int next = (head + 1) % SIZE;
      if (next == tail) break;                 // full: drop the rest
      buf[head] = data[i];
      head = next;
    }
    portEXIT_CRITICAL(&mux);
  }
  int available() override {
    portENTER_CRITICAL(&mux);
    int n = (head - tail + SIZE) % SIZE;
    portEXIT_CRITICAL(&mux);
    return n;
  }
  int read() override {
    int ch = -1;
    portENTER_CRITICAL(&mux);
    if (tail != head) { ch = buf[tail]; tail = (tail + 1) % SIZE; }
    portEXIT_CRITICAL(&mux);
    if (ch >= 0) logIn((char)ch);
    return ch;
  }
  int peek() override {
    int ch = -1;
    portENTER_CRITICAL(&mux);
    if (tail != head) ch = buf[tail];
    portEXIT_CRITICAL(&mux);
    return ch;
  }
  size_t write(uint8_t c) override {           // outgoing: sent line by line, 20-byte packets
    if (outLen == 0) Serial.print(">> ");
    Serial.write(c);
    out[outLen++] = c;
    if (c == '\n' || outLen == sizeof(out)) sendOut();
    return 1;
  }
  void flush() override {}

 private:
  static const int SIZE = 256;
  volatile uint8_t buf[SIZE];
  volatile int head = 0, tail = 0;
  portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
  uint8_t out[64];
  size_t outLen = 0;
  bool inLineStart = true;

  void sendOut() {
    if (bleConnected && uart != nullptr) {
      for (size_t i = 0; i < outLen; i += 20) {
        size_t len = (outLen - i < 20) ? outLen - i : 20;
        uart->setValue(out + i, len);
        uart->notify();
        delay(3);
      }
    }
    outLen = 0;
  }
  void logIn(char ch) {
    if (inLineStart) Serial.print("<< ");
    Serial.write(ch);
    inLineStart = (ch == '\n');
  }
};

BleUartStream bleLink;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *s) override { bleConnected = true; advertising = false; }
  void onDisconnect(BLEServer *s) override { bleConnected = false; disconnectedAt = millis(); }
};

class UartCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String v = c->getValue();
    bleLink.put((const uint8_t *)v.c_str(), v.length());
  }
};

// ---- test keys --------------------------------------------------------------------------------
bool hangNext = false, silent = false;

char usbLine[40];
int usbLen = 0;

void testCommand(char *cmd) {
  if (strncmp(cmd, "name ", 5) == 0 && strlen(cmd + 5) > 0) {
    prefs.putString("name", cmd + 5);
    Serial.printf("-- robot name set to %s, restarting\n", cmd + 5);
    delay(200);
    ESP.restart();
  }
  if (strcmp(cmd, "d") == 0) { hangNext = true; Serial.println("-- next step will hang until the server stops it"); }
  if (strcmp(cmd, "o") == 0) { silent = !silent; Serial.printf("-- silent: %s\n", silent ? "on" : "off"); }
  if (strcmp(cmd, "k") == 0 && bleConnected) BLEDevice::getServer()->disconnect(BLEDevice::getServer()->getConnId());
  if (strcmp(cmd, "s") == 0) Serial.printf("-- robot %s, Bluetooth connected: %d\n", robotName, bleConnected);
}

void testKeys() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (usbLen > 0) { usbLine[usbLen] = 0; usbLen = 0; testCommand(usbLine); }
    } else if (usbLen < (int)sizeof(usbLine) - 1) {
      usbLine[usbLen++] = ch;
    }
  }
}

// ---- setup / loop -------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  prefs.begin("zonerush", false);
  String saved = prefs.getString("name", DEFAULT_NAME);
  saved.toCharArray(robotName, sizeof(robotName));
  BLEDevice::init(robotName);
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService *service = server->createService(BLEUUID((uint16_t)0xFFE0));
  uart = service->createCharacteristic(
      BLEUUID((uint16_t)0xFFE1),
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE |
      BLECharacteristic::PROPERTY_WRITE_NR | BLECharacteristic::PROPERTY_NOTIFY);
  uart->addDescriptor(new BLE2902());
  uart->setCallbacks(new UartCallbacks());
  service->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(BLEUUID((uint16_t)0xFFE0));
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
  advertising = true;

  zoneRushBegin(bleLink, robotName);
  Serial.printf("robot %s (%s) ready, advertising over Bluetooth\n", robotName, ZONERUSH_FIRMWARE);
  Serial.println("commands: name <team>, d = next step hangs, o = silent on/off, k = drop Bluetooth, s = status");
}

void loop() {
  if (!bleConnected && !advertising && millis() - disconnectedAt > 300) {
    stopMotors();
    BLEDevice::startAdvertising();
    advertising = true;
    Serial.println("-- disconnected, advertising again");
  }
  testKeys();
  if (silent) {
    while (bleLink.available()) bleLink.read();   // heard, but never answered
  } else {
    zoneRushUpdate();
  }
  delay(2);
}

// ---- the five step functions (no motors: each step just takes time) ----------------------------
void pretend(const char *what, unsigned long ms) {
  Serial.printf("-- %s\n", what);
  if (hangNext) {
    hangNext = false;
    Serial.println("-- (stuck)");
    waitMs(600000);                                 // until the server says STOP
    return;
  }
  waitMs(ms);
}

void stepForward() { pretend("forward one cell", STEP_MS); }
void stepBack()    { pretend("back one cell", STEP_MS); }
void turnLeft()    { pretend("turn left", TURN_MS); }
void turnRight()   { pretend("turn right", TURN_MS); }
void stopMotors()  { }
