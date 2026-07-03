from __future__ import annotations

import argparse
import time
import serial


def send(ser: serial.Serial, line: str) -> None:
    print(">", line)
    ser.write((line.strip() + "\n").encode("ascii"))
    ser.flush()
    time.sleep(0.2)
    while ser.in_waiting:
        print("<", ser.readline().decode(errors="ignore").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba manual del protocolo con Arduino UNO.")
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        print("Esperando reinicio Arduino...")
        time.sleep(2)
        send(ser, "PING")
        send(ser, "ENABLE 1")
        send(ser, "HB")
        send(ser, "PULSE L 100")
        time.sleep(1)
        send(ser, "HB")
        send(ser, "PULSE R 100")
        time.sleep(1)
        send(ser, "STOP")
        send(ser, "ENABLE 0")
    print("Listo")


if __name__ == "__main__":
    main()
