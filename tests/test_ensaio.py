#!/usr/bin/env python3
# Ensaio: runs a throttle profile on the motor and plots it in real time.
#
#   !!! The motor WILL TURN. Motor firmly fixed, nobody near the propeller !!!
#
# The profile is a function of time (profile(t) -> %). To make another ensaio,
# write another function and point PROFILE to it.
#
# Profile % are RELATIVE to the firmware limit: 100 % here = MOTOR_MAX_PERCENT on the Nano
# (50 % throttle = 1500 us). The real maximum is set ONLY in the firmware (pins.h).
#
# If anything looks wrong: tap the button (it always locks) or close the plot window.
#
# Run (with the monitor CLOSED):
#   python3 test_ensaio.py
#   python3 test_ensaio.py /dev/ttyUSB1      (another port)

import os
import re
import sys
import time

import matplotlib.pyplot as plt
import serial

# works both as "python3 tests/test_ensaio.py" and "python3 -m tests.test_ensaio"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests.test_commands as tc     # wait_ready(), read_line(), write(), heartbeat, PORT, BAUD
import tests.test_motor as tm        # reply(), unlock()

MOTOR_MAX_PERCENT = 50   # same as MOTOR_MAX_PERCENT in pins.h: the real throttle at 100 % here
SEND_PERIOD = 0.05       # s between MOTOR commands (20 per second)
COUNTDOWN_S = 3          # s between "unlocked" and the start of the profile

# ---------------------------------------------------------------------------
# Profiles: profile(t) -> throttle % wanted at t seconds, 0..100 relative to MOTOR_MAX_PERCENT
# ---------------------------------------------------------------------------

PARABOLA_S = 30.0        # total duration
PARABOLA_PEAK = 100.0    # % at the middle (t = 15 s)


def parabola(t):
    """0 % at t=0, PARABOLA_PEAK at t=PARABOLA_S/2, 0 % again at t=PARABOLA_S."""
    half = PARABOLA_S / 2
    return PARABOLA_PEAK * (1 - ((t - half) / half) ** 2)


PROFILE = parabola
DURATION = PARABOLA_S


# ---------------------------------------------------------------------------

def to_motor(relative):
    """Relative % (0..100) -> the real % sent with MOTOR (0..MOTOR_MAX_PERCENT)."""
    return round(min(max(relative, 0.0), 100.0) * MOTOR_MAX_PERCENT / 100)


def to_relative(real):
    """Real % from the Nano -> relative % (for the plot)."""
    return real * 100 / MOTOR_MAX_PERCENT


def motor(port, percent):
    """Sends MOTOR <percent> and returns the confirmed %, or None (and prints why) if refused.
    Faster than tc.send(): does not wait the extra silence time after the reply."""
    tc.write(port, f"MOTOR {percent}\n")
    line = tc.read_line(port, time.monotonic() + tc.REPLY_TIMEOUT)
    m = re.fullmatch(r"OK MOTOR (\d+)", line or "")
    if not m:
        print(f"      'MOTOR {percent}' -> {line}")
        return None
    return int(m.group(1))


def setup_plot():
    """Window with the wanted profile (dashed) and the live line, both in relative %."""
    plt.ion()
    fig, ax = plt.subplots(figsize=(9, 5))
    ts = [i * DURATION / 500 for i in range(501)]
    ax.plot(ts, [PROFILE(t) for t in ts], "--", color="gray", label="pedido")
    live, = ax.plot([], [], color="tab:blue", linewidth=2, label="confirmado pelo Nano")
    ax.set_xlim(0, DURATION)
    ax.set_ylim(0, 105)
    ax.set_xlabel("tempo (s)")
    ax.set_ylabel(f"throttle (% de {MOTOR_MAX_PERCENT} % real)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.canvas.draw()
    plt.pause(0.001)
    return fig, ax, live


def run_profile(port, fig, ax, live):
    """Sends the profile every SEND_PERIOD. Returns the rows (t, wanted, sent, confirmed):
    wanted in relative %, sent and confirmed in real % (what MOTOR uses)."""
    rows = []
    t0 = time.monotonic()
    next_send = t0
    while True:
        t = time.monotonic() - t0
        if t > DURATION:
            break
        if not plt.fignum_exists(fig.number):
            print("Plot window closed: stopping.")
            break

        wanted = max(0.0, PROFILE(t))
        sent = to_motor(wanted)
        confirmed = motor(port, sent)
        if confirmed is None:
            print("The Nano refused the command (bench locked?): stopping.")
            break
        rows.append((t, wanted, sent, confirmed))

        live.set_data([r[0] for r in rows], [to_relative(r[3]) for r in rows])
        ax.set_title(f"t = {t:4.1f} s    throttle = {to_relative(confirmed):.0f} %  ({confirmed} % real)")

        next_send += SEND_PERIOD
        plt.pause(max(0.001, next_send - time.monotonic()))   # redraws AND waits for the next tick
    return rows


def main():
    print(f"Ensaio '{PROFILE.__name__}': {DURATION:g} s"
          f" (100 % = {MOTOR_MAX_PERCENT} % real throttle).")
    print("!!! The motor WILL TURN. !!!")
    if input("Motor bem preso e ninguém perto da hélice? Escreve SIM para continuar: ").strip() != "SIM":
        print("Cancelled.")
        return 2

    try:
        port = serial.Serial(tc.PORT, tc.BAUD, timeout=0.05)
    except serial.SerialException as e:
        print(f"Could not open {tc.PORT}: {e}")
        print("Is the monitor (or the server) open? Close it and try again.")
        return 2

    print(f"Port {tc.PORT} open. Waiting for READY...")
    if not tc.wait_ready(port):
        print("ERROR: the Nano did not say READY")
        return 2

    # The Nano locks if it hears nothing for 1 s: the heartbeat covers the waits
    # (unlock, countdown). During the profile the MOTOR commands already count.
    tc.start_heartbeat(port)
    rows = []
    try:
        # known, safe state, in SERVER mode (the mode only changes while LOCKED)
        tm.reply(port, "STOP")
        if tm.reply(port, "MODE SERVER") != "OK MODE SERVER":
            return 1
        bat = tm.reply(port, "BAT")
        if not re.fullmatch(r"OK BAT (GOOD|WEAK) .*", bat):
            print("Connect a charged battery to the ESC and try again.")
            return 1
        # The plot window is opened BEFORE unlocking: over X11 (MobaXterm) creating it can freeze
        # Python (heartbeat included) for more than 1 s. With the bench still LOCKED that is harmless.
        fig, ax, live = setup_plot()
        ax.set_title("à espera do desbloqueio...")
        plt.pause(0.1)
        if not tm.unlock(port):
            print("Bench not unlocked.")
            return 1

        for i in range(COUNTDOWN_S, 0, -1):
            print(f"  starting in {i}...")
            ax.set_title(f"começa em {i}...")
            plt.pause(1)
        rows = run_profile(port, fig, ax, live)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        # ALWAYS leave the motor stopped and the bench locked
        tc.write(port, "MOTOR 0\nSTOP\n")
        time.sleep(0.2)
        tc.stop_heartbeat()
        port.close()
        print("STOP sent: motor at 0 %, bench locked.")
        print(f"Longest silence towards the Nano: {tc.longest_silence():.2f} s (it locks at 1 s).")

    if rows:
        peak = max(r[3] for r in rows)
        print(f"{len(rows)} points in {rows[-1][0]:.1f} s, peak {to_relative(peak):.0f} % ({peak} % real).")
        print("Close the plot window to exit.")
        plt.ioff()
        plt.show(block=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
