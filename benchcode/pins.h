#pragma once
#include <Arduino.h>

// Hardware do banco: pinos e constantes de calibração
// Todos os módulos incluem este ficheiro em vez de definirem os seus próprios pinos.

// velocidade da porta série (bits por segundo)
const unsigned long SERIAL_SPEED = 115200;
const unsigned long SERIAL_WAIT_CONNECTION = 1000;   // tempo de espera para a porta série se conectar (USB)

// Sinal do ESC (D9)
const int PIN_ESC = 9;
const int ESC_PULSE_MIN = 1000;   // us - throttle 0 %   = motor parado
const int ESC_PULSE_MAX = 2000;   // us - throttle 100 % = aceleração máxima
const int MOTOR_MAX_PERCENT = 50; // LIMITE DE SEGURANÇA: o MOTOR nunca passa disto (50 % = 1500 us). Subir só com cuidado.
const int MOTOR_START_PERCENT = 8; // modo POT: primeiro % acima da zona morta (1080 us; abaixo disso o motor só treme)

// LEDs (cada um com uma resistência de 330 Ohm para o GND)
// Pinos de estado da bancada de testes
const int PIN_RED = 2;      
const int PIN_GREEN = 3;   
// pertence à bateria: apagado = sem bateria | pisca rápido = ESC a armar | aceso = pronta | pisca lento = fraca
const int PIN_YELLOW = 4;

// BUZZER (D7)
const int PIN_BUZZER = 7;
const long TONE_MIN_HZ = 31;      // frequência minima do buzzer
const long TONE_MAX_HZ = 10000;   // frequência maxima do buzzer
const long TONE_MAX_MS = 5000;    // limite de tempo do buzzer nunca mais de 5 s de seguida

// BOTÃO (D8)
// Bloqueia / desbloqueia o banco: segurar UNLOCK_HOLD_MS para desbloquear, um toque para bloquear.
const int PIN_BUTTON = 8;
const unsigned long DEBOUNCE_MS = 20;        // a leitura do botão tem de estar estável este tempo para contar
const unsigned long UNLOCK_HOLD_MS = 2000;   // tempo a segurar para desbloquear o banco

// POTENCIÓMETRO (A6)
const int PIN_POT = A6;
const int POT_ZERO = 15;                    // abaixo disto o pot conta como "a zero"
const int POT_LEFT_ZERO = 30;               // só sai do zero acima disto (histerese contra o ruído)
const unsigned long POT_LEAVE_MS = 200;     // tempo para considerar que o potênciometro saiu do zero
const int POT_BURST = 8;                    // leituras seguidas tiradas à média por amostra (~1 ms: períodos inteiros do buzzer)
const unsigned long POT_SAMPLE_MS = 5;      // uma rajada a cada este número de ms
const int POT_FILTER = 4;                   // média exponencial: anda 1/4 do caminho por amostra (~20 ms) - (os apitos do buzzer / ESC causam picos curtos na leitura)
const int POT_EVENT_MIN_CHANGE = 5;         // EVT POT só quando o pot mexeu pelo menos isto (ignora o ruído)
const unsigned long POT_EVENT_MS = 100;     // Frequência máxima de envio de EVT POT - se o potenciometro alterar muito rápido, envia no máximo uma vez a cada este tempo

// CONEXÃO DA BATERIA (D6)
const int PIN_BAT_DETECT = 6;    // deteção de bateria ligada: fio vermelho do BEC do ESC (5V) -> 10 kOhm -> D6 -> 100 kOhm -> GND (NUNCA ao pino 5V)
const unsigned long BAT_ARM_MS = 3000;        // depois de ligar a bateria, o ESC precisa deste tempo para armar
const unsigned long BAT_DISCONNECT_MS = 50;   // BEC desligado este tempo = bateria desligada
const unsigned long BLINK_ARMING_MS = 100;    // enquanto o ESC arma: os 3 LEDs à roda (vermelho, verde, amarelo), este tempo cada um

// TENSÃO DA BATERIA (A0) 
const int PIN_BATTERY = A0;
const float BAT_R_TOP = 10000.0;     // Ohm entre o + da bateria e o A0
const float BAT_R_BOTTOM = 4700.0;   // Ohm entre o A0 e o GND
const float VREF = 4.64;             // tensão real no pino 5V do Nano (deverá ser calibrada com multimetro para melhor valor de referênica)
const int BAT_SAMPLES = 16;          // leituras tiradas à média por cada medição de tensão (filtra o ruído)
const unsigned long BAT_CHECK_MS = 100;       // de quanto em quanto tempo se mede a tensão
const float BAT_NONE_V = 6.0;        // abaixo disto: não há bateria no cabo de balanceamento
const float BAT_WEAK_V = 10.8;       // 3,6 V/célula: fraca, acabar o ensaio e carregar
const float BAT_WEAK_HYST_V = 0.2;   // só deixa de estar "fraca" acima de BAT_WEAK_V + isto
const float BAT_LOW_V = 10.2;        // 3,4 V/célula: baixa, o motor não pode rodar
const unsigned long BAT_LOW_CUT_MS = 2000;   // abaixo de BAT_LOW_V este tempo com o banco UNLOCKED: corta e bloqueia
                                             // (ignora as quedas curtas quando o motor acelera)
const unsigned long BLINK_WEAK_MS = 500;     // amarelo a piscar lento quando a bateria está fraca ou baixa

// procedimento de desbloqueio
const unsigned long UNLOCK_WAIT_MS = 30000;   // depois do UNLOCK, espera este tempo pelo botão
const unsigned long BLINK_MS = 500;           // LED vermelho a piscar durante o UNLOCKING: 500 ms aceso, 500 ms apagado
const unsigned long BLINK_HOLD_MS = 200;      // pisca mais rápido enquanto se segura o botão para desbloquear

// Servidor 
const unsigned long SERVER_TIMEOUT_MS = 1000; // Tempo máximo que a bancada pode estar sem ouvir do servidor. Se passar disto, bloqueia e pára o motor (motor a 0 %).

// Sensor de propriedades do ar (BMP280)
const uint8_t AIR_SENSOR_ADDRESS = 0x76;    // SDO ligado ao GND (0x77 se estiver ligado ao VCC)
const float R_DRY_AIR = 287.05;         // constante do ar seco, J/(kg K)

// Sensor de força de propulsão (célula de carga + HX711)
const int PIN_THRUST_DT = A1;
const int PIN_THRUST_SCK = A2;
const float GRAMS_PER_COUNT = 0.004862;     
const float G_TO_N = 0.00980665;            // 1 g de massa pesa 0,00980665 N
const unsigned long THRUST_SENSOR_TIMEOUT_MS = 150; // Tempo máximo que a célula de carga pode estar sem responder. Se passar disto, marca como perdida.

// O Nano tem UM só conversor analógico, partilhado por todos os pinos analógicos. Logo a seguir a mudar de pino, a primeira leitura ainda se "lembra" do pino anterior. Chamar isto UMA vez antes das leituras de um pino; depois usar analogRead() normalmente.
inline void settleAnalog(int pin) {
    analogRead(pin);            // deitada fora: o conversor muda para este pino e estabiliza
}

