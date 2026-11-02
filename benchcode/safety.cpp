#include "safety.h"
#include "pins.h"

static unsigned long lastServerSeen = 0;

bool serverLostConnection() {
    return millis() - lastServerSeen >= SERVER_TIMEOUT_MS;
}

void serverSeenConnection() {
    lastServerSeen = millis();
}