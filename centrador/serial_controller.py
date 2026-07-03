from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

try:
    import serial
    from serial import SerialException
except Exception:  # pragma: no cover - permite abrir la app sin pyserial instalado
    serial = None
    SerialException = Exception

from .config import ConfigStore


@dataclass
class SerialStatus:
    enabled: bool
    connected: bool
    port: str
    last_error: Optional[str]
    dry_run: bool


class SerialController:
    def __init__(self, config: ConfigStore, logger: logging.Logger, dry_run: bool = False):
        self.config = config
        self.logger = logger.getChild("serial")
        self.dry_run = dry_run
        self.ser = None
        self.last_connect_attempt = 0.0
        self.last_heartbeat = 0.0
        self.last_error: Optional[str] = None
        self.enabled = bool(config.get("serial.enabled", True))

    def update_config(self, config: ConfigStore) -> None:
        self.config = config
        self.enabled = bool(config.get("serial.enabled", True))

    def open_if_needed(self) -> None:
        if self.dry_run or not self.enabled:
            return
        if self.ser is not None and getattr(self.ser, "is_open", False):
            return
        if serial is None:
            self.last_error = "pyserial_no_instalado"
            return
        now = time.monotonic()
        reconnect_every = float(self.config.get("serial.reconnect_every_s", 3.0))
        if now - self.last_connect_attempt < reconnect_every:
            return
        self.last_connect_attempt = now
        port = str(self.config.get("serial.port", "COM3"))
        baud = int(self.config.get("serial.baudrate", 115200))
        timeout = float(self.config.get("serial.timeout_s", 0.2))
        try:
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout, write_timeout=timeout)
            time.sleep(2.0)  # Arduino UNO reinicia al abrir puerto USB.
            self.last_error = None
            self.logger.info("Puerto serie conectado: %s @ %s", port, baud)
            startup = self.config.get("serial.startup_command", "ENABLE 0")
            if startup:
                self.send_line(str(startup))
        except SerialException as exc:
            self.last_error = str(exc)
            self.ser = None
            self.logger.warning("No se pudo abrir puerto serie %s: %s", port, exc)

    def close(self) -> None:
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def status(self) -> SerialStatus:
        return SerialStatus(
            enabled=self.enabled,
            connected=self.is_connected(),
            port=str(self.config.get("serial.port", "COM3")),
            last_error=self.last_error,
            dry_run=self.dry_run,
        )

    def is_connected(self) -> bool:
        if self.dry_run:
            return True
        return self.ser is not None and bool(getattr(self.ser, "is_open", False))

    def send_line(self, line: str) -> bool:
        if self.dry_run:
            self.logger.info("DRY-RUN serial: %s", line)
            return True
        self.open_if_needed()
        if not self.is_connected():
            return False
        try:
            payload = (line.strip() + "\n").encode("ascii", errors="ignore")
            self.ser.write(payload)
            self.ser.flush()
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.warning("Error enviando serie: %s", exc)
            self.close()
            return False

    def heartbeat_if_due(self, auto_enabled: bool) -> None:
        now = time.monotonic()
        interval = float(self.config.get("serial.heartbeat_interval_s", 1.0))
        if now - self.last_heartbeat >= interval:
            self.last_heartbeat = now
            if auto_enabled:
                self.send_line("HB")

    def set_enable(self, enabled: bool) -> bool:
        return self.send_line("ENABLE 1" if enabled else "ENABLE 0")

    def stop(self) -> bool:
        return self.send_line("STOP")

    def pulse(self, direction: str, ms: int) -> bool:
        max_ms = int(self.config.get("control.max_pulse_ms", 800))
        ms = max(10, min(int(ms), max_ms))
        d = direction.upper()
        if d in ("LEFT", "IZQUIERDA", "L"):
            cmd = f"PULSE L {ms}"
        elif d in ("RIGHT", "DERECHA", "R"):
            cmd = f"PULSE R {ms}"
        else:
            raise ValueError(f"Direccion invalida: {direction}")
        return self.send_line(cmd)
