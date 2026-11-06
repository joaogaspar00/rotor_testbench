#!/usr/bin/env python3
# Teste do motor EM VAZIO: o motor VAI RODAR.
#
#   !!! SEM A HÉLICE, com o motor bem preso !!!
#
# 1. mostra o estado da bancada (bateria, ESC, sensores)
# 2. confirma que, bloqueado, o MOTOR é recusado
# 3. desbloqueia (você segura o botão 2 s)
# 4. sobe e desce o throttle por degraus, a mostrar a bateria e a célula em tempo real
# 5. com o motor a rodar e a célula a ser lida em contínuo, você dá UM toque no botão: tem de bloquear
#
# Se algo parecer errado: um toque no botão bloqueia sempre, ou Ctrl+C (o script envia STOP).
#
# Correr (com a dashboard e o monitor FECHADOS):
#   python3 tests/test_motor.py
#   python3 tests/test_motor.py /dev/ttyUSB1      (outra porta)

import statistics
import sys
import time

import test_commands as tc            # cores, títulos, ligar(), registar(), resumo()
from communication import NanoError
from test_commands import negrito, tenue, verde, vermelho, amarelo, ciano

MOTOR_MAX = 50                         # o MOTOR_MAX_PERCENT do pins.h: o Nano nunca passa disto
DEGRAUS = [10, 20, 30, 40, 50, 30, 10] # % de throttle, por esta ordem
DEGRAU_S = 3                           # s em cada degrau
TOQUE = 15                             # % com que o motor roda durante o teste do toque
TOQUE_ESPERA_S = 15                    # s para dar o toque


# ---------------------------------------------------------------------------
# Peças usadas também pelo test_ensaio
# ---------------------------------------------------------------------------

def barra(percent, maximo=MOTOR_MAX, largura=20):
    cheio = round(largura * min(max(percent, 0), maximo) / maximo)
    return ciano("█" * cheio) + tenue("░" * (largura - cheio))


def linha_viva(texto):
    """Reescreve a mesma linha do terminal (um mostrador em tempo real)."""
    if tc.COR:
        print("\r" + texto + "\033[K", end="", flush=True)


def fim_linha_viva(texto):
    if tc.COR:
        print("\r" + texto + "\033[K")
    else:
        print(texto)


def perguntar(pergunta):
    resposta = input(f"  {amarelo('?')} {pergunta} [s/n] ").strip().lower()
    return resposta in ("s", "sim", "y", "yes")


def confirmar(aviso, pergunta):
    print("\n  " + vermelho(negrito(f"⚠  {aviso}")))
    return input(f"  {pergunta} Escreva SIM para continuar: ").strip() == "SIM"


def mostrar_estado(nano):
    """Mostra o estado da bancada. Devolve (bateria pronta?, há célula?)."""
    tc.seccao("Estado da bancada")
    bat = nano.battery_status()
    nano.esc_armed.wait(5)             # depois do reset, o ESC demora 3 s a armar
    esc = nano.esc_state()
    ar = nano.air_readings()
    forca = nano.thrust_readings()
    cor_bat = verde if bat["state"] == "GOOD" else (amarelo if bat["state"] == "WEAK" else vermelho)
    print(f"    bateria   {cor_bat(bat['state']):<6}  {bat['voltage']:.2f} V")
    print(f"    ESC       {(verde if esc == 'ARMED' else amarelo)(esc)}")
    print(f"    banco     {nano.bench_state()['state']}   modo {nano.mode()}")
    print(f"    ar        " + (f"{ar['temperature']:.1f} °C  {ar['pressure']:.1f} hPa  {ar['density']:.4f} kg/m³"
                                if ar else amarelo("sem sensor")))
    print(f"    célula    " + (f"{forca['gf']:.0f} gf (deve estar perto de 0)" if forca else amarelo("sem sensor")))
    pronta = bat["state"] in ("GOOD", "WEAK") and esc == "ARMED"
    if not pronta:
        print(vermelho("    Ligue uma bateria carregada ao ESC e tente outra vez."))
    return pronta, forca is not None


def desbloquear(nano):
    """UNLOCK + você segura o botão 2 s. Devolve True quando o banco está UNLOCKED."""
    tc.seccao("Desbloquear")
    try:
        nano.bench_unlock()
    except NanoError as e:
        tc.registar("UNLOCK", False, "-", str(e))
        return False
    print(f"    {negrito('Segure o botão 2 s')} (o LED vermelho pisca depressa, depois um apito longo)...")
    ok = nano.wait_unlocked()
    tc.registar("UNLOCK + botão 2 s", ok, nano.bench["state"] if nano.bench else "-")
    return ok


# ---------------------------------------------------------------------------

def rodar(nano, percent, segundos, ha_celula):
    """Põe o motor a 'percent' durante 'segundos', com um mostrador em tempo real. Devolve (volts, gf)."""
    nano.set_motor(percent)
    volts, gfs = [], []
    fim = time.monotonic() + segundos
    while (resta := fim - time.monotonic()) > 0:
        if ha_celula:
            gfs.append(nano.thrust_readings()["gf"])   # espera pela leitura seguinte (~100 ms)
        else:
            time.sleep(0.1)
        volts.append(nano.battery_status()["voltage"])
        forca = f"{gfs[-1]:7.0f} gf" if gfs else tenue("   — gf")
        linha_viva(f"    {barra(percent)} {percent:3d} %   {volts[-1]:5.2f} V   {forca}   {tenue(f'{resta:3.1f} s')}")
    return volts, gfs


def testar_degraus(nano, ha_celula):
    tc.seccao(f"Degraus · {DEGRAU_S} s em cada um")
    linhas = []
    for percent in DEGRAUS:
        volts, gfs = rodar(nano, percent, DEGRAU_S, ha_celula)
        v = statistics.mean(volts)
        if gfs:
            ruido = statistics.pstdev(gfs)
            forca = f"{statistics.mean(gfs):6.0f} gf  ±{ruido:4.0f}"
        else:
            forca = tenue("sem célula")
        fim_linha_viva(f"    {barra(percent)} {percent:3d} %   {v:5.2f} V   {forca}")
        linhas.append((percent, v))
    nano.set_motor(0)

    queda = linhas[0][1] - min(v for _, v in linhas)
    print(tenue(f"    a tensão caiu até {queda:.2f} V com o motor a rodar"))
    print(tenue("    em vazio a força deve ficar perto de 0: o ± é o ruído (vibração)"))
    tc.registar("degraus sem erros", True, f"{len(DEGRAUS)} degraus")
    tc.registar("o motor rodou suave", perguntar("O motor acompanhou os degraus, sem ruídos estranhos?"), "")


def testar_toque(nano, ha_celula):
    """O toque no botão tem de bloquear MESMO com a célula a ser lida em contínuo (o loop do Nano
    passa a maior parte do tempo à espera da leitura seguinte)."""
    tc.seccao("Toque no botão com o motor a rodar")
    nano.set_motor(TOQUE)
    print(f"    Motor a {TOQUE} %. {negrito('Dê UM toque curto no botão.')} "
          + tenue(f"(a célula está a ser lida em contínuo; tem {TOQUE_ESPERA_S} s)"))
    inicio = time.monotonic()
    pedidos = 0
    while time.monotonic() - inicio < TOQUE_ESPERA_S:
        if nano.bench and nano.bench["state"] == "LOCKED":
            break
        if ha_celula:
            nano.thrust_readings()
            pedidos += 1
        else:
            time.sleep(0.05)
        linha_viva(tenue(f"    à espera do toque... {time.monotonic() - inicio:4.1f} s   ({pedidos} THRUST)"))
    fim_linha_viva("")
    bloqueou = nano.bench is not None and nano.bench["state"] == "LOCKED"
    motivo = " ".join(filter(None, [nano.bench["state"], nano.bench["reason"]])) if nano.bench else "-"
    tc.registar("toque → LOCKED BUTTON", bloqueou and nano.bench["reason"] == "BUTTON", motivo,
                "" if bloqueou else "o toque não foi visto: o Nano estava parado à espera da célula?")
    tc.registar("toque → motor a 0", nano.motor() == 0, f"MOTOR {nano.motor()}")
    if bloqueou:
        tc.registar("o motor parou", perguntar("O motor parou com o toque?"), "")


def main():
    tc.titulo("Teste do motor em vazio", "o motor VAI RODAR · sem hélice")
    if not confirmar("O MOTOR VAI RODAR.", "Hélice retirada e motor bem preso?"):
        print("  Cancelado.")
        return 2

    nano = tc.ligar()
    if nano is None:
        return 2
    try:
        pronta, ha_celula = mostrar_estado(nano)
        if not pronta:
            return 1

        tc.seccao("Bloqueado: o motor não pode rodar")
        nano.stop()
        try:
            nano.set_motor(TOQUE)
            tc.registar(f"MOTOR {TOQUE} bloqueado", False, "aceite!", "o banco bloqueado aceitou o MOTOR")
        except NanoError as e:
            tc.registar(f"MOTOR {TOQUE} bloqueado", True, "recusado")

        if desbloquear(nano):
            testar_degraus(nano, ha_celula)
            testar_toque(nano, ha_celula)
    except KeyboardInterrupt:
        print(amarelo("\n  Interrompido."))
    except NanoError as e:
        print(vermelho(f"\n  O Nano recusou: {e}"))
        tc.registar("sem erros do Nano", False, "-", str(e))
    finally:
        nano.close()                   # STOP + fechar: motor a 0 e banco bloqueado, aconteça o que acontecer
        print(tenue("  STOP enviado: motor a 0 %, banco bloqueado."))
    return tc.resumo()


if __name__ == "__main__":
    sys.exit(main())
