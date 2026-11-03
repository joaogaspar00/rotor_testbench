import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from communication import Nano, NanoError

PORT = "/dev/ttyUSB0"
CLIENT_TIMEOUT_S = 2.0      # s sem a dashboard perguntar o /status, com o banco UNLOCKED: STOP (a dashboard fechou?)
HERE = os.path.dirname(os.path.abspath(__file__))

nano = None                 # o Nano, aberto UMA vez no arranque do servidor (abrir a porta faz reset ao Nano)
last_status = time.monotonic()
running = True


# Vigia do cliente: é o heartbeat de novo, um andar acima. O Pi continua a enviar PING ao Nano,
# por isso se o browser desaparecer com o motor a rodar, quem tem de mandar STOP é o servidor.
def client_watchdog():
    while running:
        time.sleep(0.2)
        if nano.bench and nano.bench["state"] == "UNLOCKED" and time.monotonic() - last_status > CLIENT_TIMEOUT_S:
            print("AVISO: a dashboard deixou de responder: STOP")
            try:
                nano.stop()
            except (NanoError, TimeoutError) as e:
                print("AVISO: o STOP falhou:", e)


# Corre no arranque (antes do yield) e no fim (depois do yield) do servidor
@asynccontextmanager
async def lifespan(app):
    global nano, running
    nano = Nano(PORT)
    threading.Thread(target=client_watchdog, daemon=True).start()
    yield
    running = False
    nano.close()                        # STOP + fechar


app = FastAPI(lifespan=lifespan)


# Chama um método do Nano e transforma os erros dele em erros HTTP, que a dashboard mostra
def call(method, *args):
    try:
        return method(*args)
    except NanoError as e:
        raise HTTPException(status_code=400, detail=str(e))       # o Nano recusou
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))       # o Nano não respondeu


# ----- A página -----

@app.get("/")
def dashboard():
    return FileResponse(os.path.join(HERE, "dashboard.html"))


# ----- Ler -----

# A dashboard pergunta isto a cada 500 ms (e é também o sinal de vida dela)
@app.get("/status")
def status():
    global last_status
    last_status = time.monotonic()
    return {
        "bench": call(nano.bench_state),
        "esc": call(nano.esc_state),
        "mode": call(nano.mode),
        "motor": call(nano.motor),
        "battery": call(nano.battery_status),
        "pot": call(nano.pot_reading),
    }


# ----- Agir -----

class ModeRequest(BaseModel):
    mode: str


class MotorRequest(BaseModel):
    percent: int


@app.post("/unlock")
def unlock():
    return {"state": call(nano.bench_unlock)}          # depois é preciso segurar o botão 2 s


@app.post("/stop")
def stop():
    call(nano.stop)
    return {"ok": True}


@app.post("/mode")
def set_mode(req: ModeRequest):
    try:
        return {"mode": call(nano.set_mode, req.mode)}
    except ValueError as e:                            # nem POT nem SERVER
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/motor")
def set_motor(req: MotorRequest):
    return {"motor": call(nano.set_motor, req.percent)}
