#!/usr/bin/env python3
# Interactive MOTOR test: the motor WILL TURN.
#
#   !!! ONLY WITHOUT THE PROPELLER, with the motor firmly fixed !!!
#
# Needs you at the bench: you hold the button to unlock, tap it to lock, and confirm
# what you see. The automatic suite (test_commands.py) never turns the motor; this one does,
# so it is a separate script you only run on purpose.
#
# The Nano locks the bench if it hears nothing for 1 s (heartbeat). While this script waits for
# you (questions, button), a background thread keeps sending PING (tc.start_heartbeat).
# It ALWAYS sends STOP at the end, even if a test fails or you press Ctrl+C.
# If anything looks wrong, tap the button (it always locks).
#
# Run (with the monitor CLOSED):
#   python3 tests/test_motor.py
#   python3 tests/test_motor.py /dev/ttyUSB1      (another port)

import os
import re
import sys
import time

import serial

# works both as "python3 tests/test_motor.py" and "python3 -m tests.test_motor"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests.test_commands as tc     # reuses wait_ready(), send(), read_line(), the heartbeat and the EVT list

PORT = tc.PORT
BAUD = tc.BAUD
UNLOCK_WAIT_S = 30             # same as UNLOCK_WAIT_MS on the Nano
UNLOCK_HOLD_S = 2              # same as UNLOCK_HOLD_MS on the Nano
READY_WAIT_S = 20              # waits for ESC_ARMING (3 s after a reset) and for you to zero the pot
TAP_WAIT_S = 15                # time to tap the button when asked
SERVER_SILENT_S = 1.5          # > SERVER_TIMEOUT_MS on the Nano (1 s): long enough to lock
SLOW = 8                       # % - slow (1080 us, the start pulse of esc_controller)
FAST = 15                      # % - a bit faster (1150 us)

results = []                   # (test name, passed)


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return ok


def ask(question):
    """Asks you to confirm what you see at the bench. Returns True for 's'/'y'."""
    answer = input(f"  >>> {question} [s/n] ").strip().lower()
    return answer in ("s", "sim", "y", "yes")


def reply(port, command):
    """Sends a command and returns its ONE reply line (or '' if none / too many)."""
    replies, _ = tc.send(port, command)
    if len(replies) != 1:
        print(f"      {command!r} -> {replies}  (expected exactly one line)")
        return ""
    print(f"      {command!r} -> {replies[0]}")
    return replies[0]


def wait_bench(port, pattern, seconds):
    """Asks BENCH every 200 ms until the reply matches 'pattern' (regex) or time runs out."""
    deadline = time.monotonic() + seconds
    line = ""
    while time.monotonic() < deadline:
        replies, _ = tc.send(port, "BENCH")
        line = replies[0] if replies else ""
        if re.fullmatch(pattern, line):
            return line
        time.sleep(0.2)
    return line


def wait_motor(port, test, seconds):
    """Asks MOTOR every 200 ms until test(percent) is True or time runs out. Returns the last %."""
    deadline = time.monotonic() + seconds
    percent = -1
    while time.monotonic() < deadline:
        replies, _ = tc.send(port, "MOTOR")
        m = re.fullmatch(r"OK MOTOR (\d+)", replies[0]) if replies else None
        if m:
            percent = int(m.group(1))
            if test(percent):
                return percent
        time.sleep(0.2)
    return percent


def request_unlock(port):
    """Sends UNLOCK until it is accepted. Returns True when the bench is UNLOCKING."""
    # Two problems fix themselves (or with your hand), so the script waits for them:
    #   ESC_ARMING   -> opening the port resets the Nano, which then waits 3 s for the ESC
    #   POT_NOT_ZERO -> you put the pot back to zero
    # Anything else (no battery, low voltage) stops the test at once.
    deadline = time.monotonic() + READY_WAIT_S
    asked_pot = False
    r = reply(port, "UNLOCK")
    while time.monotonic() < deadline:
        m = re.fullmatch(r"ERROR UNLOCK not ready:((?: \w+)+)", r)
        problems = set(m.group(1).split()) if m else set()
        if not problems or not problems <= {"ESC_ARMING", "POT_NOT_ZERO"}:
            break                                       # unlocked, or a problem we cannot wait for
        if "POT_NOT_ZERO" in problems and not asked_pot:
            print("  >>> Put the pot back to ZERO.")
            asked_pot = True
        time.sleep(0.5)
        r = reply(port, "UNLOCK")
    if not r.startswith("OK UNLOCK"):
        print("      The bench is not ready to unlock (see what is missing above).")
        return False
    return True


def unlock(port):
    """UNLOCK + you hold the button 2 s. Returns True when the bench is UNLOCKED."""
    if not request_unlock(port):
        return False
    print(f"  >>> HOLD THE BUTTON for 2 s (red LED blinking fast, then long beep). You have {UNLOCK_WAIT_S} s.")
    line = wait_bench(port, r"OK BENCH UNLOCKED", UNLOCK_WAIT_S + 2)
    return line == "OK BENCH UNLOCKED"


def run(port):
    # --- 0) start from a known, safe state, in SERVER mode (already the startup mode) ---
    reply(port, "STOP")
    check("MODE SERVER", reply(port, "MODE SERVER") == "OK MODE SERVER")
    check("starts LOCKED", reply(port, "BENCH").startswith("OK BENCH LOCKED"))
    check("motor at 0", reply(port, "MOTOR") == "OK MOTOR 0")
    bat = reply(port, "BAT")
    if not check("battery GOOD or WEAK", bool(re.fullmatch(r"OK BAT (GOOD|WEAK) .*", bat)), bat):
        print("Connect a charged battery to the ESC and try again.")
        return

    # --- 1) locked: MOTOR must be refused ---
    check("locked: MOTOR refused", reply(port, f"MOTOR {FAST}").startswith("ERROR MOTOR bench LOCKED"))
    check("locked: motor still 0", reply(port, "MOTOR") == "OK MOTOR 0")

    # --- 1b) a button ALREADY held when UNLOCK arrives must NOT unlock (stuck button) ---
    print("  >>> PRESS AND HOLD the button now (keep holding), then press Enter.")
    input("      (holding?) ")
    check("UNLOCK with the button already held", request_unlock(port))
    time.sleep(UNLOCK_HOLD_S + 1.5)
    check("held before UNLOCK: does NOT unlock", reply(port, "BENCH") == "OK BENCH UNLOCKING")
    print("  >>> RELEASE the button.")
    time.sleep(2)
    reply(port, "STOP")

    # --- 2) unlock with the button ---
    if not check("UNLOCK + button 2 s -> UNLOCKED", unlock(port)):
        return

    # --- 3) turn slowly, faster, stop ---
    tc.events.clear()
    check(f"MOTOR {SLOW}", reply(port, f"MOTOR {SLOW}") == f"OK MOTOR {SLOW}")
    check("motor turns slowly", ask("O motor está a rodar devagar?"))
    check(f"MOTOR {FAST}", reply(port, f"MOTOR {FAST}") == f"OK MOTOR {FAST}")
    check("motor turns faster", ask("Está a rodar mais depressa?"))
    pot_events = [e for e in tc.events if e.startswith("EVT POT")]
    check("no EVT POT while the motor turns (pot untouched)", not pot_events,
          f"{len(pot_events)} events: {pot_events[:5]}" if pot_events else "")
    check("MOTOR 0", reply(port, "MOTOR 0") == "OK MOTOR 0")
    check("motor stopped", ask("O motor parou?"))
    check("still UNLOCKED after MOTOR 0", reply(port, "BENCH") == "OK BENCH UNLOCKED")

    # --- 4) a tap on the button stops the motor and locks ---
    check(f"MOTOR {FAST} again", reply(port, f"MOTOR {FAST}") == f"OK MOTOR {FAST}")
    print(f"  >>> Now give ONE TAP on the button (short beep). You have {TAP_WAIT_S} s.")
    line = wait_bench(port, r"OK BENCH LOCKED.*", TAP_WAIT_S)
    check("tap -> LOCKED BUTTON", line == "OK BENCH LOCKED BUTTON", line)
    check("tap -> motor 0", reply(port, "MOTOR") == "OK MOTOR 0")
    check("motor stopped after the tap", ask("O motor parou com o toque?"))

    # --- 5) STOP stops the motor and locks ---
    if not check("unlock again", unlock(port)):
        return
    check(f"MOTOR {FAST} (for STOP)", reply(port, f"MOTOR {FAST}") == f"OK MOTOR {FAST}")
    time.sleep(1)
    check("STOP", reply(port, "STOP") == "OK STOP")
    check("STOP -> LOCKED STOP", reply(port, "BENCH") == "OK BENCH LOCKED STOP")
    check("STOP -> motor 0", reply(port, "MOTOR") == "OK MOTOR 0")
    check("motor stopped after STOP", ask("O motor parou com o STOP?"))

    # --- 5b) the server goes silent (heartbeat stops) with the motor turning: must lock ---
    if not check("unlock again (heartbeat)", unlock(port)):
        return
    check(f"MOTOR {FAST} (for the heartbeat)", reply(port, f"MOTOR {FAST}") == f"OK MOTOR {FAST}")
    print(f"  >>> The script goes SILENT for {SERVER_SILENT_S} s: the motor must stop (high beep).")
    tc.stop_heartbeat()
    time.sleep(SERVER_SILENT_S)
    tc.start_heartbeat(port)
    check("silent -> LOCKED SERVER_LOST", reply(port, "BENCH") == "OK BENCH LOCKED SERVER_LOST")
    check("silent -> motor 0", reply(port, "MOTOR") == "OK MOTOR 0")
    check("motor stopped when the server went silent", ask("O motor parou (e ouviu um apito agudo)?"))

    # --- 6) locked again: refused ---
    check("locked: MOTOR refused again", reply(port, f"MOTOR {FAST}").startswith("ERROR MOTOR bench LOCKED"))

    # --- 7) POT mode: the pot is the throttle ---
    print("\n  --- POT mode ---")
    check("MODE POT", reply(port, "MODE POT") == "OK MODE POT")
    print("  >>> Make sure the pot is at ZERO.")
    if not check("unlock in POT mode", unlock(port)):
        return
    check("unlocked: MODE refused", reply(port, "MODE SERVER").startswith("ERROR MODE bench UNLOCKED"))
    check("POT mode: MOTOR <n> refused", reply(port, f"MOTOR {FAST}") == "ERROR MOTOR mode POT")
    check("pot at zero: motor 0", reply(port, "MOTOR") == "OK MOTOR 0")
    print("  >>> Turn the pot SLOWLY until the motor turns (a little, not to the end). You have 15 s.")
    p = wait_motor(port, lambda x: x > 0, 15)
    check("pot moves the motor", p > 0, f"{p} %")
    check("motor turns with the pot", ask("O motor roda e acompanha o pot?"))
    print("  >>> Turn the pot back to ZERO. You have 15 s.")
    p = wait_motor(port, lambda x: x == 0, 15)
    check("pot at zero: motor 0 again", p == 0, f"{p} %")
    print(f"  >>> Now give ONE TAP on the button. You have {TAP_WAIT_S} s.")
    line = wait_bench(port, r"OK BENCH LOCKED.*", TAP_WAIT_S)
    check("POT mode: tap -> LOCKED BUTTON", line == "OK BENCH LOCKED BUTTON", line)


def main():
    print(__doc__ if __doc__ else "")
    print("!!! This test TURNS THE MOTOR. Remove the propeller and fix the motor firmly. !!!")
    if input("Hélice retirada e motor bem preso? Escreve SIM para continuar: ").strip() != "SIM":
        print("Cancelled.")
        return 2

    try:
        port = serial.Serial(PORT, BAUD, timeout=0.05)
    except serial.SerialException as e:
        print(f"Could not open {PORT}: {e}")
        print("Is the monitor (or the server) open? Close it and try again.")
        return 2

    print(f"Port {PORT} open. Waiting for READY...")
    if not tc.wait_ready(port):
        print("ERROR: the Nano did not say READY")
        return 2
    print("Nano READY.\n")

    tc.start_heartbeat(port)
    try:
        run(port)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        # ALWAYS leave the motor stopped and the bench locked
        tc.write(port, "STOP\n")
        time.sleep(0.2)
        tc.stop_heartbeat()
        port.close()
        print("STOP sent: motor at 0 %, bench locked.")

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
