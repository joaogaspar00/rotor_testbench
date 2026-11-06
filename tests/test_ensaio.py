#!/usr/bin/env python3
# Pequeno ensaio COM A HÉLICE: a curva da força em função do throttle.
#
#   !!! O MOTOR VAI RODAR COM A HÉLICE: motor bem preso, ninguém à frente nem ao lado da hélice !!!
#
# Em cada degrau de throttle: espera ESTABILIZAR_S (o motor acelera) e mede durante MEDIR_S
# (THRUST em contínuo, ~10 leituras/s, e a tensão da bateria). O primeiro e o último degrau são
# a 0 %: o zero da célula antes e depois (a força é corrigida pelo zero de antes; a diferença
# entre os dois é a deriva durante o ensaio).
#
# No fim mostra a curva no terminal e grava em ensaios/:
#   <data>_resumo.csv     uma linha por degrau (a curva)
#   <data>_leituras.csv   todas as leituras, também as de estabilização (para ver os transitórios)
#   <data>.png            os gráficos: a força e o throttle no tempo, e a curva força × throttle
#                         (abre-se no VS Code com um clique; não precisa de janela nem de X11)
#
# Se algo parecer errado: um toque no botão bloqueia sempre, ou Ctrl+C (o script envia STOP e grava
# o que já mediu).
#
# Correr (com a dashboard e o monitor FECHADOS):
#   python3 tests/test_ensaio.py
#   python3 tests/test_ensaio.py /dev/ttyUSB1      (outra porta)

import csv
import os
import statistics
import sys
import time

import matplotlib
matplotlib.use("Agg")                 # só grava ficheiros: nunca abre janelas (corre no terminal do VS Code)
import matplotlib.pyplot as plt

import test_commands as tc
import test_motor as tm               # barra(), linha_viva(), confirmar(), mostrar_estado(), desbloquear()
from communication import NanoError
from test_commands import negrito, tenue, verde, vermelho, amarelo, ciano

DEGRAUS = [0, 10, 20, 30, 40, 50, 0]  # % de throttle (o MOTOR_MAX_PERCENT do Nano é 50)
ESTABILIZAR_S = 2                     # s à espera que o motor estabilize em cada degrau
MEDIR_S = 3                           # s a medir em cada degrau (~30 leituras)
PASTA = os.path.join(tc.ROOT, "ensaios")


def medir_degrau(nano, percent, t0, leituras):
    """Um degrau: põe o throttle, espera e mede. Junta as leituras a 'leituras'. Devolve o resumo do degrau."""
    nano.set_motor(percent)
    inicio = time.monotonic()
    fim = inicio + ESTABILIZAR_S + MEDIR_S
    gfs, volts = [], []
    while (agora := time.monotonic()) < fim:
        fase = "estabilizar" if agora - inicio < ESTABILIZAR_S else "medir"
        forca = nano.thrust_readings()                 # espera pela leitura seguinte (~100 ms)
        bat = nano.battery_status()["voltage"]
        leituras.append({"t_s": round(time.monotonic() - t0, 3), "throttle_pct": percent, "fase": fase,
                         "forca_gf": forca["gf"], "forca_N": forca["newtons"], "bateria_V": bat})
        if fase == "medir":
            gfs.append(forca["gf"])
            volts.append(bat)
        cor_fase = amarelo if fase == "estabilizar" else verde
        tm.linha_viva(f"    {tm.barra(percent)} {percent:3d} %   {forca['gf']:7.0f} gf   {bat:5.2f} V   "
                      f"{cor_fase(fase)} {tenue(f'{fim - agora:3.1f} s')}")
    ar = nano.air_readings()
    return {
        "throttle_pct": percent,
        "n": len(gfs),
        "forca_gf": statistics.mean(gfs),
        "desvio_gf": statistics.pstdev(gfs),
        "bateria_V": statistics.mean(volts),
        "temp_C": ar["temperature"] if ar else None,
        "pressao_hPa": ar["pressure"] if ar else None,
        "densidade_kg_m3": ar["density"] if ar else None,
    }


def mostrar_curva(degraus, zero):
    """A curva no terminal: uma barra por degrau, com a força já corrigida pelo zero."""
    tc.seccao("Curva · força em função do throttle (corrigida pelo zero inicial)")
    maximo = max((d["forca_corrigida_gf"] for d in degraus), default=1) or 1
    for d in degraus:
        f = d["forca_corrigida_gf"]
        cheio = max(0, round(40 * f / maximo))
        extra = tenue(f"±{d['desvio_gf']:.1f}  {d['bateria_V']:.2f} V")
        print(f"    {d['throttle_pct']:3d} %  {ciano('█' * cheio)}{' ' * (40 - cheio)} {negrito(f'{f:7.1f}')} gf  {extra}")
    print(tenue(f"    zero inicial: {zero:.1f} gf"))


def gravar(nome, degraus, leituras):
    """Grava os dois CSV. Devolve os caminhos."""
    ficheiros = []
    for sufixo, linhas in (("resumo", degraus), ("leituras", leituras)):
        if not linhas:
            continue
        caminho = os.path.join(PASTA, f"{nome}_{sufixo}.csv")
        with open(caminho, "w", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
            escritor.writeheader()
            escritor.writerows(linhas)
        ficheiros.append(caminho)
    return ficheiros


def grafico(nome, degraus, leituras, zero):
    """Grava o PNG: em cima a força e o throttle no tempo, em baixo a curva força × throttle."""
    fig, (cima, baixo) = plt.subplots(2, 1, figsize=(10, 9), gridspec_kw={"height_ratios": [3, 2]})
    fig.suptitle(f"Ensaio {nome}", fontweight="bold")

    # 1) No tempo: cada leitura (as de estabilização mais claras) e o throttle por trás, noutro eixo
    for fase, cor, rotulo in (("estabilizar", "#9ecae1", "a estabilizar"), ("medir", "#08519c", "medida")):
        pontos = [l for l in leituras if l["fase"] == fase]
        cima.plot([l["t_s"] for l in pontos], [l["forca_gf"] - zero for l in pontos],
                  ".", color=cor, markersize=4, label=f"força ({rotulo})")
    cima.set_xlabel("tempo (s)")
    cima.set_ylabel("força (gf, corrigida pelo zero)")
    cima.grid(True, alpha=0.3)
    throttle = cima.twinx()
    throttle.step([l["t_s"] for l in leituras], [l["throttle_pct"] for l in leituras],
                  where="post", color="#e6550d", alpha=0.6, label="throttle")
    throttle.set_ylabel("throttle (%)", color="#e6550d")
    throttle.set_ylim(0, 100)
    linhas_a, rotulos_a = cima.get_legend_handles_labels()
    linhas_b, rotulos_b = throttle.get_legend_handles_labels()
    cima.legend(linhas_a + linhas_b, rotulos_a + rotulos_b, loc="upper left")

    # 2) A curva: a média de cada degrau com o desvio. O 0 % final fica à parte: mostra a deriva do zero
    curva = degraus[:-1] if len(degraus) > 1 and degraus[-1]["throttle_pct"] == 0 else degraus
    baixo.errorbar([d["throttle_pct"] for d in curva], [d["forca_corrigida_gf"] for d in curva],
                   yerr=[d["desvio_gf"] for d in curva], fmt="o-", color="#08519c", capsize=4, label="média ± desvio")
    if curva is not degraus:
        baixo.plot(0, degraus[-1]["forca_corrigida_gf"], "x", color="#e6550d", markersize=10,
                   label=f"zero no fim (deriva {degraus[-1]['forca_corrigida_gf']:+.1f} gf)")
    baixo.legend(loc="upper left")
    for d in degraus:
        if d["throttle_pct"] > 0:
            baixo.annotate(f"{d['forca_corrigida_gf']:.0f} gf", (d["throttle_pct"], d["forca_corrigida_gf"]),
                           textcoords="offset points", xytext=(-8, 8), ha="right", fontsize=9)
    baixo.set_xlabel("throttle (%)")
    baixo.set_ylabel("força (gf)")
    baixo.grid(True, alpha=0.3)

    fig.tight_layout()
    caminho = os.path.join(PASTA, f"{nome}.png")
    fig.savefig(caminho, dpi=120)
    plt.close(fig)
    return caminho


def main():
    tc.titulo("Ensaio com a hélice", f"degraus {DEGRAUS} %  ·  {ESTABILIZAR_S} s a estabilizar + {MEDIR_S} s a medir")
    if not tm.confirmar("O MOTOR VAI RODAR COM A HÉLICE.",
                        "Motor bem preso e ninguém à frente nem ao lado da hélice?"):
        print("  Cancelado.")
        return 2

    nano = tc.ligar()
    if nano is None:
        return 2
    degraus, leituras = [], []
    try:
        pronta, ha_celula = tm.mostrar_estado(nano)
        if not ha_celula:
            print(vermelho("    O ensaio precisa da célula de carga."))
        if not pronta or not ha_celula:
            return 1
        if not tm.desbloquear(nano):
            return 1

        tc.seccao("Ensaio")
        t0 = time.monotonic()
        for percent in DEGRAUS:
            d = medir_degrau(nano, percent, t0, leituras)
            degraus.append(d)
            desvio = tenue(f"±{d['desvio_gf']:.1f}")
            tm.fim_linha_viva(f"    {tm.barra(percent)} {percent:3d} %   {d['forca_gf']:7.1f} gf  {desvio}   {d['bateria_V']:5.2f} V")
        nano.set_motor(0)
        tc.registar("ensaio completo", True, f"{len(DEGRAUS)} degraus, {len(leituras)} leituras")
    except KeyboardInterrupt:
        print(amarelo("\n  Interrompido: grava o que já foi medido."))
    except NanoError as e:
        print(vermelho(f"\n  O Nano recusou ({e}): o banco bloqueou? Grava o que já foi medido."))
        tc.registar("ensaio completo", False, "-", str(e))
    finally:
        nano.close()                   # STOP + fechar: motor a 0 e banco bloqueado, aconteça o que acontecer
        print(tenue("  STOP enviado: motor a 0 %, banco bloqueado."))

    if degraus:
        zero = degraus[0]["forca_gf"] if degraus[0]["throttle_pct"] == 0 else 0.0
        for d in degraus:
            d["forca_corrigida_gf"] = round(d["forca_gf"] - zero, 1)
            d["forca_corrigida_N"] = round(d["forca_corrigida_gf"] * 0.00980665, 3)
        mostrar_curva([d for d in degraus if d["throttle_pct"] > 0], zero)
        if len(degraus) == len(DEGRAUS) and DEGRAUS[-1] == 0:
            deriva = degraus[-1]["forca_gf"] - zero
            ok = abs(deriva) < 10
            tc.registar("deriva do zero", ok, f"{deriva:+.1f} gf",
                        "" if ok else "o zero mudou muito: a célula aqueceu ou a montagem cedeu?")
        tc.seccao("Ficheiros")
        os.makedirs(PASTA, exist_ok=True)
        nome = time.strftime("%Y-%m-%d_%H%M%S")
        ficheiros = gravar(nome, degraus, leituras)
        if leituras:
            ficheiros.append(grafico(nome, degraus, leituras, zero))
        for caminho in ficheiros:
            print(f"    {os.path.relpath(caminho, tc.ROOT)}")
    return tc.resumo()


if __name__ == "__main__":
    sys.exit(main())
