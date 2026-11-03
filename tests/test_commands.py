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
import threading
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
BAUD = 115200            # same as SERIAL_SPEED in benchcode.ino
STARTUP_TIMEOUT = 5.0    # s waiting for READY (opening the port resets the Nano)
REPLY_TIMEOUT = 1.0      # s waiting for the reply to a command
SILENCE_TIME = 0.2       # s checking that no 2nd line arrives (rule: ONE reply)
HEARTBEAT_S = 0.25       # s: PING when nothing else was sent for this long (the Nano locks after 1 s)

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
    ("UNLOCK",              r"OK UNLOCK UNLOCKING|ERROR UNLOCK not ready:( (NO_BATTERY|ESC_ARMING|LOW_VOLTAGE|POT_NOT_ZERO|BATTERY_CUT|SERVER_LOST))+"),
    ("STOP",                r"OK STOP"),                         # cancels a pending UNLOCK
    ("BENCH",               r"OK BENCH LOCKED STOP"),            # UNLOCK alone never unlocks
    ("UNLOCK 1",            r"ERROR UNLOCK expects 0 values: UNLOCK"),

    # --- MODE: who controls the throttle. Starts in SERVER; changes only with the bench LOCKED ---
    ("STOP",                r"OK STOP"),
    ("MODE",                r"OK MODE SERVER"),                  # the startup mode
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

    # --- ESC: battery plugged into the ESC (D6) and armed (BAT_ARM_MS after plugging) ---
    ("ESC",                 r"OK ESC (NONE|ARMING|ARMED)"),
    ("ESC 1",               r"ERROR ESC expects 0 values: ESC"),

    # --- PING: the server's heartbeat (any line counts; PING is for when there is nothing else to say) ---
    ("PING",                r"OK PING"),
    ("PING 1",              r"ERROR PING expects 0 values: PING"),

    # --- HELP: list built from the table ---
    ("HELP",                r"OK POT TONE BENCH UNLOCK MOTOR MODE BAT ESC STOP PING HELP"),

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


# ---------------------------------------------------------------------------
# Writing + heartbeat
# The Nano locks the bench if it hears NOTHING for SERVER_TIMEOUT_MS (1 s). Scripts that wait
# (input(), sleep, plots) with the bench UNLOCKING/UNLOCKED call start_heartbeat(): a background
# thread sends PING whenever nothing else was sent for HEARTBEAT_S. Its "OK PING" replies are
# skipped by read_line(). ALL writes go through write(), so the two threads never mix lines.
# ---------------------------------------------------------------------------

_write_lock = threading.Lock()   # one writer at a time (and protects the 2 variables below)
_last_write = 0.0                # when the last line was sent
_pings_pending = 0               # heartbeat PINGs whose "OK PING" has not arrived yet
_longest_gap = 0.0               # longest time between two writes (to diagnose SERVER_LOST)
_hb_stop = threading.Event()
_hb_thread = None


def _sent():
    """Call with _write_lock held, right after a write: updates the silence bookkeeping."""
    global _last_write, _longest_gap
    now = time.monotonic()
    if _last_write:
        _longest_gap = max(_longest_gap, now - _last_write)
    _last_write = now


def longest_silence():
    """Longest time (s) between two lines sent so far. Above 1 s the Nano locks (SERVER_LOST)."""
    return _longest_gap


def write(port, text):
    """Sends text (one or more lines, each ending in \n). Safe to use with the heartbeat running."""
    with _write_lock:
        port.write(text.encode())
        _sent()


def _heartbeat(port):
    global _pings_pending
    while not _hb_stop.wait(0.05):
        with _write_lock:
            if time.monotonic() - _last_write >= HEARTBEAT_S:
                port.write(b"PING\n")
                _sent()
                _pings_pending += 1


def start_heartbeat(port):
    """Starts the background PING (does nothing if it is already running)."""
    global _hb_thread
    if _hb_thread is not None and _hb_thread.is_alive():
        return
    _hb_stop.clear()
    _hb_thread = threading.Thread(target=_heartbeat, args=(port,), daemon=True)
    _hb_thread.start()


def stop_heartbeat():
    """Stops the background PING. With the bench unlocked, the Nano locks 1 s later (SERVER_LOST)."""
    _hb_stop.set()
    if _hb_thread is not None:
        _hb_thread.join()


def _is_heartbeat_reply(line):
    """True (and counts it) if 'line' is the reply to one of the heartbeat's PINGs."""
    global _pings_pending
    with _write_lock:
        if line == "OK PING" and _pings_pending > 0:
            _pings_pending -= 1
            return True
        return False


def read_line(port, deadline):
    """Reads one non-empty line that is NOT an event (nor a heartbeat reply) until 'deadline'; None if none arrives in time."""
    while time.monotonic() < deadline:
        line = port.readline().decode("utf-8", errors="replace").strip()
        if line.startswith("EVT "):
            events.append(line)       # an event: keep it, but it is not a reply
            continue
        if _is_heartbeat_reply(line):
            continue                  # the heartbeat's own reply: not for us
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
    write(port, command + "\n")
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
    write(port, "TONE 0\nBENCH\n")
    r1 = read_line(port, time.monotonic() + REPLY_TIMEOUT)
    r2 = read_line(port, time.monotonic() + REPLY_TIMEOUT)
    ok = r1 == "OK TONE 0 0" and r2 is not None and r2.startswith("OK BENCH ")
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {'two lines at once':36} -> {r1} | {r2}")

    # Extra test: heartbeat. With the bench UNLOCKING, 1.5 s of silence must lock it (SERVER_LOST).
    # Needs the battery connected and the pot at zero; otherwise UNLOCK is refused and it is skipped.
    total = len(TESTS) + 2
    replies, _ = send(port, "UNLOCK")
    if replies == ["OK UNLOCK UNLOCKING"]:
        time.sleep(1.5)
        replies, _ = send(port, "BENCH")
        ok = replies == ["OK BENCH LOCKED CHECK SERVER_LOST"]
        failures += not ok
        total += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {'heartbeat: 1.5 s silent -> locks':36} -> {' | '.join(replies) or '-'}")
    else:
        print(f"[SKIP] {'heartbeat: 1.5 s silent -> locks':36} -> UNLOCK refused: {' | '.join(replies) or '-'}")
    send(port, "STOP")

    # Events: every EVT line must have the right format
    bad = [e for e in events if not re.fullmatch(r"EVT POT \d+|EVT ESC (NONE|ARMING|ARMED)|EVT BENCH (UNLOCKED|UNLOCKING|LOCKED( \w+)+)", e)]
    ok = not bad
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {'event format':36} -> {len(events)} events received"
          + (f", bad: {bad}" if bad else ""))

    port.close()
    print(f"\n{total - failures}/{total} tests passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
