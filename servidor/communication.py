import collections
import contextlib
import queue
import threading
import time
import serial

BAUD = 115200            # igual ao SERIAL_SPEED do pins.h
# A porta do Nano pelo nome FIXO do aparelho USB (o chip CH340, fabricante 1a86). O /dev/ttyUSB0 pode passar a
# ttyUSB1 se o USB cair e voltar; este nome não muda. Ver os disponíveis: ls -l /dev/serial/by-id/
DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"
STARTUP_TIMEOUT = 5.0    # s à espera do READY (abrir a porta faz reset ao Nano)
REPLY_TIMEOUT = 1.0      # s à espera da resposta a um comando (OK ... ou ERROR ...). Ignora os eventos (EVT ...).
HEARTBEAT_S = 0.25       # s sem enviar nada até o heartbeat enviar PING (o Nano bloqueia ao fim de 1 s: SERVER_TIMEOUT_MS)
LOG_LINES = 500          # linhas guardadas no registo da porta série (as mais antigas vão saindo)
ESC_ARM_TIMEOUT = 5.0    # s que o bench_unlock espera pelo EVT ESC ARMED (o ESC arma 3 s depois de ligar a bateria: BAT_ARM_MS)

TARE_TIMEOUT = 3.0       # s à espera do OK TARE: a tara demora ~1 s (10 leituras da HX711 a 10/s)


# Exceção levantada quando o Nano responde com ERROR
class NanoError(Exception):
    pass


# Interpreta a resposta do BENCH ou o EVT BENCH, já partidos em palavras. Por exemplo:
#   ... BENCH UNLOCKED                             -> {"state": "UNLOCKED", "reason": None,    "problems": []}
#   ... BENCH LOCKED BUTTON                        -> {"state": "LOCKED",   "reason": "BUTTON", "problems": []}
#   ... BENCH LOCKED CHECK NO_BATTERY POT_NOT_ZERO -> {"state": "LOCKED",   "reason": "CHECK",
#                                                     "problems": ["NO_BATTERY", "POT_NOT_ZERO"]}
# As três chaves existem SEMPRE. (As duas primeiras palavras são "OK BENCH" ou "EVT BENCH".)
def _parse_bench(parts):
    state = parts[2]                                    # LOCKED, UNLOCKING ou UNLOCKED
    reason = parts[3] if len(parts) > 3 else None       # só existe quando LOCKED
    problems = parts[4:]                                # só quando o motivo é CHECK ([] se não houver)
    return {"state": state, "reason": reason, "problems": problems}


#Ligação ao Nano do banco: a ÚNICA parte do servidor que fala com a porta série
class Nano:

    # Utiliza a porta série para falar com o Nano. A porta é aberta no construtor e espera pelo READY enviado pelo NANO.
    # Depois arranca as duas threads: a de leitura (lê a porta o tempo todo) e a do heartbeat (PING).
    def __init__(self, port=DEFAULT_PORT):

        # Registo de tudo o que é enviado e recebido (a dashboard mostra-o). Antes de abrir: o READY também fica registado.
        self.log = collections.deque(maxlen=LOG_LINES)
        self._log_seq = 0                       # número da última linha registada
        self._log_lock = threading.Lock()
        self._local = threading.local()         # o "quiet" de cada thread (ver quiet())
        self._pending_quiet = False             # a resposta que se espera é de fundo?

        self.port = serial.Serial(port, BAUD, timeout=0.05, exclusive=True)   # exclusive: um 2.º programa falha logo ("porta ocupada")
        self._wait_for_ready()

        # Só DEPOIS do READY: durante o arranque quem lê é o _wait_for_ready (duas a ler "roubavam" linhas uma à outra)
        self.replies = queue.Queue()            # respostas (OK/ERROR), da thread de leitura para o send
        self.esc = None                         # último estado do ESC recebido por evento: NONE, ARMING ou ARMED
        self.esc_armed = threading.Event()      # bandeira: em cima quando o ESC está armado (EVT ESC ARMED)
        self.bench = None                       # último estado do banco recebido por evento (o mesmo dicionário do bench_state)
        self._bench_changed = threading.Condition()   # acorda quem espera (wait_unlocked) sempre que o self.bench muda
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
        except (serial.SerialException, OSError):
            print("AVISO: a porta já não existe (o USB caiu?): sem STOP")

        # 2) Pára as threads: fechar a porta a meio de um readline() rebentava com elas.
        # O heartbeat pára PRIMEIRO: se estiver a meio de um send("PING"), precisa da leitura viva para receber o OK PING.
        self._running = False
        self._heartbeat.join()                  # espera que cada thread acabe a volta em que está
        self._reader.join()

        # 3) Fecha a porta (se ainda existir)
        try:
            self.port.close()
        except (serial.SerialException, OSError):
            pass
        print("Connection closed to Nano on port", self.port.name)

    # Espera até o Nano enviar READY, ou dá timeout.
    def _wait_for_ready(self):

        start = time.monotonic()
        while True:
            line = self._read_line()
            if line is not None:
                self._log("RX", line)
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
            try:
                line = self._read_line()        # espera no máximo 50 ms (o timeout da porta)
            except (serial.SerialException, OSError):
                print("AVISO: a porta deixou de responder (o USB caiu?): a leitura parou")
                return

            if line is None:
                pass                            # nada chegou: volta a ver se ainda deve correr

            elif line.startswith("EVT "):
                self._log("RX", line)
                self._handle_event(line)

            else:
                self._log("RX", line, self._pending_quiet)   # a resposta é de fundo se o pedido foi
                self.replies.put(line)

    # Envia um comando e devolve a resposta. Quem lê é a thread de leitura: aqui só se espera pela fila.
    # Pode ser chamado de várias threads (servidor e heartbeat): o cadeado garante um send de cada vez.
    # É responsável por saber se o nano respondeu em tempo
    def send(self, command, timeout=REPLY_TIMEOUT):
        with self._send_lock:                   # fecha à entrada, abre à saída (mesmo com erro)

            # Deita fora respostas atrasadas de um comando anterior que deu timeout: senão este send recebia a resposta errada
            while not self.replies.empty():
                self.replies.get()

            quiet = getattr(self._local, "quiet", False)
            self._pending_quiet = quiet
            self.port.write((command + "\n").encode("utf-8"))
            self._log("TX", command, quiet)
            self._last_send = time.monotonic()  # qualquer comando conta como sinal de vida para o Nano
            try:
                return self.replies.get(timeout=timeout)  # espera pela resposta (OK/ERROR)
            except queue.Empty:
                raise TimeoutError("No response from Nano for command: " + command)

    # Envia um comando e devolve a resposta se for OK, ou levanta NanoError se for ERROR.
    def _command(self, command, timeout=REPLY_TIMEOUT):
        answer = self.send(command, timeout=timeout)
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
                    with self.quiet():
                        self.send("PING")
                except TimeoutError:
                    # dentro do ciclo: um erro não pode parar o heartbeat para sempre
                    print("AVISO: o Nano não respondeu ao PING")
                except (serial.SerialException, OSError):
                    return                              # a porta morreu (o USB caiu?): não vale a pena insistir

    # ----- Registo da porta série -----

    # Guarda uma linha no registo. direction = "TX" (enviada) ou "RX" (recebida). quiet = tráfego de fundo
    def _log(self, direction, text, quiet=False):
        with self._log_lock:
            self._log_seq += 1
            now = time.time()
            self.log.append({
                "seq": self._log_seq,
                "time": time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}",
                "dir": direction,
                "text": text,
                "quiet": quiet,
            })

    # As linhas do registo depois da número 'after'. Sem quiet=True, deixa de fora o tráfego de fundo.
    # Devolve (linhas, número da última linha registada).
    def get_log(self, after=0, include_quiet=False):
        with self._log_lock:
            lines = [l for l in self.log if l["seq"] > after and (include_quiet or not l["quiet"])]
            return lines, self._log_seq

    # Tudo o que se enviar dentro de um "with nano.quiet():" fica marcado como tráfego de fundo (o PING, o /status...)
    @contextlib.contextmanager
    def quiet(self):
        before = getattr(self._local, "quiet", False)
        self._local.quiet = True
        try:
            yield
        finally:
            self._local.quiet = before

    # Trata UM evento, no momento em que chega. Por agora só o mostra.
    # (Corre na thread de leitura: deve ser rápido, para não atrasar a leitura das respostas.)
    def _handle_event(self, line):
        print(line)

        # EVT ESC <NONE|ARMING|ARMED>: guarda o estado e levanta/baixa a bandeira (o bench_unlock espera por ela)
        if line.startswith("EVT ESC "):
            self.esc = line.split()[2]
            if self.esc == "ARMED":
                self.esc_armed.set()
            else:
                self.esc_armed.clear()

        # EVT BENCH <estado> [motivo] [problemas]: guarda o estado e acorda quem está à espera dele
        if line.startswith("EVT BENCH "):
            self._set_bench(_parse_bench(line.split()))

    # Muda o self.bench e acorda quem espera por uma mudança (wait_unlocked)
    def _set_bench(self, bench):
        with self._bench_changed:
            self.bench = bench
            self._bench_changed.notify_all()

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

    # Propriedades do ar (BMP280), medidas agora:
    #   OK AIR 23.55C 997.98hPa 1.1718kg/m3 -> {"temperature": 23.55, "pressure": 997.98, "density": 1.1718}
    # None se não há sensor (ERROR AIR no sensor): o banco pode trabalhar sem ele.
    def air_readings(self):
        try:
            answer = self._command("AIR")
        except NanoError as e:
            if "no sensor" in str(e):
                return None                                     # não há sensor: não é uma avaria
            raise                                               # outro erro: volta a levantá-lo, igual

        if answer.startswith("OK AIR"):
            parts = answer.split()
            air_temp = float(parts[2].removesuffix("C"))        # temperatura em °C
            air_pressure = float(parts[3].removesuffix("hPa"))  # pressão em hPa
            air_density = float(parts[4].removesuffix("kg/m3")) # densidade em kg/m3
            return {"temperature": air_temp, "pressure": air_pressure, "density": air_density}
        raise NanoError(f"Unexpected response for AIR command: {answer}")

    # Força da célula de carga (HX711): espera pela próxima leitura (até ~100 ms a 10/s), nunca repete uma.
    #   OK THRUST 799gf 7.84N -> {"gf": 799.0, "newtons": 7.84}
    # None se não há célula (ERROR THRUST no sensor); NanoError se a célula deixou de responder (ERROR THRUST timeout).
    def thrust_readings(self):
        try:
            answer = self._command("THRUST")
        except NanoError as e:
            if "no sensor" in str(e):
                return None                                     # não há célula: não é uma avaria
            raise                                               # timeout ou outro erro: volta a levantá-lo, igual

        if answer.startswith("OK THRUST"):
            parts = answer.split()
            thrust_gf = float(parts[2].removesuffix("gf"))      # força em gramas-força
            thrust_newtons = float(parts[3].removesuffix("N"))  # força em newtons
            return {"gf": thrust_gf, "newtons": thrust_newtons}
        raise NanoError(f"Unexpected response for THRUST command: {answer}")

    # Estado do ESC, perguntado agora: "NONE" (sem bateria), "ARMING" (a armar) ou "ARMED". OK ESC ARMED -> "ARMED"
    # (Também chega sozinho por evento, em self.esc, sempre que muda.)
    def esc_state(self):
        return self._command("ESC").split()[2]

    def pot_reading(self):
        answer = self._command("POT")
        if answer.startswith("OK POT"):
            parts = answer.split()
            pot_value = int(parts[2])  
            return pot_value # devolve o valor do potenciômetro

        raise NanoError(f"Unexpected response for POT command: {answer}")

    # Refaz o zero da célula: a força deste momento passa a ser 0. Devolve o offset novo: OK TARE -241554 -> -241554
    # Demora ~1 s (TARE_TIMEOUT dá margem). Só com o banco LOCKED; senão (ou sem célula) o Nano responde ERROR
    # e o _command lança NanoError.
    def tare_thrust_sensor(self):
        answer = self._command("TARE", timeout=TARE_TIMEOUT)
        if answer.startswith("OK TARE"):
            return int(answer.split()[2])                       # o offset novo, em contagens da HX711
        raise NanoError(f"Unexpected response for TARE command: {answer}")

    # O zero da célula (a última tara), em contagens da HX711: OK THRUST_OFFSET -241554 -> -241554
    # None se não há célula (ERROR THRUST_OFFSET no sensor). Só lê: não mexe no zero.
    def thrust_offset(self):
        try:
            answer = self._command("THRUST_OFFSET")
        except NanoError as e:
            if "no sensor" in str(e):
                return None                                     # não há célula: não é uma avaria
            raise                                               # outro erro: volta a levantá-lo, igual

        if answer.startswith("OK THRUST_OFFSET"):
            return int(answer.split()[2])
        raise NanoError(f"Unexpected response for THRUST_OFFSET command: {answer}")

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
            return _parse_bench(answer.split())                 # o mesmo que o EVT BENCH

        raise NanoError(f"Unexpected response for BENCH command: {answer}")

    # Pede o desbloqueio. Devolve o estado: "UNLOCKING" (agora é preciso segurar o botão 2 s) ou "UNLOCKED" (já estava).
    # Se faltar alguma coisa, o Nano responde "ERROR UNLOCK not ready: NO_BATTERY ..." e o _command lança NanoError.
    # ATENÇÃO: não desbloqueia sozinho. Para esperar pelo botão: wait_unlocked().
    def bench_unlock(self):
        # Espera (sem ciclos) que o ESC esteja armado: logo a seguir a abrir a porta, ou a ligar a bateria,
        # demora 3 s. Se já estiver armado, não espera nada. A bandeira é levantada pelo EVT ESC ARMED.
        if not self.esc_armed.wait(ESC_ARM_TIMEOUT):
            raise NanoError(f"ESC not armed after {ESC_ARM_TIMEOUT:g} s (ESC {self.esc}): is the battery connected?")

        answer = self._command("UNLOCK")
        if answer.startswith("OK UNLOCK"):
            state = answer.split()[2]                           # UNLOCKING ou UNLOCKED
            # O Nano confirmou: o estado já mudou. Guarda-o já, sem esperar pelo EVT BENCH (que chega logo a seguir),
            # para o wait_unlocked não ver ainda o LOCKED de antes.
            self._set_bench({"state": state, "reason": None, "problems": []})
            return state

        raise NanoError(f"Unexpected response for UNLOCK command: {answer}")

    # Depois do bench_unlock(): espera que alguém segure o botão 2 s.
    # True = UNLOCKED. False = voltou a LOCKED (TIMEOUT, falhou uma verificação...) ou passou o timeout.
    # Não pergunta nada ao Nano: dorme até o EVT BENCH dizer que saiu do UNLOCKING.
    def wait_unlocked(self, timeout=30):                        # 30 s, como o UNLOCK_WAIT_MS do Nano
        with self._bench_changed:
            self._bench_changed.wait_for(lambda: self.bench is not None and self.bench["state"] != "UNLOCKING", timeout)
            return self.bench is not None and self.bench["state"] == "UNLOCKED"

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
