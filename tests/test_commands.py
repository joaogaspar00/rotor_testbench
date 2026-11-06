#!/usr/bin/env python3
# Teste de TODOS os comandos do Nano, através da classe Nano (servidor/communication.py).
#
# Envia cada comando, lê a resposta e compara-a com a esperada. Testa também a regra do protocolo:
# cada comando recebe EXATAMENTE uma linha de resposta. O motor NUNCA roda (o banco fica bloqueado).
#
# Correr (com a dashboard e o monitor FECHADOS: a porta só pode ser usada por um programa):
#   python3 tests/test_commands.py
#   python3 tests/test_commands.py /dev/ttyUSB1      (outra porta)

import os
import re
import sys
import time

import serial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "servidor"))
import communication
from communication import Nano, NanoError

PORT = sys.argv[1] if len(sys.argv) > 1 else communication.DEFAULT_PORT
EXTRA_S = 0.15           # s à espera de uma 2.ª linha de resposta (não pode haver)
SILENT_S = 1.5           # s sem enviar nada: mais do que o SERVER_TIMEOUT_MS do Nano (1 s)

# (comando enviado, resposta esperada). A resposta é uma expressão regular que tem de bater com a linha INTEIRA.
# P. ex. r"OK POT \d+" aceita "OK POT 523" (\d+ = um ou mais algarismos).
SECCOES = [
    ("POT · o potenciómetro", [
        ("POT",                 r"OK POT \d+"),
        ("POT 3",               r"ERROR POT expects 0 values: POT"),
    ]),
    ("AIR · o ar (BMP280)", [
        ("AIR",                 r"OK AIR -?\d+\.\d\dC \d+\.\d\dhPa \d+\.\d{4}kg/m3|ERROR AIR no sensor"),
        ("AIR 1",               r"ERROR AIR expects 0 values: AIR"),
    ]),
    ("THRUST · a célula de carga (HX711)", [
        ("THRUST",              r"OK THRUST -?\d+(\.\d+)?gf -?\d+\.\d\dN|ERROR THRUST no sensor"),
        ("THRUST",              r"OK THRUST -?\d+(\.\d+)?gf -?\d+\.\d\dN|ERROR THRUST no sensor"),   # logo a seguir: espera pela leitura seguinte
        ("THRUST 1",            r"ERROR THRUST expects 0 values: THRUST"),
    ]),
    ("TONE · o buzzer", [
        ("TONE 2000 200",       r"OK TONE 2000 200"),
        ("TONE 1000",           r"OK TONE 1000 0"),                  # toca até ser parado
        ("TONE 0",              r"OK TONE 0 0"),                     # pára
        ("TONE 0 500",          r"OK TONE 0 0"),                     # 0 Hz = parar, o ms é ignorado
        ("TONE",                r"ERROR TONE expects 1 to 2 values: TONE <freq> \[ms\]"),
        ("TONE 1000 200 5",     r"ERROR TONE expects 1 to 2 values: TONE <freq> \[ms\]"),
        ("TONE abc",            r"ERROR TONE invalid value: abc"),
        ("TONE 12x",            r"ERROR TONE invalid value: 12x"),
        ("TONE 30",             r"ERROR TONE invalid value: 30"),    # abaixo de TONE_MIN_HZ (31)
        ("TONE 10001",          r"ERROR TONE invalid value: 10001"), # acima de TONE_MAX_HZ
        ("TONE -5",             r"ERROR TONE invalid value: -5"),
        ("TONE 2000 -5",        r"ERROR TONE invalid value: -5"),
        ("TONE 2000 10001",     r"ERROR TONE invalid value: 10001"), # acima de TONE_MAX_MS
        ("TONE 2000 abc",       r"ERROR TONE invalid value: abc"),
    ]),
    ("STOP · põe tudo em segurança", [
        ("TONE 1000",           r"OK TONE 1000 0"),
        ("STOP",                r"OK STOP"),                         # também cala o buzzer
        ("STOP 1",              r"ERROR STOP expects 0 values: STOP"),
    ]),
    ("BENCH / UNLOCK · o bloqueio (o botão testa-se no test_motor)", [
        ("STOP",                r"OK STOP"),
        ("BENCH",               r"OK BENCH LOCKED STOP"),            # o STOP bloqueia, e diz porquê
        ("BENCH 1",             r"ERROR BENCH expects 0 values: BENCH"),
        ("UNLOCK",              r"OK UNLOCK UNLOCKING|ERROR UNLOCK not ready:( (NO_BATTERY|ESC_ARMING|LOW_VOLTAGE|POT_NOT_ZERO|BATTERY_CUT|SERVER_LOST))+"),
        ("STOP",                r"OK STOP"),                         # cancela o UNLOCK pendente
        ("BENCH",               r"OK BENCH LOCKED STOP"),            # o UNLOCK sozinho nunca desbloqueia
        ("UNLOCK 1",            r"ERROR UNLOCK expects 0 values: UNLOCK"),
    ]),
    ("MODE · quem controla o throttle", [
        ("MODE",                r"OK MODE SERVER"),                  # arranca em SERVER
        ("MODE POT",            r"OK MODE POT"),
        ("MOTOR 10",            r"ERROR MOTOR mode POT"),            # em POT quem manda é o pot
        ("MOTOR",               r"OK MOTOR 0"),                      # ler funciona nos dois modos
        ("MODE XPTO",           r"ERROR MODE invalid value: XPTO"),
        ("MODE pot",            r"ERROR MODE invalid value: pot"),   # só MAIÚSCULAS
        ("MODE POT SERVER",     r"ERROR MODE expects 0 to 1 values: MODE \[POT\|SERVER\]"),
        ("MODE SERVER",         r"OK MODE SERVER"),
    ]),
    ("MOTOR · com o banco bloqueado: o motor NUNCA roda", [
        ("STOP",                r"OK STOP"),
        ("MOTOR",               r"OK MOTOR 0"),
        ("MOTOR 0",             r"OK MOTOR 0"),                      # o 0 é sempre aceite
        ("MOTOR 10",            r"ERROR MOTOR bench LOCKED STOP"),   # bloqueado: recusado
        ("MOTOR",               r"OK MOTOR 0"),                      # ...e não mexeu
        ("MOTOR 51",            r"ERROR MOTOR invalid value: 51"),   # acima do MOTOR_MAX_PERCENT (50)
        ("MOTOR -1",            r"ERROR MOTOR invalid value: -1"),
        ("MOTOR abc",           r"ERROR MOTOR invalid value: abc"),
        ("MOTOR 10.5",          r"ERROR MOTOR invalid value: 10.5"), # só percentagens inteiras
        ("MOTOR 1 2",           r"ERROR MOTOR expects 0 to 1 values: MOTOR \[0\.\.100\]"),
    ]),
    ("BAT / ESC · a bateria", [
        ("BAT",                 r"OK BAT (NONE|GOOD|WEAK|LOW) \d+\.\d\dV"),
        ("BAT 1",               r"ERROR BAT expects 0 values: BAT"),
        ("ESC",                 r"OK ESC (NONE|ARMING|ARMED)"),
        ("ESC 1",               r"ERROR ESC expects 0 values: ESC"),
    ]),
    ("PING / HELP", [
        ("PING",                r"OK PING"),
        ("PING 1",              r"ERROR PING expects 0 values: PING"),
        ("HELP",                r"OK POT AIR TONE BENCH UNLOCK MOTOR THRUST MODE BAT ESC STOP PING HELP"),
    ]),
    ("Comandos desconhecidos e formato da linha", [
        ("XPTO 1",              r"ERROR unknown command: XPTO"),
        ("led 1",               r"ERROR unknown command: led"),      # os nomes são em MAIÚSCULAS
        ("",                    r"ERROR empty command.*"),
        ("   TONE   0   ",      r"OK TONE 0 0"),                     # espaços a mais não mudam nada
        ("X 1 2 3 4 5 6 7 8 9 10 11", r"ERROR more than 10 values"),
        ("STOP",                r"OK STOP"),                         # deixa tudo em segurança
    ]),
]

EVENTOS_VALIDOS = r"EVT POT \d+|EVT ESC (NONE|ARMING|ARMED)|EVT BENCH (UNLOCKED|UNLOCKING|LOCKED( \w+)+)"


# ---------------------------------------------------------------------------
# Aparência (cores ANSI; sem cores se a saída não for um terminal)
# ---------------------------------------------------------------------------

COR = sys.stdout.isatty()
def _cor(codigo):
    return (lambda t: f"\033[{codigo}m{t}\033[0m") if COR else (lambda t: str(t))
negrito, tenue, verde, vermelho, amarelo, azul, ciano = (_cor(c) for c in ("1", "2", "32", "31", "33", "34", "36"))
PASSOU, FALHOU, SALTOU = verde("✔"), vermelho("✘"), amarelo("–")


def titulo(texto, sub=""):
    largura = 66
    print("\n" + azul("╭" + "─" * largura + "╮"))
    print(azul("│") + negrito(f"  {texto}".ljust(largura)) + azul("│"))
    if sub:
        print(azul("│") + tenue(f"  {sub}".ljust(largura)) + azul("│"))
    print(azul("╰" + "─" * largura + "╯"))


def seccao(texto):
    print("\n" + negrito(ciano(f"▸ {texto}")))


# O communication.py escreve avisos com print(): aparecem esbatidos, para não se misturarem com os resultados.
# Os eventos não são escritos: ficam guardados no Banco (e são verificados no fim).
def _print_do_nano(*args, **kwargs):
    texto = " ".join(str(a) for a in args)
    if not texto.startswith("EVT "):
        print(tenue(f"    · {texto}"))
communication.print = _print_do_nano


class Banco(Nano):
    """O Nano de sempre, mas guarda todos os eventos que chegam."""
    def __init__(self, port):
        self.eventos = []
        super().__init__(port)

    def _handle_event(self, line):
        self.eventos.append(line)
        super()._handle_event(line)


# ---------------------------------------------------------------------------

resultados = []          # (nome, True / False / None = saltado)


def registar(nome, ok, resposta="", detalhe="", ms=None):
    resultados.append((nome, ok))
    marca = PASSOU if ok else (SALTOU if ok is None else FALHOU)
    tempo = tenue(f"{ms:4.0f} ms") if ms is not None else ""
    print(f"  {marca} {nome:<28} {tenue('→')} {resposta}  {tempo}")
    if detalhe:
        print(f"      {(amarelo if ok is None else vermelho)(detalhe)}")


def pedir(nano, comando):
    """Envia UM comando. Devolve (resposta, linhas a mais, ms até chegar a resposta)."""
    inicio = time.monotonic()
    try:
        resposta = nano.send(comando)
    except TimeoutError:
        return None, [], (time.monotonic() - inicio) * 1000
    ms = (time.monotonic() - inicio) * 1000
    with nano._send_lock:              # ninguém envia (nem o heartbeat) enquanto se vê se chega uma 2.ª linha
        time.sleep(EXTRA_S)
        extra = []
        while not nano.replies.empty():
            extra.append(nano.replies.get())
    return resposta, extra, ms


def mostrar_comando(comando):
    return comando if comando and comando == comando.strip() else repr(comando)


def testar_comandos(nano):
    for nome_seccao, testes in SECCOES:
        seccao(nome_seccao)
        for comando, esperado in testes:
            resposta, extra, ms = pedir(nano, comando)
            if resposta is None:
                ok, detalhe = False, "sem resposta"
            elif extra:
                ok, detalhe = False, f"{1 + len(extra)} linhas (deve ser 1): {extra}"
            elif not re.fullmatch(esperado, resposta):
                ok, detalhe = False, f"esperado /{esperado}/"
            else:
                ok, detalhe = True, ""
            registar(mostrar_comando(comando), ok, resposta or "-", detalhe, ms)


def testar_funcoes(nano):
    """As funções do communication.py que o servidor usa: traduzem a resposta em valores Python."""
    seccao("Funções do communication.py (o que o servidor usa)")
    funcoes = [
        ("battery_status()",  nano.battery_status,  lambda v: isinstance(v, dict) and isinstance(v["voltage"], float)),
        ("esc_state()",       nano.esc_state,       lambda v: v in ("NONE", "ARMING", "ARMED")),
        ("pot_reading()",     nano.pot_reading,     lambda v: isinstance(v, int)),
        ("bench_state()",     nano.bench_state,     lambda v: v["state"] == "LOCKED"),
        ("mode()",            nano.mode,            lambda v: v == "SERVER"),
        ("motor()",           nano.motor,           lambda v: v == 0),
        ("air_readings()",    nano.air_readings,    lambda v: v is None or isinstance(v["density"], float)),
        ("thrust_readings()", nano.thrust_readings, lambda v: v is None or isinstance(v["gf"], float)),
    ]
    for nome, funcao, valido in funcoes:
        try:
            valor = funcao()
            if valor is None:
                registar(nome, None, "None", "sem sensor: o banco funciona, mas sem esta medida")
            else:
                registar(nome, valido(valor), str(valor), "" if valido(valor) else "valor inesperado")
        except (NanoError, TimeoutError) as e:
            registar(nome, False, "-", str(e))


def testar_thrust_continuo(nano, n=10):
    """Pedidos THRUST seguidos: cada um espera pela leitura seguinte, por isso saem ~10 por segundo."""
    seccao(f"THRUST em contínuo · {n} pedidos seguidos")
    if nano.thrust_readings() is None:
        registar("ritmo das leituras", None, "-", "sem célula de carga")
        return
    inicio = time.monotonic()
    leituras = [nano.thrust_readings()["gf"] for _ in range(n)]
    ritmo = n / (time.monotonic() - inicio)
    ok = 7 <= ritmo <= 13                  # a HX711 desta placa faz 10 leituras por segundo
    registar("ritmo das leituras", ok, f"{ritmo:.1f} leituras/s",
             "" if ok else "esperado ~10/s (a placa está a 10 SPS)")
    print(tenue(f"      gf: {', '.join(f'{g:.0f}' for g in leituras)}"))


def testar_especiais(nano):
    seccao("Protocolo")

    # Duas linhas enviadas de uma vez: duas respostas, pela ordem certa
    with nano._send_lock:
        while not nano.replies.empty():
            nano.replies.get()
        nano.port.write(b"TONE 0\nBENCH\n")
        try:
            r1 = nano.replies.get(timeout=1)
            r2 = nano.replies.get(timeout=1)
        except Exception:
            r1 = r2 = None
    ok = r1 == "OK TONE 0 0" and r2 is not None and r2.startswith("OK BENCH ")
    registar("duas linhas de uma vez", ok, f"{r1} | {r2}")

    # Heartbeat: com o banco UNLOCKING, 1,5 s de silêncio tem de o bloquear (SERVER_LOST).
    # Precisa da bateria ligada e do pot no zero; senão o UNLOCK é recusado e o teste é saltado.
    nano.esc_armed.wait(5)                 # depois do reset, o ESC demora 3 s a armar
    resposta, _, _ = pedir(nano, "UNLOCK")
    if resposta == "OK UNLOCK UNLOCKING":
        with nano._send_lock:              # segura o envio: o heartbeat não consegue enviar PING
            time.sleep(SILENT_S)
        resposta, _, _ = pedir(nano, "BENCH")
        registar(f"{SILENT_S} s em silêncio → bloqueia", resposta == "OK BENCH LOCKED CHECK SERVER_LOST", resposta)
    else:
        registar(f"{SILENT_S} s em silêncio → bloqueia", None, resposta, "UNLOCK recusado: ligue a bateria e ponha o pot no zero")
    pedir(nano, "STOP")

    # Todos os eventos que chegaram têm de ter o formato certo
    maus = [e for e in nano.eventos if not re.fullmatch(EVENTOS_VALIDOS, e)]
    registar("formato dos eventos", not maus, f"{len(nano.eventos)} eventos recebidos",
             f"mal formados: {maus}" if maus else "")


def resumo():
    passou = sum(1 for _, ok in resultados if ok)
    falhou = [n for n, ok in resultados if ok is False]
    saltou = sum(1 for _, ok in resultados if ok is None)
    total = len(resultados)
    print()
    linha = f"  {passou}/{total - saltou} passaram" + (f"  ·  {saltou} saltados" if saltou else "")
    if falhou:
        print(vermelho(negrito(f"✘{linha}  ·  {len(falhou)} falharam")))
        print(vermelho("    " + ", ".join(falhou)))
    else:
        print(verde(negrito(f"✔{linha}")))
    return 1 if falhou else 0


def ligar():
    """Abre a porta e espera pelo READY. Devolve o Banco, ou None (e diz porquê) se não conseguir."""
    print(tenue(f"  porta {PORT}"))
    print("  A ligar... (o Nano reinicia e faz a tara da célula: não toque na bancada)")
    try:
        return Banco(PORT)
    except serial.SerialException as e:
        print(vermelho(f"  Não abriu a porta: {e}"))
        print("  A dashboard ou o monitor estão abertos? Feche-os e tente outra vez.")
    except TimeoutError:
        print(vermelho("  O Nano não disse READY (firmware errado? porta errada?)"))
    return None


def main():
    titulo("Teste dos comandos", "todos os comandos do Nano · o motor NÃO roda")
    nano = ligar()
    if nano is None:
        return 2

    try:
        testar_comandos(nano)
        testar_funcoes(nano)
        testar_thrust_continuo(nano)
        testar_especiais(nano)
    except KeyboardInterrupt:
        print(amarelo("\n  Interrompido."))
    finally:
        nano.close()                       # STOP + fechar, aconteça o que acontecer
    return resumo()


if __name__ == "__main__":
    sys.exit(main())
