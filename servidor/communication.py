import queue
import threading
import time
import serial

BAUD = 115200            # igual ao SERIAL_SPEED do pins.h
STARTUP_TIMEOUT = 5.0    # s à espera do READY (abrir a porta faz reset ao Nano)
REPLY_TIMEOUT = 1.0      # s à espera da resposta a um comando (OK ... ou ERROR ...). Ignora os eventos (EVT ...).
HEARTBEAT_S = 0.25       # s sem enviar nada até o heartbeat enviar PING (o Nano bloqueia ao fim de 1 s: SERVER_TIMEOUT_MS)

# Exceção levantada quando o Nano responde com ERROR
class NanoError(Exception):
    pass


#Ligação ao Nano do banco: a ÚNICA parte do servidor que fala com a porta série
class Nano:

    # Utiliza a porta série para falar com o Nano. A porta é aberta no construtor e espera pelo READY enviado pelo NANO.
    # Depois arranca as duas threads: a de leitura (lê a porta o tempo todo) e a do heartbeat (PING).
    def __init__(self, port):

        self.port = serial.Serial(port, BAUD, timeout=0.05)
        self._wait_for_ready()

        # Só DEPOIS do READY: durante o arranque quem lê é o _wait_for_ready (duas a ler "roubavam" linhas uma à outra)
        self.replies = queue.Queue()            # respostas (OK/ERROR), da thread de leitura para o send
        self._send_lock = threading.Lock()      # só um send de cada vez (o servidor e o heartbeat)
        self._last_send = time.monotonic()      # quando foi enviado o último comando
        self._running = True                    # as threads correm enquanto isto for True

        # (o que as threads usam tem de existir ANTES de elas arrancarem)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat.start()

    # fecha a porta série, para não deixar o Nano preso à porta quando o servidor fecha
    def close(self):

        # 1) STOP enquanto as threads ainda correm (a leitura recebe o OK STOP): motor a 0 JÁ e banco "LOCKED STOP".
        #    Sem isto o Nano só bloqueava 1 s depois (heartbeat parado), com o motivo errado: SERVER_LOST.
        #    Se o Nano já não responder (cabo desligado...), o close tem de continuar na mesma.
        try:
            self.send("STOP")
        except TimeoutError:
            print("AVISO: o Nano não respondeu ao STOP (vai bloquear sozinho por SERVER_LOST)")

        # 2) Pára as threads: fechar a porta a meio de um readline() rebentava com elas.
        # O heartbeat pára PRIMEIRO: se estiver a meio de um send("PING"), precisa da leitura viva para receber o OK PING.
        self._running = False
        self._heartbeat.join()                  # espera que cada thread acabe a volta em que está
        self._reader.join()

        # 3) Fecha a porta
        self.port.close()
        print("Connection closed to Nano on port", self.port.name)

    # Espera até o Nano enviar READY, ou dá timeout.
    def _wait_for_ready(self):

        start = time.monotonic()
        while True:
            line = self._read_line()
            if line == "READY":
                print("Bench is ready and connected on port", self.port.name)
                return
            if time.monotonic() - start > STARTUP_TIMEOUT:
                self.port.close()
                raise TimeoutError("Timeout waiting for Nano READY")

    # Lê uma linha do Nano
    def _read_line(self):
        line = self.port.readline().decode("utf-8", errors="replace").strip()
        return line if line else None

    # Corre na thread de leitura, o tempo todo: é a ÚNICA que lê a porta depois do READY.
    # Separa o que chega: eventos (EVT ...) vão para o _handle_event, respostas (OK/ERROR) para a fila do send.
    def _read_loop(self):
        while self._running:
            line = self._read_line()            # espera no máximo 50 ms (o timeout da porta)

            if line is None:
                pass                            # nada chegou: volta a ver se ainda deve correr

            elif line.startswith("EVT "):
                self._handle_event(line)

            else:
                self.replies.put(line)

    # Envia um comando e devolve a resposta. Quem lê é a thread de leitura: aqui só se espera pela fila.
    # Pode ser chamado de várias threads (servidor e heartbeat): o cadeado garante um send de cada vez.
    # É responsável por saber se o nano respondeu em tempo
    def send(self, command):
        with self._send_lock:                   # fecha à entrada, abre à saída (mesmo com erro)

            # Deita fora respostas atrasadas de um comando anterior que deu timeout: senão este send recebia a resposta errada
            while not self.replies.empty():
                self.replies.get()

            self.port.write((command + "\n").encode("utf-8"))
            self._last_send = time.monotonic()  # qualquer comando conta como sinal de vida para o Nano
            try:
                return self.replies.get(timeout=REPLY_TIMEOUT)
            except queue.Empty:
                raise TimeoutError("No response from Nano for command: " + command)

    # Envia um comando e devolve a resposta se for OK, ou levanta NanoError se for ERROR.
    def _command(self, command):
        answer = self.send(command)
        if answer.startswith("OK"):           
            return answer
        
        raise NanoError(f"Nano returned ERROR for command: " + command + " with answer: " + answer)

    # Corre na thread do heartbeat: envia PING sempre que ninguém enviou nada há HEARTBEAT_S.
    # Enquanto o servidor envia comandos (p. ex. MOTOR a cada 50 ms) não sai nenhum PING: já contam como sinal de vida.
    def _heartbeat_loop(self):
        while self._running:
            time.sleep(0.05)
            if time.monotonic() - self._last_send >= HEARTBEAT_S:
                try:
                    self.send("PING")
                except TimeoutError:
                    # dentro do ciclo: um erro não pode parar o heartbeat para sempre
                    print("AVISO: o Nano não respondeu ao PING")

    # Trata UM evento, no momento em que chega. Por agora só o mostra.
    # (Corre na thread de leitura: deve ser rápido, para não atrasar a leitura das respostas.)
    def _handle_event(self, line):
        print(line)

    # ----- Comandos do banco: traduzem entre o Python e o Nano -----

    # Devolve o estado e a tensão da bateria
    def battery_status(self):
        answer = self._command("BAT")
        if answer.startswith("OK BAT"):
            parts = answer.split()
            bat_status = parts[2]  # devolve o estado da bateria 
            bat_volts = parts[3].removesuffix("V")   # devolve o valor da bateria em volts (sem o V no final)
            return {"state": bat_status, "voltage": float(bat_volts)}   

        raise NanoError(f"Unexpected response for BAT command: {answer}")

    def pot_reading(self):
        answer = self._command("POT")
        if answer.startswith("OK POT"):
            parts = answer.split()
            pot_value = int(parts[2])  
            return pot_value # devolve o valor do potenciômetro

        raise NanoError(f"Unexpected response for POT command: {answer}")

    # Para o motor e bloqueia o banco. Devolve True se correu bem, ou levanta NanoError se não.
    def stop(self):
        answer = self._command("STOP")
        if answer.startswith("OK STOP"):                 
            return True 
        raise NanoError(f"Unexpected response for STOP command: {answer}")

    # Devolve o estado do banco, o motivo do bloqueio e as verificações que falharam. 
    def bench_state(self):
        answer = self._command("BENCH")
        if answer.startswith("OK BENCH"):
            parts = answer.split()
            state = parts[2]                                    # LOCKED, UNLOCKING ou UNLOCKED
            reason = parts[3] if len(parts) > 3 else None       # só existe quando LOCKED
            problems = parts[4:]                                # só quando o motivo é CHECK ([] se não houver)
            return {"state": state, "reason": reason, "problems": problems}

        raise NanoError(f"Unexpected response for BENCH command: {answer}")

    # Pede o desbloqueio. Devolve o estado: "UNLOCKING" (agora é preciso segurar o botão 2 s) ou "UNLOCKED" (já estava).
    # Se faltar alguma coisa, o Nano responde "ERROR UNLOCK not ready: NO_BATTERY ..." e o _command lança NanoError.
    # ATENÇÃO: não desbloqueia sozinho. Para esperar pelo botão: wait_unlocked().
    def bench_unlock(self):
        answer = self._command("UNLOCK")
        if answer.startswith("OK UNLOCK"):
            parts = answer.split()
            return parts[2]                                     # UNLOCKING ou UNLOCKED

        raise NanoError(f"Unexpected response for UNLOCK command: {answer}")

    # Depois do bench_unlock(): espera que alguém segure o botão 2 s.
    # True = UNLOCKED. False = voltou a LOCKED (TIMEOUT, falhou uma verificação...) ou passou o timeout.
    def wait_unlocked(self, timeout=30):                        # 30 s, como o UNLOCK_WAIT_MS do Nano
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.bench_state()["state"]
            if state == "UNLOCKED":
                return True
            if state == "LOCKED":
                return False                                    # o Nano desistiu: não vale a pena esperar mais
            time.sleep(0.2)                                     # ainda UNLOCKING: pergunta outra vez
        return False

    # Throttle atual, em % (nos dois modos). OK MOTOR 30 -> 30
    def motor(self):
        return int(self._command("MOTOR").split()[2])

    # Só em modo SERVER e com o banco UNLOCKED: põe o throttle. Devolve o valor confirmado pelo Nano.
    # O limite (MOTOR_MAX_PERCENT) é do Nano: acima dele responde ERROR e o _command lança NanoError.
    def set_motor(self, percent):
        return int(self._command(f"MOTOR {percent}").split()[2])

    # Quem controla o throttle: "POT" ou "SERVER". OK MODE SERVER -> "SERVER"
    def mode(self):
        return self._command("MODE").split()[2]

    # Muda o modo ("POT" ou "SERVER"). Só com o banco LOCKED (senão o Nano responde ERROR).
    def set_mode(self, mode):
        if mode not in ("POT", "SERVER"):
            raise ValueError(f"modo inválido: {mode!r} (só POT ou SERVER)")
        return self._command(f"MODE {mode}").split()[2]

    # Toca no buzzer: freq em Hz (0 = parar), ms = duração (0 = até TONE 0 ou STOP).
    def tone(self, freq, ms=0):
        self._command(f"TONE {freq} {ms}")
