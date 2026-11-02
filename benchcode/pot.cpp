#include "pot.h"
#include "pins.h"

// Variável que indica se o potênciometro está a zero (true) ou não (false). A variável é atualizada na função updatePot() e lida com histerese e tempo de espera para sair do zero.
static bool potenciometerAtZero = false;

static long filteredX16 = 0;   // filtered value x16 (keeps fractions without using float)

static bool potReadingStarted = false;


// Faz um conjunto de leituras do potênciometro (POT_BURST) e devolve a média. A primeira leitura é só para estabilizar o pino A6, depois tira POT_BURST leituras seguidas e devolve a média.
static int readBurst() {
    long sum = 0;
    settleAnalog(PIN_POT);                                  // define o pino A6 e estabiliza o conversor analógico
    for (int i = 0; i < POT_BURST; i++) sum += analogRead(PIN_POT);
    return sum / POT_BURST;
}

// verifica se o potênciometro está a zero ou não, com histerese e tempo de espera para sair do zero. Atualiza a variável potAtZero.
static void updateZero(int value) {

    static unsigned long aboveSince = 0; 
    static bool above = false;

    // Se passa o valor limite de sair do zero, começa a contar o tempo. Se passar o tempo limite, considera que saiu do zero. Se voltar a descer abaixo do limite de zero, considera que voltou a estar a zero.
    if (value > POT_LEFT_ZERO) {
        if (!above) {
            above = true;
            aboveSince = millis();
        }
        if (millis() - aboveSince >= POT_LEAVE_MS) potenciometerAtZero = false;
    } else {
        above = false;
        if (value < POT_ZERO) potenciometerAtZero = true;
    }

}

void updatePot() {

    static unsigned long lastSample = 0;

    // Se o potênciometro já começou a ser lido, mas ainda não passou o tempo de amostragem, não faz nada.
    if (potReadingStarted && millis() - lastSample < POT_SAMPLE_MS) return;


    // Se o potênciometro ainda não começou a ser lido, ou se já passou o tempo de amostragem, faz uma nova leitura.
    lastSample = millis();

    // Faz uma rajada de leituras do potênciometro e devolve a média.
    int burst = readBurst();

    // A primeira leitura do POTENCIÓMETRO é usada para inicializar o filtro exponencial. Depois disso, o filtro exponencial é atualizado com cada nova leitura.
    if (!potReadingStarted) {
        filteredX16 = (long)burst * 16;                 
        potReadingStarted = true;
    }

    // Exponential average: moves 1/POT_FILTER of the way to the new burst each sample.
    filteredX16 += ((long)burst * 16 - filteredX16) / POT_FILTER;

    updateZero(potValue());
}

// Devolve o valor do potênciometro filtrado, arredondado para o inteiro mais próximo.
int potValue() {
    return (filteredX16 + 8) / 16;
}

bool potAtZero() {
    return potenciometerAtZero;
}
