#pragma once

#include <Wire.h>
#include <Adafruit_BMP280.h>

struct AirReading { float temperature; float pressure; float density; };  
struct ThrustReading { float gf; float newtons; };  

void initialSensorsSetup();

void initialAirSensorSetup();
void initialThrustSensorSetup();

bool thrustSensorOk();     // a célula está a responder? false se a tara falhou no arranque, ou se a célula deixou de responder (até ao reset)

bool readAir(AirReading& air);
bool readThrust(ThrustReading& thrust);
