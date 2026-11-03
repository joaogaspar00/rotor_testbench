#!/usr/bin/env python3
# Teste dos eventos do ESC: mostra cada EVT ESC com o tempo, e confirma que a pergunta (ESC)
# e o evento dizem o mesmo. O motor NÃO roda.
#
# O que fazer durante o teste:
#   1. espere pelo ARMED do arranque
#   2. desligue a bateria do ESC        -> EVT ESC NONE
#   3. volte a ligá-la                   -> EVT ESC ARMING (3 LEDs à roda) e, ~3 s depois, EVT ESC ARMED
#   Ctrl+C para terminar.
#
# Correr (com o Monitor e o miniterm FECHADOS):
#   python3 tests/test_esc_events.py

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "servidor"))
from communication import Nano


class EscWatcher(Nano):
    """O Nano de sempre, mas cada EVT ESC é mostrado com o tempo e comparado com a pergunta ESC."""

    def _handle_event(self, line):
        super()._handle_event(line)                     # o tratamento normal: nano.esc e a bandeira esc_armed
        if not line.startswith("EVT ESC "):
            return
        now = time.monotonic()
        state = line.split()[2]
        extra = ""
        if state == "ARMING":
            self.arming_since = now
        elif state == "ARMED" and getattr(self, "arming_since", None):
            extra = f"   (armou em {now - self.arming_since:.1f} s)"
        print(f"  [{now - T0:6.1f} s] ESC = {state:6}  bandeira esc_armed = {self.esc_armed.is_set()}{extra}")


T0 = time.monotonic()
nano = EscWatcher("/dev/ttyUSB0")
try:
    print("À escuta. Desligue e volte a ligar a bateria do ESC. Ctrl+C para terminar.\n")
    while True:
        time.sleep(2)
        asked = nano.esc_state()                        # a pergunta tem de dizer o mesmo que o último evento
        if asked != nano.esc:
            print(f"  !! a pergunta diz {asked}, o último evento disse {nano.esc}")
except KeyboardInterrupt:
    print("\nFim.")
finally:
    nano.close()
