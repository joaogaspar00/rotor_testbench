#!/usr/bin/env python3
# Exemplo de um script que usa a classe Nano (servidor/communication.py).
# Lê o estado, desbloqueia o banco (com o botão) e roda o motor 2 s a 10 %.
#
#   !!! O MOTOR VAI RODAR: SEM HÉLICE e com o motor bem preso !!!
#   Se algo correr mal: um toque no botão bloqueia sempre.
#
# Correr (com o Monitor e o miniterm FECHADOS):
#   python3 tests/test_scripts.py

import os
import sys
import time

# para encontrar o servidor/communication.py, esteja onde estiver quem corre o script
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "servidor"))
from communication import Nano, NanoError

PERCENT = 10          # % do throttle
DURATION_S = 2        # s a rodar

if input("Hélice retirada e motor bem preso? Escreve SIM para continuar: ").strip() != "SIM":
    sys.exit("Cancelado.")

nano = Nano()                             # abre a porta (DEFAULT_PORT) e espera pelo READY
try:
    print("Bateria:", nano.battery_status())
    print("Banco:  ", nano.bench_state())
    print("Modo:   ", nano.mode())        # já arranca em SERVER: o throttle vem do set_motor
    print("Pot:    ", nano.pot_reading())


    print("Desbloqueio:", nano.bench_unlock())
    print(">>> Segure o botão 2 s (LED vermelho a piscar, depois apito longo)...")
    if not nano.wait_unlocked():
        print("Não desbloqueou:", nano.bench_state())
    else:
        print(f"Motor a {PERCENT} % durante {DURATION_S} s...")
        nano.set_motor(PERCENT)
        time.sleep(DURATION_S)            # o heartbeat mantém o banco desbloqueado durante a espera
        nano.set_motor(0)
        print("Motor parado.")

except NanoError as e:
    print("O Nano recusou:", e)

finally:
    nano.close()                          # STOP + fechar, aconteça o que acontecer
