#pragma once
#include <Arduino.h>

// Bateria: ligação (BEC do ESC no D6) e tensão (cabo de balanceamento no A0).

// Em cada volta do loop: acompanha o pino do BEC (ligação e tempo de armar), mede a
// tensão a cada BAT_CHECK_MS e mostra o estado da bateria no LED amarelo:
//   apagado = sem bateria | pisca rápido = ESC a armar | aceso = pronta | pisca lento = fraca ou baixa
void updateBattery();

// Verdadeiro enquanto o BEC do ESC dá 5V no D6 (bateria ligada ao ESC).
bool batteryConnected();

// Verdadeiro quando a bateria está ligada há BAT_ARM_MS (o ESC teve tempo de armar).
bool batteryArmed();

// Verdadeiro quando a tensão está abaixo de BAT_WEAK_V (com histerese), medida a cada BAT_CHECK_MS.
bool batteryWeak();

// Tensão da bateria, média de BAT_SAMPLES leituras (demora ~2 ms): mede AGORA.
float batteryVolts();

// A última tensão medida pelo updateBattery() (a cada BAT_CHECK_MS): instantâneo, para
// verificações que correm em cada volta do loop.
float batteryLastVolts();

// Verdadeiro quando a tensão está abaixo de BAT_LOW_V há BAT_LOW_CUT_MS seguidos
// (bateria mesmo baixa, ou o cabo de balanceamento saiu).
bool batteryLowTooLong();

// Verdadeiro (até ao reset) depois de se ver uma bateria REALMENTE baixa: entre BAT_NONE_V e
// BAT_LOW_V durante BAT_LOW_CUT_MS com a bateria ligada. A bateria tem de ser carregada: não
// volta a desbloquear. (Abaixo de BAT_NONE_V quer dizer que o cabo de balanceamento saiu, não
// que a bateria está vazia: isso não fica memorizado.)
bool batteryLowCut();
