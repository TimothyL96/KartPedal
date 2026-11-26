#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "esp_timer.h"
#include <atomic>
extern "C" {
#include "src/bosch/bmi270.h"
}
#include "v18_format.h"
enum Kind : uint8_t { SAMPLE, ANCHOR, GAP, EDGE, VOLTAGE, EPOCH, FIFO_READ, SENSOR_FAULT };
struct Item { Kind kind; uint8_t stream; Sample r; uint64_t end; uint32_t detail; };
extern QueueHandle_t items;
extern std::atomic<int> statusCode;
enum Phase { GRACE, MAINTENANCE, STARTING, RECORD, STOPPING, SAFE_OFF, ERROR_STOPPED };
enum Reason { USER, LOW_BATTERY, FAULT };
extern std::atomic<int> reason;
extern std::atomic<bool> acquisitionStopped;
extern std::atomic<uint32_t> highWater;
extern std::atomic<unsigned> activeSubmits;
extern bool bench;
inline uint64_t nowUs(){return esp_timer_get_time();}
void requestStop(Reason r);
bool submit(Item &i);
bool setupSensors(int number=2);
void probeSensors(int number);
bool probeCard();
bool flushSensors();
bool pollSensor(int index);
bool openStorage();
bool mountRecordingCard();
void writer(void*);

