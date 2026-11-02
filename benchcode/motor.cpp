#include <Servo.h>
#include "motor.h"
#include "bench.h"
#include "pot.h"
#include "pins.h"

static Servo esc;                        // o sinal do ESC no D9 (50 pulsos por segundo). Só este ficheiro lhe pode mexer.
static int percent = 0;                  // throttle atual
static MotorMode mode = MODE_SERVER;     // no arranque é o servidor que controla o throttle (comando MOTOR)

static void writePercent(int p) {
    percent = p;
    esc.writeMicroseconds(ESC_PULSE_MIN + (long)p * (ESC_PULSE_MAX - ESC_PULSE_MIN) / 100);
}

// Posição do pot -> throttle %, como no esc_controller:
//   até POT_LEFT_ZERO: zona morta, motor parado (o ruído do pot nunca mexe o motor)
//   acima disso: de MOTOR_START_PERCENT (primeiro valor que roda mesmo) até MOTOR_MAX_PERCENT
static int potToPercent(int pot) {
    if (pot <= POT_LEFT_ZERO) return 0;
    return map(pot, POT_LEFT_ZERO, 1023, MOTOR_START_PERCENT, MOTOR_MAX_PERCENT);
}


// Função chamada no setup para fazer setup ao motor, definindo qual o pino do ESC (PIN_ESC)
// e a velocidade inicial do motor a zero (0%).
void initialMotorSetup() {
    esc.attach(PIN_ESC, ESC_PULSE_MIN, ESC_PULSE_MAX);
    writePercent(0);
}

void updateMotor() {
    if (!isBenchUnlocked()) {              // LOCKED / UNLOCKING: nunca roda, em nenhum modo
        if (percent != 0) writePercent(0);
        return;
    }
    if (mode == MODE_POT) writePercent(potToPercent(potValue()));
    // modo SERVER: mantém o último valor do comando MOTOR
}

void motorStop() {
    writePercent(0);
}

bool motorSet(long p) {
    if (mode != MODE_SERVER) return false;              // em modo POT quem manda é o pot
    if (p < 0 || p > MOTOR_MAX_PERCENT) return false;   // nunca acima do limite
    if (p > 0 && !isBenchUnlocked()) return false;      // só um banco UNLOCKED pode pôr o motor a rodar
    writePercent(p);
    return true;
}

int motorPercent() {
    return percent;
}

bool motorSetMode(MotorMode m) {
    if (!isBenchLocked()) return false;    // só LOCKED (não UNLOCKING, não UNLOCKED)
    mode = m;
    motorStop();
    return true;
}

MotorMode motorMode() {
    return mode;
}

const __FlashStringHelper* motorModeName() {
    return mode == MODE_POT ? F("POT") : F("SERVER");
}
