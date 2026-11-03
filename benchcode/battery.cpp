#include "battery.h"
#include "pins.h"

// Variáveis estáticas para manter o estado da conexão bateria 
static bool connected = false; // Estado
static unsigned long connectedAt = 0; // Hora a que a bateria foi ligada 

// Variáveis estáticas para manter o estado da tensão da bateria
static bool weak = false;

static float lastVolts = 0;   // última tensão medida (a cada BAT_CHECK_MS)

// Diz que a bateria está fraca
static bool below = false;    
// Diz desde quando a bateria está fraca
static unsigned long belowSince = 0;

static bool lowCut = false;   // memorizado até ao reset, viu-se uma bateria realmente baixa

// Mede a tensão a cada BAT_CHECK_MS (o batteryVolts() demora ~2 ms: lento demais para todas as voltas do loop) e mantém o "fraca" com histerese, para o LED não piscar à volta de BAT_WEAK_V.
static void updateVoltage() {

    static unsigned long lastCheck = 0;
    static bool first = true;

    // Se ainda não passou BAT_CHECK_MS desde a última medição, não faz nada.
    if (!first && millis() - lastCheck < BAT_CHECK_MS) return;

    first = false;

    // Guarda o tempo da última medição, para a próxima volta do loop.
    lastCheck = millis();

    // MEDE a tensão da bateria
    lastVolts = batteryVolts();

    // Verifica se a tensão está fraca ou não, só sai do estado "fraca" acima de BAT_WEAK_V + BAT_WEAK_HYST_V.
    if (lastVolts < BAT_WEAK_V) weak = true;
    else if (lastVolts > BAT_WEAK_V + BAT_WEAK_HYST_V) weak = false;

    // Tensão baixa durante demasiado tempo (verificado aqui, a cada BAT_CHECK_MS)
    if (lastVolts < BAT_LOW_V) {
        if (!below) {
            below = true;
            belowSince = millis();
        }
    } else {
        below = false;
    }

    if (batteryLowTooLong() && connected && lastVolts >= BAT_NONE_V) {
        lowCut = true;                    // bateria mesmo vazia: memorizado até ao reset
    }

}

// LED amarelo: apagado = sem bateria | aceso = pronta | pisca lento = fraca ou baixa (ESC a armar: o bench.cpp roda os 3 LEDs)
static void showBattery() {

    bool on;

    // A bateria não está conectada
    if (!connected)           on = false;
    // A bateria está conectada, mas o ESC ainda não teve tempo de armar:
    // não mexe no amarelo, porque o showBenchState() (bench.cpp) roda os 3 LEDs
    else if (!batteryArmed()) return;
    //A bateria está conectada, o ESC armou, mas a tensão está fraca ou baixa
    else if (weak || lowCut)  on = (millis() / BLINK_WEAK_MS) % 2;
    // A bateria está conectada, o ESC armou, e a tensão está boa
    else                      on = true;

    // Mostra o estado da bateria no LED amarelo
    digitalWrite(PIN_YELLOW, on);
}


// Verifica a ligação da bateria (BEC do ESC no D6) e o tempo de armar (BAT_ARM_MS). O ESC demora algum tempo a armar depois de ligar a bateria, e o BEC pode desligar momentaneamente quando o motor acelera.
static void updateConnection() {

    static bool lastReading = false;
    static unsigned long changedAt = 0;

    bool now = digitalRead(PIN_BAT_DETECT) == HIGH;

    // Verifica se a leitura mudou desde a última vez que se chamou esta função. Se mudou, regista o tempo da mudança.
    if (now != lastReading) {
        lastReading = now;
        changedAt = millis(); // -> regista o tempo aqui
    }

    // Se a bateria for conectada (BEC do ESC dá 5V no D6), marca como conectada e regista a hora a que foi ligada.
    if (now && !connected) {

        connected = true;
        connectedAt = millis(); // -> regista a hora a que a bateria foi ligada

    } 
    // Se a bateria foi desligada há tempo suficiente (BAT_DISCONNECT_MS) para considerar que o BEC desligou. Se sim, marca como desconectado.
    else if (!now && connected && millis() - changedAt >= BAT_DISCONNECT_MS) {

        connected = false;                                   

    }
}

void updateBattery() {
    // 1. está ligada?   → atualiza connected / connectedAt
    updateConnection();
    // 2. quantos volts? → atualiza lastVolts / weak / below / lowCut
    updateVoltage();
    // 3. mostra no LED amarelo
    showBattery();
}

bool batteryWeak() {
    return weak;
}

bool batteryLowTooLong() {
    return below && millis() - belowSince >= BAT_LOW_CUT_MS;
}

bool batteryLowCut() {
    return lowCut;
}

float batteryLastVolts() {
    return lastVolts;
}

bool batteryConnected() {
    return connected;
}

bool batteryArmed() {
    return connected && millis() - connectedAt >= BAT_ARM_MS;
}

float batteryVolts() {
    
    long sum = 0;

    settleAnalog(PIN_BATTERY);                                                // estabiliza no A0 primeiro

    for (int i = 0; i < BAT_SAMPLES; i++) sum += analogRead(PIN_BATTERY);     // média: menos ruído
    float pinVolts = (sum / (float)BAT_SAMPLES) * VREF / 1023.0;              // volts no A0
    return pinVolts * (BAT_R_TOP + BAT_R_BOTTOM) / BAT_R_BOTTOM;              // desfaz o divisor
}
