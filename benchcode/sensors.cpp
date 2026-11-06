#include "sensors.h"
#include "pins.h"

static Adafruit_BMP280 airSensor;
static bool airSensorFound = false;            // o sensor foi encontrado no arranque?


static bool thrustSensorFound = false;            // o sensor foi encontrado no arranque?
static long offset = 0;              // a tara da célula de carga (HX711)


// Faz a leitura das propriedades do ar
bool readAir(AirReading& air) {  // true se leu; false se não há sensor 

    if (!airSensorFound) return false;

    air.temperature = airSensor.readTemperature();
    air.pressure = airSensor.readPressure();
    air.density = air.pressure / (R_DRY_AIR * (air.temperature + 273.15));   // kg/m3 (ar seco: sem humidade)
    
    return true;

}

// Lê os 24 bits da HX711, em bruto (só chamar com o DT em LOW: há uma leitura pronta).
// Não verifica nada: quem a chama (readThrust e a tara) é que decide se se pode ler.
static long readThrustSensorRaw() {
    long value = 0;
    for (int i = 0; i < 25; i++) {          // 24 bits + 1 pulso extra (canal A, ganho 128)
        noInterrupts();                     // o SCK não pode ficar em HIGH mais de 60 us
        digitalWrite(PIN_THRUST_SCK, HIGH);
        digitalWrite(PIN_THRUST_SCK, LOW);
        interrupts();
        if (i < 24) value = (value << 1) | digitalRead(PIN_THRUST_DT);
    }
    if (value & 0x800000) value |= 0xFF000000;    // negativo: estende o sinal para os 32 bits do long
    return value;
}

// Faz a leitura do valor de propulsão e converte-o em valores úteis: em gf e em newtons
bool readThrust(ThrustReading& thrust) {

    if (!thrustSensorFound) return false;                   // não há célula: não há leitura

    unsigned long start = millis();
    while (digitalRead(PIN_THRUST_DT) == HIGH) {
        if (millis() - start > THRUST_SENSOR_TIMEOUT_MS) {                  // 1 s sem leitura: a HX711 não responde
            thrustSensorFound = false;
            return false;                                     // sai da função: o arranque continua
        }
    }

    long value = readThrustSensorRaw();

    thrust.gf = (value - offset) * GRAMS_PER_COUNT;
    thrust.newtons = thrust.gf * G_TO_N;

    return true;
}

// A janela para o thrustSensorFound (static: só este ficheiro o vê), para o commands.cpp
bool thrustSensorOk(){
    return thrustSensorFound;
}

long thrustSensorOffset() {
    return offset;
}


// Inicializa o sensor de pressão/temperatura (BMP280)
void initialAirSensorSetup() {
    airSensorFound = airSensor.begin(AIR_SENSOR_ADDRESS);
}


// Faz a tara da célula de carga (HX711). Se não conseguir ler 10 vezes seguidas, marca a célula como perdida (thrustSensorFound = false).
void thrustSensorTare() {

    long sum = 0;
    for (int i = 0; i < 10; i++) {                          // tara: a média de 10 leituras (~1 s a 10/s)
        unsigned long start = millis();
        while (digitalRead(PIN_THRUST_DT) == HIGH) {
            if (millis() - start > THRUST_TARE_TIMEOUT_MS) {                  // 0.5 s sem leitura: a HX711 não responde
                thrustSensorFound = false;
                return;                                     // sai da função: não há celula de carga
            }
        }
        sum += readThrustSensorRaw();
    }
    offset = sum / 10;

    thrustSensorFound = true;                               // chegou aqui: a célula respondeu às 10

}

// Inicializa a célula de carga (HX711) e faz a tara (offset)
void initialThrustSensorSetup() {

    // Inicializa os pinos da célula de carga (HX711)
    pinMode(PIN_THRUST_DT, INPUT_PULLUP);
    pinMode(PIN_THRUST_SCK, OUTPUT);
    digitalWrite(PIN_THRUST_SCK, LOW);

    // Faz a tara da célula de carga (HX711)
    thrustSensorTare();

}

// Inicializa os sensores da bancada
void initialSensorsSetup() {
    initialAirSensorSetup();
    initialThrustSensorSetup();
}



