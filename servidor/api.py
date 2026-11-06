import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import serial
import serial.tools.list_ports

from communication import DEFAULT_PORT, Nano, NanoError

PORT = os.environ.get("NANO_PORT", DEFAULT_PORT)   # outra porta: NANO_PORT=/dev/ttyUSB1 python3 -m uvicorn ...
CLIENT_TIMEOUT_S = 2.0      # s sem a dashboard perguntar o /status, com o banco UNLOCKED: STOP (a dashboard fechou?)
HERE = os.path.dirname(os.path.abspath(__file__))

nano = None                 # o Nano, aberto UMA vez (abrir a porta faz reset ao Nano). None = sem ligação
connect_lock = threading.Lock()   # só uma tentativa de ligação de cada vez
last_status = time.monotonic()
running = True

thrust_points = []
thrust_recording = False
thrust_start = 0.0
thrust_lock = threading.Lock()

# Vigia do cliente: é o heartbeat de novo, um andar acima. O Pi continua a enviar PING ao Nano,
# por isso se o browser desaparecer com o motor a rodar, quem tem de mandar STOP é o servidor.
def client_watchdog():
    while running:
        time.sleep(0.2)
        if nano and nano.bench and nano.bench["state"] == "UNLOCKED" and time.monotonic() - last_status > CLIENT_TIMEOUT_S:
            print("AVISO: a dashboard deixou de responder: STOP")
            try:
                nano.stop()
            except (NanoError, TimeoutError) as e:
                print("AVISO: o STOP falhou:", e)

# Gravação do thrust (para o gráfico): enquanto thrust_recording estiver ligado, pede a força e o throttle
# ao Nano em contínuo e junta um ponto à thrust_points. O ritmo é o da HX711 (~10/s): cada THRUST espera
# pela leitura seguinte, por isso não precisa de sleep. Se algo falhar, desliga a gravação (e avisa).
def thrust_loop():
    global thrust_recording
    while running:
        n = nano                            # cópia: o CONNECT pode trocar (ou largar) o nano a meio da volta
        if not thrust_recording or n is None:
            time.sleep(0.05)                # nada a fazer: sem isto o ciclo punha o processador a 100 %
            continue

        try:
            with n.quiet():                 # pedidos de fundo: não enchem a página Serial
                thrust = n.thrust_readings()
                throttle = n.motor()
        except (NanoError, TimeoutError) as e:
            print("AVISO: a leitura do thrust falhou, a gravação parou:", e)
            thrust_recording = False
            continue
        except (serial.SerialException, OSError):
            print("AVISO: a porta do Nano morreu (o USB caiu?), a gravação parou")
            thrust_recording = False
            continue

        if thrust is None:                  # não há célula de carga
            print("AVISO: sem célula de carga, a gravação parou")
            thrust_recording = False
            continue

        with thrust_lock:                   # a rota GET /thrust lê a mesma lista noutra thread
            thrust_points.append({
                "n": len(thrust_points) + 1,                        # 1, 2, 3... (recomeça em cada start)
                "t": round(time.monotonic() - thrust_start, 3),     # s desde o start, medidos aqui
                "gf": thrust["gf"],
                "throttle": throttle,                               # % do MOTOR nesse momento
            })


# Larga o Nano atual (se houver), fechando-o sem rebentar mesmo que a porta já tenha morrido
def drop_nano():
    global nano
    old, nano = nano, None
    if old is not None:
        old.close()


# A porta a que o Nano está ligado (o caminho real, p. ex. /dev/ttyUSB0), ou None
def connected_device():
    return os.path.realpath(nano.port.port) if nano is not None else None


# Tenta ligar ao Nano na porta 'port' (por omissão a PORT). Devolve None se correu bem, ou a mensagem de erro.
# Se já estiver ligado a OUTRA porta, larga essa primeiro.
def connect(port=None):
    global nano
    port = port or PORT
    with connect_lock:
        if nano is not None and connected_device() == os.path.realpath(port):
            return None                     # já está ligado a esta porta
        try:
            new = Nano(port)                # experimenta a porta nova PRIMEIRO...
        except (serial.SerialException, TimeoutError) as e:
            print("AVISO: sem ligação ao Nano:", e)
            return str(e)                   # ...se falhar, a ligação que havia (se havia) continua
        drop_nano()                         # só agora larga a antiga
        nano = new
        return None


# Corre no arranque (antes do yield) e no fim (depois do yield) do servidor.
# Se o Nano não estiver ligado, a dashboard arranca na mesma: depois liga-se com o botão CONNECT.
@asynccontextmanager
async def lifespan(app):
    global running
    connect()
    threading.Thread(target=client_watchdog, daemon=True).start()
    threading.Thread(target=thrust_loop, daemon=True).start()
    yield
    running = False
    if nano is not None:
        nano.close()                        # STOP + fechar


app = FastAPI(lifespan=lifespan)

# Entrega os ficheiros da pasta servidor/assets (imagens...) em /assets/<nome>
app.mount("/assets", StaticFiles(directory=os.path.join(HERE, "assets")), name="assets")
# Entrega o CSS e o JavaScript da dashboard (pasta servidor/static) em /static/<nome>
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# Chama um método do Nano (pelo nome) e transforma os erros em erros HTTP, que a dashboard mostra.
# Recebe o NOME, e não nano.metodo: com o nano a None, nano.metodo rebentava antes de chegar aqui.
def call(name, *args):
    if nano is None:
        raise HTTPException(status_code=503, detail="Nano not connected: plug it in and press CONNECT")
    try:
        return getattr(nano, name)(*args)
    except NanoError as e:
        raise HTTPException(status_code=400, detail=str(e))       # o Nano recusou
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))       # o Nano não respondeu
    except (serial.SerialException, OSError):
        drop_nano()                                               # a porta morreu (o USB caiu?): larga o Nano
        raise HTTPException(status_code=503, detail="Nano disconnected (USB?): choose the port and press CONNECT")


# ----- A página -----

# As páginas: cada uma é um template (pasta templates/) que estende o base.html
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


@app.get("/")
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"page": "dashboard"})


@app.get("/serial")
def serial_page(request: Request):
    return templates.TemplateResponse(request, "serial.html", {"page": "serial"})


# ----- Ler -----

# A dashboard pergunta isto a cada 500 ms (e é também o sinal de vida dela)
@app.get("/status")
def status():
    global last_status
    last_status = time.monotonic()
    if nano is None:
        call("bench_state")                   # sem Nano: o call() responde 503
    with nano.quiet():                        # pedidos de fundo: o Serial da página esconde-os por omissão
        return {
            "bench": call("bench_state"),
            "esc": call("esc_state"),
            "mode": call("mode"),
            "motor": call("motor"),
            "battery": call("battery_status"),
            "pot": call("pot_reading"),
            "air": call("air_readings"),
            "thrust_offset": call("thrust_offset"),
        }


# O registo da porta série: as linhas depois da número 'after'. all=true inclui o tráfego de fundo (PING, /status)
@app.get("/serial-log")
def serial_log(after: int = 0, all: bool = False):
    global last_status
    last_status = time.monotonic()            # a página Serial também é sinal de vida (a vigia do cliente)
    if nano is None:
        return {"lines": [], "last": after}
    reset = after > nano.get_log(0)[1]        # o Nano foi religado (CONNECT): o registo recomeçou do 1
    lines, last = nano.get_log(0 if reset else after, include_quiet=all)
    return {"lines": lines, "last": last, "reset": reset}


# ----- Ligar -----

# As portas USB disponíveis, e o que está ligado a cada uma (para o menu da dashboard)
@app.get("/ports")
def ports():
    by_id = {}                                          # /dev/ttyUSB0 -> /dev/serial/by-id/... (o nome fixo)
    folder = "/dev/serial/by-id"
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            by_id[os.path.realpath(path)] = path
    current = connected_device()
    found = []
    for p in serial.tools.list_ports.comports():
        if p.vid is None:
            continue                                    # não é um aparelho USB (p. ex. a porta série interna do Pi)
        found.append({
            "device": p.device,                         # /dev/ttyUSB0
            "port": by_id.get(p.device, p.device),      # o que se usa para ligar: o nome fixo, se existir
            "description": p.description,               # USB2.0-Serial
            "manufacturer": p.manufacturer,
            "usb_id": f"{p.vid:04X}:{p.pid:04X}",       # 1A86:7523 = CH340 (o chip USB do Nano)
            "connected": p.device == current,
        })
    return {"ports": found, "connected": current}


class ConnectRequest(BaseModel):
    port: str | None = None                             # sem porta: a PORT por omissão


@app.post("/connect")
def connect_nano(req: ConnectRequest):
    error = connect(req.port)
    if error:
        raise HTTPException(status_code=503, detail=f"Could not connect to the Nano: {error}")
    return {"connected": connected_device()}


# ----- Agir -----

class ModeRequest(BaseModel):
    mode: str


class MotorRequest(BaseModel):
    percent: int


@app.post("/unlock")
def unlock():
    return {"state": call("bench_unlock")}          # depois é preciso segurar o botão 2 s


@app.post("/stop")
def stop():
    call("stop")
    return {"ok": True}


@app.post("/mode")
def set_mode(req: ModeRequest):
    try:
        return {"mode": call("set_mode", req.mode)}
    except ValueError as e:                            # nem POT nem SERVER
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/motor")
def set_motor(req: MotorRequest):
    return {"motor": call("set_motor", req.percent)}

@app.post("/tare")
def tare():
    return {"offset": call("tare_thrust_sensor")}


# ----- Thrust (o gráfico e os ensaios) -----

# Liga a gravação: limpa os pontos e o tempo volta ao zero. A thread thrust_loop começa a juntar pontos.
@app.post("/thrust/start")
def thrust_start_recording():
    global thrust_recording, thrust_start
    if nano is None:
        call("thrust_readings")               # sem Nano: o call() responde 503
    with thrust_lock:
        thrust_points.clear()                 # ANTES de ligar: senão a thread ainda juntava um ponto à lista antiga
    thrust_start = time.monotonic()
    thrust_recording = True
    return {"recording": True}


# Desliga a gravação. Os pontos ficam na lista (o GET /thrust continua a dá-los) até ao próximo start.
@app.post("/thrust/stop")
def thrust_stop_recording():
    global thrust_recording
    thrust_recording = False
    return {"recording": False}


# A força NESTE momento (para os ensaios): {"gf": 205.0, ...}, ou null se não há célula.
# A gravar: o último ponto da thread (lido há menos de ~100 ms), sem pedir nada ao Nano: dois a pedir THRUST
# dividiam as 10 leituras por segundo entre si. Sem gravar: pergunta ao Nano agora.
@app.get("/thrust/now")
def thrust_now():
    with thrust_lock:
        if thrust_recording and thrust_points:
            return thrust_points[-1]
    return call("thrust_readings")


# Os pontos gravados depois do número 'after' (o gráfico pede só os novos), e se ainda está a gravar
# (false = parado com o STOP, ou parou sozinho: célula a falhar, porta a morrer...).
@app.get("/thrust")
def thrust(after: int = 0):
    with thrust_lock:
        points = [p for p in thrust_points if p["n"] > after]
    return {"points": points, "recording": thrust_recording}
