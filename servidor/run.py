import time
from communication import Nano


nano = Nano("/dev/ttyUSB0")

try:
    print(nano.send("BENCH"))

    # Teste do heartbeat: precisa da bateria ligada e do pot no zero (senão o UNLOCK é recusado).
    # Sem heartbeat, 5 s calado davam "LOCKED CHECK SERVER_LOST". Com ele, continua UNLOCKING.
    # Abrir a porta faz reset ao Nano, que recomeça os 3 s do ESC a armar (BAT_ARM_MS):
    # repete o UNLOCK enquanto a resposta for ESC_ARMING (no máximo 5 s)
    deadline = time.monotonic() + 5
    reply = nano.send("UNLOCK")
    while "ESC_ARMING" in reply and time.monotonic() < deadline:
        time.sleep(0.5)
        reply = nano.send("UNLOCK")
    print(reply)
    print("5 s sem enviar nada (NÃO carregue no botão)...")
    time.sleep(5)
    print(nano.send("BENCH"))               # esperado: OK BENCH UNLOCKING

    print(nano.battery_status())            # esperado: OK BAT <estado> <valor>V

    print(nano.unlock_bench())              # esperado: OK UNLOCK

finally:
    nano.close()                            # STOP + fechar, aconteça o que acontecer (erro, Ctrl+C)