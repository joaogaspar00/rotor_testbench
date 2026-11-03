#pragma once
#include <Arduino.h>

// Bloqueio do banco: o Nano é o ÚNICO dono do estado do bloqueio.
//
//   LOCKED    -- comando UNLOCK, todas as verificações OK -->  UNLOCKING  (LED vermelho a piscar)
//   UNLOCKING -- botão segurado UNLOCK_HOLD_MS             -->  UNLOCKED   (LED verde aceso)
//   UNLOCKING -- falha uma verificação / sem botão em UNLOCK_WAIT_MS  -->  LOCKED
//   UNLOCKED  -- um toque, STOP, bateria desligada                    -->  LOCKED
//
// Qualquer um pode BLOQUEAR. Só o botão pode acabar o desbloqueio: o comando UNLOCK só
// COMEÇA o procedimento, por isso tem de estar sempre alguém ao pé do banco.

// Em cada volta do loop, mesmo sem o servidor: bateria, pot, botão, LEDs.
void updateBench();

// Bloqueia o banco e põe tudo num estado seguro. Qualquer um a pode chamar.
// (O motivo do bloqueio mostrado pelo printBenchState() é "STOP".)
void lockBench();

// Comando UNLOCK: se todas as verificações passarem, vai para UNLOCKING (espera pelo botão)
// e devolve true. Devolve false (e não muda nada) se faltar alguma coisa.
bool requestUnlock();

// Imprime o que falta para desbloquear, p. ex.: " NO_BATTERY POT_NOT_ZERO" (nada se estiver pronto).
void printUnlockProblems();

// True só quando o banco está desbloqueado (o motor só roda quando isto é true).
bool isBenchUnlocked();

// True só quando o banco está LOCKED (não UNLOCKING, não UNLOCKED).
bool isBenchLocked();

// "LOCKED", "UNLOCKING" ou "UNLOCKED" (guardado na memória flash, como o F("..."))
const __FlashStringHelper* benchStateName();

// O estado e, quando LOCKED, porque foi bloqueado, p. ex.:
//   "UNLOCKED"   "LOCKED STARTUP"   "LOCKED BUTTON"   "LOCKED CHECK POT_NOT_ZERO"
void printBenchState();

// Um número que muda sempre que o estado (ou o motivo do bloqueio) muda. Usado pelo EVT BENCH.
unsigned int benchStateVersion();
