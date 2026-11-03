#include "bench.h"
#include "battery.h"
#include "motor.h"
#include "pot.h"
#include "pins.h"
#include "safety.h"

enum BenchState { BENCH_LOCKED, BENCH_UNLOCKING, BENCH_UNLOCKED };
static BenchState benchState = BENCH_LOCKED;      // arranca sempre bloqueado

// Um clique só conta depois de o botão ter sido visto solto. Começa a false para que um
// botão encravado (ou segurado desde o arranque) nunca desbloqueie o banco; volta a false
// depois de desbloquear, para o dedo que ainda está no botão não o bloquear outra vez.
static bool seenReleased = false;
static bool holding = false;               // botão a ser segurado durante o UNLOCKING
static unsigned long pressedAt = 0;        // quando começou o clique atual
static unsigned long unlockRequestedAt = 0;

// Porque é que o banco foi bloqueado da última vez (mostrado pelo BENCH). NULL = nunca bloqueado desde o arranque.
static const __FlashStringHelper* lockReason = NULL;
// Conta as mudanças de estado (ou de motivo). O EVT BENCH (commands.cpp) é enviado quando este número muda.
static unsigned int stateVersion = 0;
static uint8_t lockProblems = 0;           // as verificações que falharam, quando o motivo é CHECK

// ---------------------------------------------------------------------------
// Verificações para desbloquear
// ---------------------------------------------------------------------------

// Um bit por problema, para se poderem indicar vários ao mesmo tempo.
const uint8_t PROBLEM_NO_BATTERY   = 1 << 0;   // D6 a LOW: bateria não ligada ao ESC
const uint8_t PROBLEM_ESC_ARMING   = 1 << 1;   // ligada, mas há menos de BAT_ARM_MS
const uint8_t PROBLEM_LOW_VOLTAGE  = 1 << 2;   // abaixo de BAT_LOW_V (ou sem cabo de balanceamento)
const uint8_t PROBLEM_POT_NOT_ZERO = 1 << 3;   // pot do throttle não está em zero
const uint8_t PROBLEM_BATTERY_CUT  = 1 << 4;   // viu-se uma bateria mesmo baixa: carregá-la e fazer reset
const uint8_t PROBLEM_SERVER_LOST  = 1 << 5;   // sem sinal do servidor há SERVER_TIMEOUT_MS

// A função importante: o que impede o banco de ser desbloqueado agora.
// 0 = nada, pronto a desbloquear.
static uint8_t unlockProblems() {
    uint8_t problems = 0;
    if (!batteryConnected())             problems |= PROBLEM_NO_BATTERY;
    else if (!batteryArmed())            problems |= PROBLEM_ESC_ARMING;
    if (batteryLastVolts() < BAT_LOW_V)  problems |= PROBLEM_LOW_VOLTAGE;
    if (!potAtZero())                    problems |= PROBLEM_POT_NOT_ZERO;
    if (batteryLowCut())                 problems |= PROBLEM_BATTERY_CUT;
    if (serverLostConnection())          problems |= PROBLEM_SERVER_LOST;
    return problems;
}

static void printProblems(uint8_t problems) {
    if (problems & PROBLEM_NO_BATTERY)   Serial.print(F(" NO_BATTERY"));
    if (problems & PROBLEM_ESC_ARMING)   Serial.print(F(" ESC_ARMING"));
    if (problems & PROBLEM_LOW_VOLTAGE)  Serial.print(F(" LOW_VOLTAGE"));
    if (problems & PROBLEM_POT_NOT_ZERO) Serial.print(F(" POT_NOT_ZERO"));
    if (problems & PROBLEM_BATTERY_CUT)  Serial.print(F(" BATTERY_CUT"));
    if (problems & PROBLEM_SERVER_LOST)  Serial.print(F(" SERVER_LOST"));
}

void printUnlockProblems() {
    printProblems(unlockProblems());
}

// ---------------------------------------------------------------------------
// Bloquear / desbloquear
// ---------------------------------------------------------------------------

// Põe tudo num estado seguro.
// (motor a 0 %, buzzer desligado.)
static void makeSafe() {
    motorStop();
    noTone(PIN_BUZZER);
}

// Todos os bloqueios passam por aqui, com o motivo (e as verificações que falharam, se houver).
static void lockFor(const __FlashStringHelper* reason, uint8_t problems = 0) {
    makeSafe();
    if (benchState != BENCH_LOCKED || lockReason != reason || lockProblems != problems) stateVersion++;   // mudou
    benchState = BENCH_LOCKED;
    holding = false;
    lockReason = reason;
    lockProblems = problems;
}

void lockBench() {
    lockFor(F("STOP"));
}

bool requestUnlock() {
    if (benchState == BENCH_UNLOCKED) return true;     // já está desbloqueado: nada a fazer
    if (unlockProblems() != 0) return false;           // falta alguma coisa: fica como está
    if (benchState == BENCH_LOCKED) {
        tone(PIN_BUZZER, 2000, 100);                   // apito curto: carregue no botão
        stateVersion++;                                // LOCKED -> UNLOCKING (outro UNLOCK em UNLOCKING não muda nada)
    }
    benchState = BENCH_UNLOCKING;                      // só ESPERA pelo botão
    unlockRequestedAt = millis();
    holding = false;
    seenReleased = false;    // só conta um clique que COMEÇA depois do UNLOCK: um botão encravado
                             // (ou alguém que já o está a segurar) nunca desbloqueia o banco
    return true;
}

bool isBenchUnlocked() {
    return benchState == BENCH_UNLOCKED;
}

bool isBenchLocked() {
    return benchState == BENCH_LOCKED;
}

unsigned int benchStateVersion() {
    return stateVersion;
}

void printBenchState() {
    Serial.print(benchStateName());
    if (benchState != BENCH_LOCKED) return;
    Serial.print(' ');
    Serial.print(lockReason != NULL ? lockReason : F("STARTUP"));
    printProblems(lockProblems);
}

const __FlashStringHelper* benchStateName() {
    switch (benchState) {
        case BENCH_LOCKED:    return F("LOCKED");
        case BENCH_UNLOCKING: return F("UNLOCKING");
        case BENCH_UNLOCKED:  return F("UNLOCKED");
    }
    return F("?");
}

// Leitura do botão com debounce: true enquanto o botão está (de forma estável) carregado.
static bool readButton() {
    static bool lastReading = false;     // 'static' dentro de uma função: guarda o valor entre chamadas
    static bool stable = false;
    static unsigned long changedAt = 0;
    bool now = digitalRead(PIN_BUTTON) == LOW;
    if (now != lastReading) {
        lastReading = now;
        changedAt = millis();
    }
    if (millis() - changedAt >= DEBOUNCE_MS) stable = lastReading;
    return stable;
}

static void updateLock() {
    bool pressed = readButton();
    if (!pressed) {
        seenReleased = true;
        holding = false;                                   // largou: os 2 s começam de novo
    }

    switch (benchState) {
        case BENCH_LOCKED:
            break;                                         // só o comando UNLOCK sai de LOCKED

        case BENCH_UNLOCKING:
            {
                uint8_t problems = unlockProblems();
                if (problems != 0) {                       // falhou uma verificação durante a espera
                    lockFor(F("CHECK"), problems);
                    break;
                }
            }
            if (!holding && millis() - unlockRequestedAt >= UNLOCK_WAIT_MS) {
                lockFor(F("TIMEOUT"));                     // ninguém carregou no botão a tempo
                break;
            }
            if (pressed && seenReleased) {
                if (!holding) {                            // um clique novo: começa a contar
                    holding = true;
                    pressedAt = millis();
                } else if (millis() - pressedAt >= UNLOCK_HOLD_MS) {
                    benchState = BENCH_UNLOCKED;           // o ÚNICO sítio que desbloqueia
                    stateVersion++;
                    holding = false;
                    seenReleased = false;                  // este clique não pode voltar a bloquear
                    tone(PIN_BUZZER, 2000, 500);           // apito longo: desbloqueado
                }
            }
            break;

        case BENCH_UNLOCKED:
            if (serverLostConnection()) {                  // não ouviu sinais do servidor há SERVER_TIMEOUT_MS
                lockFor(F("SERVER_LOST"));
                tone(PIN_BUZZER, 3000, 600);               // apito agudo e longo: servidor
            } else if (!batteryConnected()) {              // bateria desligada com o banco desbloqueado
                lockFor(F("NO_BATTERY"));
                tone(PIN_BUZZER, 1000, 150);
            } else if (batteryLowTooLong()) {              // bateria vazia (ou cabo de balanceamento solto) durante 2 s
                lockFor(F("LOW_VOLTAGE"));
                tone(PIN_BUZZER, 1000, 600);               // apito grave e longo: bateria
            } else if (pressed && seenReleased) {          // um toque: bloqueia
                lockFor(F("BUTTON"));
                seenReleased = false;
                tone(PIN_BUZZER, 1000, 150);               // apito curto: bloqueado
            }
            break;
    }
}

// Mostra o estado do bloqueio nos LEDs:
//   LOCKED = vermelho aceso | UNLOCKING = vermelho a piscar (mais depressa com o botão segurado) | UNLOCKED = verde aceso
//   ESC a armar (bateria ligada há menos de BAT_ARM_MS) = os 3 LEDs à roda: vermelho, verde, amarelo, BLINK_ARMING_MS cada
static void showBenchState() {
    // ESC a armar: só acontece em LOCKED (o ESC_ARMING impede o UNLOCK), por isso nunca esconde outro estado.
    // Aqui este é o ÚNICO dono dos 3 LEDs: o showBattery() não mexe no amarelo enquanto o ESC arma.
    if (batteryConnected() && !batteryArmed()) {
        int phase = (millis() / BLINK_ARMING_MS) % 3;    // 0, 1, 2, 0, 1, 2... a cada 100 ms
        digitalWrite(PIN_RED,    phase == 0);
        digitalWrite(PIN_GREEN,  phase == 1);
        digitalWrite(PIN_YELLOW, phase == 2);
        return;
    }

    unsigned long blinkMs = holding ? BLINK_HOLD_MS : BLINK_MS;
    bool blinkOn = (millis() / blinkMs) % 2;
    digitalWrite(PIN_RED, benchState == BENCH_LOCKED || (benchState == BENCH_UNLOCKING && blinkOn));
    digitalWrite(PIN_GREEN, benchState == BENCH_UNLOCKED);
}

// Tem de correr em TODAS as voltas do loop, não só quando chega um comando.
void updateBench() {
    updateBattery();
    updatePot();
    updateLock();
    showBenchState();    // em todas as voltas: apanha também um bloqueio feito pelo STOP (lockBench)
}
