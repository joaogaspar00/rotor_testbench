#pragma once
#include <Arduino.h>

// Potentiometer on A6, filtered against electrical noise (buzzer, LEDs, ESC current
// through GND make the raw reading jump by tens of counts without touching the pot).
// Everybody reads the pot through here, never with analogRead().

// Every loop pass: samples and filters the pot, and updates "at zero".
void updatePot();

// Filtered pot value, 0..1023.
int potValue();

// True when the pot is at zero: enters below POT_ZERO, leaves only when above
// POT_LEFT_ZERO for POT_LEAVE_MS in a row.
bool potAtZero();