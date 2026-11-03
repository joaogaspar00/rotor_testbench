import time
from communication import Nano


nano = Nano("/dev/ttyUSB0")

try:
    
    print(nano.battery_status())



    print(nano.bench_unlock())

    print(nano.wait_unlocked())

    print(nano.bench_state())          

finally:
    nano.close()                            # STOP + fechar, aconteça o que acontecer (erro, Ctrl+C)