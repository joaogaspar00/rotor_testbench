#pragma once
#include <Arduino.h>

// Motor: o sinal do ESC no PIN_ESC, como percentagem de throttle.
//   0 %   = ESC_PULSE_MIN (1000 us) = motor parado
//   100 % = ESC_PULSE_MAX (2000 us) = aceleração máxima
// Nunca acima de MOTOR_MAX_PERCENT, e nunca acima de 0 % sem o banco UNLOCKED.
//
// Dois modos, ou seja, quem controla o throttle:
//   POT                  -> o potenciómetro, como no esc_controller
//   SERVER (no arranque) -> o comando MOTOR <0..100>
// O modo só pode mudar com o banco LOCKED (para o throttle nunca dar saltos).

enum MotorMode { MODE_POT, MODE_SERVER };

// PRIMEIRA coisa do setup(): começa o sinal do ESC a 0 % (motor parado).
void initialMotorSetup();

// Em cada volta do loop: em modo POT segue o pot; em qualquer modo, 0 % enquanto não estiver UNLOCKED.
void updateMotor();

// Motor a 0 % imediatamente. Sempre permitido (usado quando o banco bloqueia).
void motorStop();

// Só em modo SERVER: define o throttle. Devolve false (e não muda nada) se não estiver em
// modo SERVER, se estiver fora de 0..MOTOR_MAX_PERCENT, ou se for acima de 0 % com o banco não UNLOCKED.
bool motorSet(long percent);

// Throttle atual, em % (nos dois modos).
int motorPercent();

// Muda o modo. Devolve false (e não muda nada) se o banco não estiver LOCKED.
bool motorSetMode(MotorMode mode);

MotorMode motorMode();

// "POT" ou "SERVER" (guardado na memória flash)
const __FlashStringHelper* motorModeName();
