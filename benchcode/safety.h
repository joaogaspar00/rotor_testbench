#pragma once
#include <Arduino.h>

bool serverLostConnection();   // true se o servidor não deu sinais de vida há SERVER_TIMEOUT_MS
void serverSeenConnection();   // marca que o servidor deu sinais de vida