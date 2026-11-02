#!/usr/bin/env python3
# Automatic tests for the commands in benchcode.ino (inputReader + commands).
#
# Sends each command to the Nano, reads the reply and compares it with the expected one.
# Protocol rule that is also tested: every command gets EXACTLY one reply line.
# Lines starting with "EVT" are events the Nano sends on its own (e.g. EVT POT 157):
# they are not replies, so they are counted and skipped.
#
# Run (with the monitor CLOSED, the port can only be used by one program):
#   python3 test_commands.py
#   python3 test_commands.py /dev/ttyUSB1      (another port)

import re
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
BAUD = 115200            # same as SERIAL_SPEED in benchcode.ino
STARTUP_TIMEOUT = 5.0    # s waiting for READY (opening the port resets the Nano)
REPLY_TIMEOUT = 1.0      # s waiting for the reply to a command
SILENCE_TIME = 0.2       # s checking that no 2nd line arrives (rule: ONE reply)

# (command sent, expected reply)
# The expected reply is a regular expression that must match the WHOLE line.
# E.g.: r"OK POT \d+" accepts "OK POT 523" (\d+ = one or more digits).
TESTS = [
    # --- POT ---
    ("POT",                 r"OK POT \d+"),
    ("POT 3",               r"ERROR POT expects 0 values: POT"),

    # --- TONE: <freq> [ms]; ms 0 or none = until TONE 0 / STOP ---
    ("TONE 2000 200",       r"OK TONE 2000 200"),
    ("TONE 1000",           r"OK TONE 1000 0"),                  # plays until stopped
    ("TONE 0",              r"OK TONE 0 0"),                     # stops
    ("TONE 0 500",          r"OK TONE 0 0"),                     # 0 Hz = stop, the ms is ignored
    ("TONE",                r"ERROR TONE expects 1 to 2 values: TONE <freq> \[ms\]"),
    ("TONE 1000 200 5",     r"ERROR TONE expects 1 to 2 values: TONE <freq> \[ms\]"),
    ("TONE abc",            r"ERROR TONE invalid value: abc"),
    ("TONE 12x",            r"ERROR TONE invalid value: 12x"),   # strtol catches the junk at the end
    ("TONE 30",             r"ERROR TONE invalid value: 30"),    # below TONE_MIN_HZ (31)
    ("TONE 10001",          r"ERROR TONE invalid value: 10001"), # above TONE_MAX_HZ
    ("TONE -5",             r"ERROR TONE invalid value: -5"),
    ("TONE 2000 -5",        r"ERROR TONE invalid value: -5"),
    ("TONE 2000 10001",     r"ERROR TONE invalid value: 10001"), # above TONE_MAX_MS
    ("TONE 2000 abc",       r"ERROR TONE invalid value: abc"),

    # --- STOP: makes everything safe (motor signal to minimum, buzzer off) ---
    ("TONE 1000",           r"OK TONE 1000 0"),
    ("STOP",                r"OK STOP"),                         # must silence the buzzer too
    ("STOP 1",              r"ERROR STOP expects 0 values: STOP"),

    # --- BENCH / UNLOCK (the script cannot press the button: hold 2 s / tap is tested by hand) ---
    ("BENCH",               r"OK BENCH LOCKED (STARTUP|STOP)"),  # never unlocked so far
    ("STOP",                r"OK STOP"),
    ("BENCH",               r"OK BENCH LOCKED STOP"),            # STOP locks, and says so
    ("BENCH 1",             r"ERROR BENCH expects 0 values: BENCH"),
    ("UNLOCK",              r"OK UNLOCK UNLOCKING|ERROR UNLOCK not ready:( (NO_BATTERY|ESC_ARMING|LOW_VOLTAGE|POT_NOT_ZERO|BATTERY_CUT))+"),
    ("STOP",                r"OK STOP"),                         # cancels a pending UNLOCK
    ("BENCH",               r"OK BENCH LOCKED STOP"),            # UNLOCK alone never unlocks
    ("UNLOCK 1",            r"ERROR UNLOCK expects 0 values: UNLOCK"),

    # --- MODE: who controls the throttle. Starts in POT; changes only with the bench LOCKED ---
    ("STOP",                r"OK STOP"),
    ("MODE",                r"OK MODE (POT|SERVER)"),
    ("MODE POT",            r"OK MODE POT"),
    ("MOTOR 10",            r"ERROR MOTOR mode POT"),            # POT mode: the pot is in charge
    ("MOTOR 0",             r"ERROR MOTOR mode POT"),
    ("MOTOR",               r"OK MOTOR 0"),                      # reading works in both modes
    ("MODE XPTO",           r"ERROR MODE invalid value: XPTO"),
    ("MODE pot",            r"ERROR MODE invalid value: pot"),   # UPPERCASE only
    ("MODE POT SERVER",     r"ERROR MODE expects 0 to 1 values: MODE \[POT\|SERVER\]"),
    ("MODE SERVER",         r"OK MODE SERVER"),
    ("MODE",                r"OK MODE SERVER"),

    # --- MOTOR (SERVER mode): the bench is LOCKED here (after STOP), so the motor must NEVER move ---
    # (turning the motor is tested by hand: UNLOCK + button 2 s, WITHOUT the propeller)
    ("STOP",                r"OK STOP"),
    ("MOTOR",               r"OK MOTOR 0"),                      # reads: stopped
    ("MOTOR 0",             r"OK MOTOR 0"),                      # 0 is always accepted
    ("MOTOR 10",            r"ERROR MOTOR bench LOCKED STOP"),   # locked: refused
    ("MOTOR",               r"OK MOTOR 0"),                      # ...and it did not move
    ("MOTOR 51",            r"ERROR MOTOR invalid value: 51"),   # above MOTOR_MAX_PERCENT (50)
    ("MOTOR 100",           r"ERROR MOTOR invalid value: 100"),
    ("MOTOR -1",            r"ERROR MOTOR invalid value: -1"),
    ("MOTOR abc",           r"ERROR MOTOR invalid value: abc"),
    ("MOTOR 10.5",          r"ERROR MOTOR invalid value: 10.5"), # whole percentages only
    ("MOTOR 1 2",           r"ERROR MOTOR expects 0 to 1 values: MOTOR \[0\.\.100\]"),

    # --- BAT: <NONE|GOOD|WEAK|LOW> <volts>V ---
    ("BAT",                 r"OK BAT (NONE|GOOD|WEAK|LOW) \d+\.\d\dV"),
    ("BAT 1",               r"ERROR BAT expects 0 values: BAT"),

    # --- HELP: list built from the table ---
    ("HELP",                r"OK POT TONE BENCH UNLOCK MOTOR MODE BAT STOP HELP"),

    # --- unknown commands (including the old format) ---
    ("XPTO 1",              r"ERROR unknown command: XPTO"),
    ("led 1",               r"ERROR unknown command: led"),      # names are UPPERCASE
    ("/cmd LED 1",          r"ERROR unknown command: /cmd"),
    ("LED 1",               r"ERROR unknown command: LED"),      # removed: the yellow LED belongs to the battery

    # --- line format (parseInput) ---
    ("",                    r"ERROR empty command.*"),
    ("   TONE   0   ",      r"OK TONE 0 0"),                     # extra spaces change nothing
    ("X 1 2 3 4 5 6 7 8 9 10 11", r"ERROR more than 10 values"),

    # --- leave everything safe at the end ---
    ("STOP",                r"OK STOP"),
]


events = []   # every EVT line received (not replies)


def read_line(port, deadline):
    """Reads one non-empty line that is NOT an event until 'deadline'; None if none arrives in time."""
    while time.monotonic() < deadline:
        line = port.readline().decode("utf-8", errors="replace").strip()
        if line.startswith("EVT "):
            events.append(line)       # an event: keep it, but it is not a reply
            continue
        if line:
            return line
    return None


def wait_ready(port):
    """Ignores everything (USB chip noise, header) until the Nano says READY."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        line = read_line(port, deadline)
        if line is None:
            return False
        if line == "READY":
            return True


def send(port, command):
    """Sends ONE line. Returns (lines received, ms until the 1st line arrived)."""
    start = time.monotonic()
    port.write((command + "\n").encode())
    first = read_line(port, start + REPLY_TIMEOUT)
    ms = (time.monotonic() - start) * 1000      # round-trip time: stops when the reply arrives
    if first is None:
        return [], ms
    replies = [first]
    # Wait a bit longer to catch EXTRA lines (they break the one-reply rule)
    while True:
        extra = read_line(port, time.monotonic() + SILENCE_TIME)
        if extra is None:
            return replies, ms
        replies.append(extra)


def main():
    try:
        port = serial.Serial(PORT, BAUD, timeout=0.05)
    except serial.SerialException as e:
        print(f"Could not open {PORT}: {e}")
        print("Is the monitor (or the server) open? Close it and try again.")
        return 2

    print(f"Port {PORT} open. Waiting for READY...")
    if not wait_ready(port):
        print("ERROR: the Nano did not say READY (wrong sketch? wrong speed?)")
        return 2
    print("Nano READY.\n")

    failures = 0
    for command, expected in TESTS:
        replies, ms = send(port, command)

        if not replies:
            ok, reason = False, "no reply"
        elif len(replies) > 1:
            ok, reason = False, f"{len(replies)} lines (should be 1)"
        elif not re.fullmatch(expected, replies[0]):
            ok, reason = False, f"expected /{expected}/"
        else:
            ok, reason = True, ""

        failures += not ok
        mark = "PASS" if ok else "FAIL"
        reply = " | ".join(replies) if replies else "-"
        print(f"[{mark}] {command!r:36} -> {reply}  ({ms:.0f} ms)")
        if not ok:
            print(f"       reason: {reason}")

    # Extra test: two lines sent at once -> two replies, in the right order
    port.write(b"TONE 0\nBENCH\n")
    r1 = read_line(port, time.monotonic() + REPLY_TIMEOUT)
    r2 = read_line(port, time.monotonic() + REPLY_TIMEOUT)
    ok = r1 == "OK TONE 0 0" and r2 is not None and r2.startswith("OK BENCH ")
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {'two lines at once':36} -> {r1} | {r2}")

    # Events: every EVT line must have the right format
    bad = [e for e in events if not re.fullmatch(r"EVT POT \d+", e)]
    ok = not bad
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {'event format':36} -> {len(events)} events received"
          + (f", bad: {bad}" if bad else ""))

    port.close()
    total = len(TESTS) + 2
    print(f"\n{total - failures}/{total} tests passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
