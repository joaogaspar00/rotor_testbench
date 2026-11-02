#include "commands.h"
#include "bench.h"
#include "battery.h"
#include "motor.h"
#include "pot.h"
#include "pins.h"
#include "safety.h"

// ---------------------------------------------------------------------------
// Funções de resposta: todas as respostas têm o mesmo formato
// ---------------------------------------------------------------------------

// "OK <NOME> <valor>"
static void replyOk(const Command& cmd, long value) {
    Serial.print(F("OK "));
    Serial.print(cmd.name);
    Serial.print(' ');
    Serial.println(value);
}

// "ERROR <NOME> invalid value: <valor>"
static void replyInvalidValue(const Command& cmd, const char* value) {
    Serial.print(F("ERROR "));
    Serial.print(cmd.name);
    Serial.print(F(" invalid value: "));
    Serial.println(value);
}

// ---------------------------------------------------------------------------
// Comandos: cada função só faz o seu trabalho.
// O número de valores (minArgs/maxArgs na tabela) já foi verificado pelo processInput.
// ---------------------------------------------------------------------------

// POT -> lê o potenciómetro (A6, filtrado)
static void cmdPot(const Command& cmd) {
    replyOk(cmd, potValue());
}

// STOP -> bloqueia o banco e põe tudo em segurança. SEMPRE aceite.
static void cmdStop(const Command&) {      // não usa o cmd: parâmetro sem nome
    lockBench();
    Serial.println(F("OK STOP"));
}

// TONE <freq> [ms]  -> toca freq Hz durante ms (0 ou nada = até TONE 0 / STOP)
// TONE 0            -> para
static void cmdTone(const Command& cmd) {
    long freq;
    if (!paramToLong(cmd, 0, freq) || (freq != 0 && (freq < TONE_MIN_HZ || freq > TONE_MAX_HZ))) {
        replyInvalidValue(cmd, cmd.params[0]);
        return;
    }
    long ms = 0;
    if (cmd.count == 2 && (!paramToLong(cmd, 1, ms) || ms < 0 || ms > TONE_MAX_MS)) {
        replyInvalidValue(cmd, cmd.params[1]);
        return;
    }

    if (freq == 0) {
        noTone(PIN_BUZZER);
        ms = 0;
    } else if (ms > 0) {
        tone(PIN_BUZZER, freq, ms);     // para sozinho
    } else {
        tone(PIN_BUZZER, freq);         // até TONE 0 / STOP
    }

    Serial.print(F("OK TONE "));
    Serial.print(freq);
    Serial.print(' ');
    Serial.println(ms);
}

// BENCH -> "OK BENCH UNLOCKING" / "OK BENCH UNLOCKED" / "OK BENCH LOCKED <reason>"
//   p. ex. "OK BENCH LOCKED STARTUP", "OK BENCH LOCKED CHECK POT_NOT_ZERO"
static void cmdBench(const Command&) {
    Serial.print(F("OK BENCH "));
    printBenchState();
    Serial.println();
}

// BAT -> "OK BAT <NONE|GOOD|WEAK|LOW> <volts>V", p. ex. "OK BAT GOOD 11.40V"
static void cmdBat(const Command&) {
    float volts = batteryVolts();

    Serial.print(F("OK BAT "));
    if (volts < BAT_NONE_V)      Serial.print(F("NONE "));
    else if (volts < BAT_LOW_V)  Serial.print(F("LOW "));
    else if (volts < BAT_WEAK_V) Serial.print(F("WEAK "));
    else                         Serial.print(F("GOOD "));
    Serial.print(volts, 2);                                                  // 2 casas decimais
    Serial.println('V');
}

// UNLOCK -> começa o procedimento de desbloqueio (ainda é preciso segurar o botão no banco)
//   pronto:     "OK UNLOCK UNLOCKING"  (LED vermelho a piscar, à espera do botão)
//   não pronto: "ERROR UNLOCK not ready: NO_BATTERY POT_NOT_ZERO" (o que falta)
static void cmdUnlock(const Command&) {
    if (requestUnlock()) {
        Serial.print(F("OK UNLOCK "));
        Serial.println(benchStateName());
    } else {
        Serial.print(F("ERROR UNLOCK not ready:"));
        printUnlockProblems();
        Serial.println();
    }
}

// MOTOR          -> "OK MOTOR <percent>"  (lê o throttle, nos dois modos)
// MOTOR <0..100> -> só em modo SERVER: define o throttle em % (0 = parado). Acima de 0 só com
//                   o banco UNLOCKED, nunca acima de MOTOR_MAX_PERCENT. Em modo SERVER o MOTOR 0
//                   é sempre aceite (para). Em modo POT: "ERROR MOTOR mode POT".
static void cmdMotor(const Command& cmd) {
    if (cmd.count == 1) {
        if (motorMode() != MODE_SERVER) {            // em modo POT quem manda é o pot
            Serial.print(F("ERROR MOTOR mode "));
            Serial.println(motorModeName());
            return;
        }
        long p;
        if (!paramToLong(cmd, 0, p) || p < 0 || p > MOTOR_MAX_PERCENT) {
            replyInvalidValue(cmd, cmd.params[0]);
            return;
        }
        if (!motorSet(p)) {                          // aqui só falha se o banco não estiver desbloqueado
            Serial.print(F("ERROR MOTOR bench "));
            printBenchState();
            Serial.println();
            return;
        }
    }
    replyOk(cmd, motorPercent());
}

// MODE                 -> "OK MODE POT" / "OK MODE SERVER"  (quem controla o throttle)
// MODE <POT|SERVER>    -> muda-o, só com o banco LOCKED (o throttle nunca dá saltos)
static void cmdMode(const Command& cmd) {
    if (cmd.count == 1) {
        MotorMode m;
        if (strcmp(cmd.params[0], "POT") == 0)         m = MODE_POT;
        else if (strcmp(cmd.params[0], "SERVER") == 0) m = MODE_SERVER;
        else {
            replyInvalidValue(cmd, cmd.params[0]);
            return;
        }
        if (!motorSetMode(m)) {
            Serial.print(F("ERROR MODE bench "));
            printBenchState();
            Serial.println();
            return;
        }
    }
    Serial.print(F("OK MODE "));
    Serial.println(motorModeName());
}

static void cmdPing(const Command&) {
    Serial.println(F("OK PING"));
}

static void cmdHelp(const Command&);       // definida depois da tabela, porque a usa

// ---------------------------------------------------------------------------
// TABELA DE COMANDOS: para acrescentar um comando novo, escrever a sua função acima
// e acrescentar UMA linha aqui.
// ---------------------------------------------------------------------------
static const CommandEntry COMMANDS[] = {
//   nome       min max  função      uso
    { "POT",    0,  0,   cmdPot,     "POT" },
    { "TONE",   1,  2,   cmdTone,    "TONE <freq> [ms]" },
    { "BENCH",  0,  0,   cmdBench,   "BENCH" },
    { "UNLOCK", 0,  0,   cmdUnlock,  "UNLOCK" },
    { "MOTOR",  0,  1,   cmdMotor,   "MOTOR [0..100]" },
    { "MODE",   0,  1,   cmdMode,    "MODE [POT|SERVER]" },
    { "BAT",    0,  0,   cmdBat,     "BAT" },
    { "STOP",   0,  0,   cmdStop,    "STOP" },
    { "PING",   0,  0,   cmdPing,    "PING" },
    { "HELP",   0,  0,   cmdHelp,    "HELP" },
};
static const int NUM_COMMANDS = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

// HELP -> "OK POT TONE ... HELP" (lista construída a partir da tabela: nunca fica desatualizada)
static void cmdHelp(const Command&) {
    Serial.print(F("OK"));
    for (int i = 0; i < NUM_COMMANDS; i++) {
        Serial.print(' ');
        Serial.print(COMMANDS[i].name);
    }
    Serial.println();
}

// ---------------------------------------------------------------------------
// Eventos: linhas "EVT ..." enviadas sem pedido
// ---------------------------------------------------------------------------

// EVT POT <valor>: quando o pot mexeu pelo menos POT_EVENT_MIN_CHANGE desde o último
// evento, no máximo uma vez a cada POT_EVENT_MS. Se o rodar depressa e parar, a verificação
// seguinte (100 ms depois) ainda envia a posição final, porque difere 5 ou mais.
static void sendPotEvent() {
    static int lastSent = -1000;           // obriga a um evento logo a seguir ao arranque
    static unsigned long lastCheck = 0;
    if (millis() - lastCheck < POT_EVENT_MS) return;
    lastCheck = millis();

    int pot = potValue();
    if (abs(pot - lastSent) < POT_EVENT_MIN_CHANGE) return;   // ruído, ou não mexeu
    lastSent = pot;
    Serial.print(F("EVT POT "));
    Serial.println(pot);
}

void sendEvents() {
    sendPotEvent();
}

// ---------------------------------------------------------------------------

void processInput() {
    Command cmd;
    if (!readInput(cmd)) return;          // ainda não há linha completa (ou já foi enviado um ERROR)

    // chegou uma linha: o servidor está vivo (mesmo que o comando seja desconhecido)
    serverSeenConnection();

    // 1) procura o nome na tabela
    for (int i = 0; i < NUM_COMMANDS; i++) {
        const CommandEntry& e = COMMANDS[i];
        if (strcmp(cmd.name, e.name) != 0) continue;

        // 2) o número de valores está dentro do que o comando aceita?
        if (cmd.count < e.minArgs || cmd.count > e.maxArgs) {
            Serial.print(F("ERROR "));
            Serial.print(e.name);
            Serial.print(F(" expects "));
            Serial.print(e.minArgs);
            if (e.maxArgs != e.minArgs) {
                Serial.print(F(" to "));
                Serial.print(e.maxArgs);
            }
            Serial.print(F(" values: "));
            Serial.println(e.usage);
            return;
        }

        // 3) executa-o
        e.handler(cmd);
        return;
    }

    // Tudo o que for inesperado recebe um ERROR. Nunca ignorar: quem enviou tem de saber que algo estava errado.
    Serial.print(F("ERROR unknown command: "));
    Serial.println(cmd.name);
}
