#include <avr/wdt.h>

#include "pins.h"
#include "bench.h"
#include "motor.h"
#include "commands.h"
#include "sensors.h"


void setup() {
    MCUSR = 0;          // limpa o registo que diz "o último reset foi do watchdog"
    wdt_disable();      // desliga o watchdog, caso venha ligado de um reset anterior
   
    // Procedimento Inicial de Segurança, defini o pino do ESC (PIN_ESC) e coloca o motor em 0% de velocidade, antes de qualquer delay. Por segurança, é o primeiro passo
    initialMotorSetup();      // FIRST: ESC signal at 0 % (motor stopped), before any delay

    Serial.begin(SERIAL_SPEED);
    delay(SERIAL_WAIT_CONNECTION);   // espera a abertura da porta série

    Serial.println(F("=================================================="));
    Serial.println(F("               Starting BENCHCODE                 "));
    Serial.println(F("==================================================\n"));

    // defini os modos e os estados iniciais dos pinos do Arduino 
    // dos diferentes componentes do bench (LEDs, buzzer, botão, BEC)
    pinMode(PIN_YELLOW, OUTPUT); digitalWrite(PIN_YELLOW, LOW);
    pinMode(PIN_RED, OUTPUT); digitalWrite(PIN_RED, LOW);
    pinMode(PIN_GREEN, OUTPUT); digitalWrite(PIN_GREEN, LOW);
    pinMode(PIN_BUZZER, OUTPUT); digitalWrite(PIN_BUZZER, LOW);
    pinMode(PIN_BUTTON, INPUT_PULLUP);
    pinMode(PIN_BAT_DETECT, INPUT);           // external 100 kOhm pull-down

    Wire.setWireTimeout(25000, true);   // I2C: desiste ao fim de 25 ms em vez de encravar (fio mal ligado...)
    initialSensorsSetup();

    // MANTER COMO O ULTIMO PASSO PARA O RASPBERRY PI SABER QUE O ARDUINO ESTÁ PRONTO PARA RECEBER COMANDOS
    Serial.println(F("READY"));

    // Liga o watchdog só agora, depois do delay do arranque.
    // Modo INTERRUPÇÃO (não faz reset: o bootloader antigo entrava em ciclo de resets).
    // Se o loop encravar 250 ms sem wdt_reset(), corre a ISR(WDT_vect) no fim deste ficheiro.
    cli();                                  // desliga as interrupções enquanto se configura
    wdt_reset();
    WDTCSR = (1 << WDCE) | (1 << WDE);      // abre a "janela" (4 ciclos) para mudar a configuração
    WDTCSR = (1 << WDIE) | (1 << WDP2);     // só interrupção (WDIE, sem WDE = sem reset), ~250 ms (WDP2)
    sei();                                  // volta a ligar as interrupções

}

void loop() {

    // Watchdog: "estou vivo". Se o loop encravar 250 ms sem passar aqui, corre a ISR(WDT_vect): motor a 0
    wdt_reset();

    //Segurança do banco. Mede a bateria e o potenciómetro, lê o botão, decide se o banco está LOCKED, UNLOCKING ou UNLOCKED, e acende os LEDs de acordo. Se algo correr mal (bateria desligada, botão carregado), bloqueia e põe o motor a 0.
    updateBench();     

    // Controla o sinal do ESC. Se o banco não estiver desbloqueado, garante o motor a 0 %. Se estiver desbloqueado e em modo POT, o throttle segue o potenciómetro. Em modo SERVER não faz nada, porque o throttle só muda com o comando MOTOR.
    updateMotor();     

    // Recebe e processa ordens/comandos. Lê o que chegou pela porta série e, quando há um comando válido, executa o comando e responde com OK ou ERROR
    processInput();     

    // Avisa o PC sem ele perguntar so alterações. Por agora só envia EVT POT <valor> quando o potenciómetro mexe.
    sendEvents();       // and the events (EVT ...) the Nano sends on its own
}

// Corre sozinha se o loop() encravar (passaram ~250 ms sem wdt_reset()): é o chip que a chama.
// O chip continua encravado, mas o motor fica PARADO. Para recuperar: reabrir a porta série (faz reset).
// Num ISR: curto, sem delay(), sem Serial.
ISR(WDT_vect) {
    motorStop();                    // ESC a 0 %
    noTone(PIN_BUZZER);
    digitalWrite(PIN_GREEN, LOW);
    digitalWrite(PIN_RED, HIGH);    // vermelho fixo
}
