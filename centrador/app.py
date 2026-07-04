from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, ttk

from .camera_discovery import CameraInfo, open_camera, scan_cameras
from .config import ConfigStore
from .detector import DetectionResult, PaperDetector
from .serial_controller import SerialController


class CenteringApp:
    def __init__(self, root: tk.Tk, config: ConfigStore, logger: logging.Logger, dry_run: bool = False):
        self.root = root
        self.config = config
        self.logger = logger.getChild("app")
        self.detector = PaperDetector(config)
        self.serial = SerialController(config, logger, dry_run=dry_run)
        self.capture: Optional[cv2.VideoCapture] = None
        self.running = True
        self.auto_enabled = bool(config.get("app.auto_start_enabled", False))
        self.last_pulse_time = 0.0
        self.pending_click: Optional[str] = None
        self.last_frame_bgr: Optional[np.ndarray] = None
        self.last_result: Optional[DetectionResult] = None
        self.photo_ref = None
        self.canvas_image_id = None
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.display_w = 960
        self.display_h = 540
        self.last_command = ""
        self.force_show_config = not self.auto_enabled
        self.camera_infos: list[CameraInfo] = []

        self._build_ui()
        self._bind_keys()
        self._open_camera()
        self.serial.open_if_needed()
        self.serial.set_enable(self.auto_enabled)
        self._set_auto_var()
        self._schedule_update()

    def _build_ui(self) -> None:
        self.root.title(str(self.config.get("app.title", "Centrador Corrugadora")))
        if bool(self.config.get("app.fullscreen", False)):
            self.root.attributes("-fullscreen", True)

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.main = ttk.Frame(self.root, padding=6)
        self.main.pack(fill=tk.BOTH, expand=True)

        self.left = ttk.Frame(self.main)
        self.left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.left, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.status_label = ttk.Label(self.left, text="Iniciando...", font=("Segoe UI", 12))
        self.status_label.pack(fill=tk.X, pady=(5, 0))

        self.panel = ttk.Frame(self.main, width=330)
        self.panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        title = ttk.Label(self.panel, text="Centrador", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w", pady=(0, 8))

        self.auto_var = tk.BooleanVar(value=self.auto_enabled)
        self.auto_check = ttk.Checkbutton(self.panel, text="AUTO habilitado", variable=self.auto_var, command=self._toggle_auto)
        self.auto_check.pack(anchor="w", pady=3)

        self.serial_var = tk.BooleanVar(value=bool(self.config.get("serial.enabled", True)))
        ttk.Checkbutton(self.panel, text="Usar Arduino/Serie", variable=self.serial_var, command=self._toggle_serial_enabled).pack(anchor="w", pady=3)

        ttk.Button(self.panel, text="STOP salidas", command=self._stop_outputs).pack(fill=tk.X, pady=4)
        ttk.Button(self.panel, text="Guardar configuración", command=self._save_config).pack(fill=tk.X, pady=4)
        ttk.Button(self.panel, text="Reabrir cámara", command=self._reopen_camera).pack(fill=tk.X, pady=4)

        ttk.Separator(self.panel).pack(fill=tk.X, pady=8)
        ttk.Label(self.panel, text="Cámara", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.active_camera_var = tk.StringVar(value="Activa: --")
        self.active_backend_var = tk.StringVar(value="Backend: --")
        ttk.Label(self.panel, textvariable=self.active_camera_var).pack(anchor="w")
        ttk.Label(self.panel, textvariable=self.active_backend_var).pack(anchor="w")
        self.camera_backend_combo = self._labeled_combo("Backend", "camera.backend", ["dshow", "msmf", "default"])
        self.camera_select = ttk.Combobox(self.panel, state="readonly", width=28)
        self.camera_select.pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="Buscar cámaras", command=self._scan_cameras).pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="Usar cámara seleccionada", command=self._use_selected_camera).pack(fill=tk.X, pady=2)
        self._refresh_camera_status_labels()

        ttk.Separator(self.panel).pack(fill=tk.X, pady=8)
        ttk.Label(self.panel, text="Calibración por click", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.panel, text="Tocá el botón y luego clic en la imagen.").pack(anchor="w")
        ttk.Button(self.panel, text="1) Click referencia izquierda", command=lambda: self._set_pending("left_reference_x")).pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="2) Click borde izquierdo papel", command=lambda: self._set_pending("ideal_left_edge_x")).pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="3) Click borde derecho papel", command=lambda: self._set_pending("ideal_right_edge_x")).pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="4) Click referencia derecha", command=lambda: self._set_pending("right_reference_x")).pack(fill=tk.X, pady=2)
        ttk.Button(self.panel, text="Usar centro actual como ideal", command=self._use_current_center_as_ideal).pack(fill=tk.X, pady=4)
        ttk.Button(self.panel, text="Recalcular centro ideal por bordes", command=self._recalc_ideal_center).pack(fill=tk.X, pady=2)

        ttk.Separator(self.panel).pack(fill=tk.X, pady=8)
        ttk.Label(self.panel, text="Ajustes rápidos", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        self.com_entry = self._labeled_entry("Puerto COM", "serial.port")
        self.tolerance_entry = self._labeled_entry("Tolerancia px", "control.tolerance_px")
        self.medium_entry = self._labeled_entry("Error medio px", "control.medium_error_px")
        self.pxmm_entry = self._labeled_entry("px por mm", "calibration.px_per_mm")
        self.roi_y1_entry = self._labeled_entry("ROI y1", "roi.y1")
        self.roi_y2_entry = self._labeled_entry("ROI y2", "roi.y2")
        ttk.Button(self.panel, text="Aplicar ajustes", command=self._apply_entries).pack(fill=tk.X, pady=4)

        ttk.Separator(self.panel).pack(fill=tk.X, pady=8)
        self.info_text = tk.Text(self.panel, height=14, width=42, wrap="word")
        self.info_text.pack(fill=tk.BOTH, expand=False)
        self.info_text.insert("1.0", "Esperando imagen...\n")
        self.info_text.configure(state="disabled")

        ttk.Label(self.panel, text="Teclas: A auto | S guardar | F fullscreen | ESC salir", font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))

    def _labeled_entry(self, label: str, dotted: str) -> ttk.Entry:
        frame = ttk.Frame(self.panel)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=16).pack(side=tk.LEFT)
        entry = ttk.Entry(frame, width=16)
        entry.insert(0, str(self.config.get(dotted, "")))
        entry.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        entry.dotted = dotted  # type: ignore[attr-defined]
        return entry

    def _labeled_combo(self, label: str, dotted: str, values: list[str]) -> ttk.Combobox:
        frame = ttk.Frame(self.panel)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=16).pack(side=tk.LEFT)
        combo = ttk.Combobox(frame, values=values, state="readonly", width=16)
        current = str(self.config.get(dotted, values[0]))
        combo.set(current if current in values else values[0])
        combo.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        combo.dotted = dotted  # type: ignore[attr-defined]
        return combo

    def _bind_keys(self) -> None:
        self.root.bind("<Escape>", lambda _e: self.shutdown())
        self.root.bind("a", lambda _e: self._toggle_auto_from_key())
        self.root.bind("A", lambda _e: self._toggle_auto_from_key())
        self.root.bind("s", lambda _e: self._save_config())
        self.root.bind("S", lambda _e: self._save_config())
        self.root.bind("f", lambda _e: self._toggle_fullscreen())
        self.root.bind("F", lambda _e: self._toggle_fullscreen())

    def _on_canvas_resize(self, event) -> None:
        self.display_w = max(320, int(event.width))
        self.display_h = max(240, int(event.height))

    def _open_camera(self) -> None:
        cam_index = int(self.config.get("camera.index", 0))
        backend = str(self.config.get("camera.backend", "dshow")).lower()
        self.capture = open_camera(cam_index, backend)
        if not self.capture.isOpened():
            self.logger.error("No se pudo abrir cámara index=%s backend=%s", cam_index, backend)
            self._refresh_camera_status_labels()
            return
        width = int(self.config.get("camera.width", 1280))
        height = int(self.config.get("camera.height", 720))
        fps = int(self.config.get("camera.fps", 30))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        autofocus = self.config.get("camera.autofocus")
        if autofocus is not None:
            self.capture.set(cv2.CAP_PROP_AUTOFOCUS, 1 if bool(autofocus) else 0)
        exposure = self.config.get("camera.exposure")
        if exposure is not None:
            self.capture.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
        gain = self.config.get("camera.gain")
        if gain is not None:
            self.capture.set(cv2.CAP_PROP_GAIN, float(gain))
        self.logger.info("Camara abierta index=%s backend=%s", cam_index, backend)
        self._refresh_camera_status_labels()

    def _reopen_camera(self) -> None:
        self._prepare_camera_change("Reabriendo cámara")
        self._reopen_camera_unsafe()

    def _reopen_camera_unsafe(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self._open_camera()

    def _prepare_camera_change(self, reason: str) -> None:
        if self.auto_enabled:
            self.auto_enabled = False
            self.auto_var.set(False)
            self.config.set("app.auto_start_enabled", False)
            self.serial.set_enable(False)
        self.serial.stop()
        self.last_command = f"STOP: {reason}"

    def _refresh_camera_status_labels(self) -> None:
        if not hasattr(self, "active_camera_var"):
            return
        index = int(self.config.get("camera.index", 0))
        backend = str(self.config.get("camera.backend", "dshow"))
        opened = self.capture is not None and self.capture.isOpened()
        status = "abierta" if opened else "sin imagen"
        self.active_camera_var.set(f"Activa: {index} ({status})")
        self.active_backend_var.set(f"Backend: {backend}")

    def _scan_cameras(self) -> None:
        backend = self.camera_backend_combo.get().strip() or str(self.config.get("camera.backend", "dshow"))
        self._prepare_camera_change("Buscando cámaras")
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.camera_select.configure(values=[])
        self.camera_select.set("Buscando...")
        self.root.update_idletasks()
        self.camera_infos = scan_cameras(max_index=8, backend=backend)
        labels = [info.label() for info in self.camera_infos]
        self.camera_select.configure(values=labels)
        current_index = int(self.config.get("camera.index", 0))
        selected = next((info.label() for info in self.camera_infos if info.index == current_index), labels[0] if labels else "")
        self.camera_select.set(selected)
        self._reopen_camera_unsafe()
        available_count = sum(1 for info in self.camera_infos if info.available)
        self.last_command = f"Cámaras encontradas: {available_count}"

    def _selected_camera_info(self) -> Optional[CameraInfo]:
        selected = self.camera_select.get().strip()
        for info in self.camera_infos:
            if info.label() == selected:
                return info
        if selected:
            try:
                index = int(selected.split("-", 1)[0].strip())
            except ValueError:
                return None
            return next((info for info in self.camera_infos if info.index == index), None)
        return None

    def _use_selected_camera(self) -> None:
        info = self._selected_camera_info()
        if info is None:
            messagebox.showwarning("Cámara", "Primero usá Buscar cámaras y elegí una opción de la lista.")
            return
        if not info.available:
            messagebox.showwarning("Cámara no disponible", f"La cámara {info.index} no está disponible. No se cambió la cámara activa.")
            return
        backend = self.camera_backend_combo.get().strip() or str(self.config.get("camera.backend", "dshow"))
        self._prepare_camera_change("Cambiando cámara")
        self.config.set("camera.index", int(info.index))
        self.config.set("camera.backend", backend)
        self._reopen_camera_unsafe()
        self.last_command = f"Cámara activa: {info.label()}"

    def _schedule_update(self) -> None:
        if self.running:
            interval = int(self.config.get("app.update_interval_ms", 40))
            self.root.after(max(10, interval), self._update)

    def _update(self) -> None:
        try:
            self._update_once()
        except Exception as exc:
            self.logger.exception("Error en update: %s", exc)
            self.status_label.configure(text=f"ERROR APP: {exc}")
        finally:
            self._schedule_update()

    def _update_once(self) -> None:
        frame = self._read_frame()
        if frame is None:
            self.status_label.configure(text="SIN CÁMARA / SIN IMAGEN")
            self._update_info(None)
            return
        self.last_frame_bgr = frame
        self.detector.update_config(self.config)
        result = self.detector.detect(frame)
        self.last_result = result
        self._control_step(result)
        overlay = self._draw_overlay(frame.copy(), result)
        self._show_frame(overlay)
        self._update_status(result)
        self._update_info(result)
        self.serial.heartbeat_if_due(self.auto_enabled)

    def _read_frame(self) -> Optional[np.ndarray]:
        if self.capture is None or not self.capture.isOpened():
            self._open_camera()
            return None
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return None
        if bool(self.config.get("camera.flip_horizontal", False)):
            frame = cv2.flip(frame, 1)
        if bool(self.config.get("camera.flip_vertical", False)):
            frame = cv2.flip(frame, 0)
        if bool(self.config.get("camera.rotate_180", False)):
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def _control_step(self, result: DetectionResult) -> None:
        self.serial.open_if_needed()
        serial_ok = self.serial.is_connected()
        require_serial = bool(self.config.get("control.require_serial_ok_for_auto", True))
        if self.auto_enabled and require_serial and not serial_ok:
            self.last_command = "AUTO bloqueado: serie no conectada"
            return
        if not self.auto_enabled:
            return
        if not result.valid:
            self.last_command = f"FAULT: {result.fault}"
            if bool(self.config.get("control.stop_on_fault", True)):
                self.serial.stop()
            return
        if result.error_px is None:
            return
        now = time.monotonic()
        cooldown = float(self.config.get("control.cooldown_ms", 500)) / 1000.0
        if now - self.last_pulse_time < cooldown:
            return

        error = float(result.error_px)
        tolerance = float(self.config.get("control.tolerance_px", 18))
        if abs(error) <= tolerance:
            self.last_command = "Dentro de tolerancia"
            return

        medium = float(self.config.get("control.medium_error_px", 60))
        ms = int(self.config.get("control.pulse_small_ms", 100)) if abs(error) <= medium else int(self.config.get("control.pulse_large_ms", 250))
        invert = bool(self.config.get("control.invert_correction", False))

        # error positivo = centro del papel a la derecha del ideal -> corregir hacia izquierda.
        if error > 0:
            direction = "RIGHT" if invert else "LEFT"
        else:
            direction = "LEFT" if invert else "RIGHT"

        if self.serial.pulse(direction, ms):
            self.last_pulse_time = now
            self.last_command = f"PULSO {direction} {ms} ms"
            self.logger.info("%s | error_px=%.1f error_mm=%s", self.last_command, error, result.error_mm)
        else:
            self.last_command = "No se pudo enviar pulso"

    def _draw_overlay(self, frame: np.ndarray, result: DetectionResult) -> np.ndarray:
        h, w = frame.shape[:2]
        x1, x2, y1, y2 = result.roi
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), (255, 255, 0), 2)

        def vline(x: Optional[float], color, label: str, thickness: int = 2):
            if x is None:
                return
            xi = int(round(x))
            cv2.line(frame, (xi, 0), (xi, h - 1), color, thickness)
            cv2.putText(frame, label, (max(5, xi + 5), 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        vline(self.config.get("calibration.left_reference_x"), (0, 255, 255), "REF IZQ", 2)
        vline(self.config.get("calibration.right_reference_x"), (0, 255, 255), "REF DER", 2)
        vline(self.config.get("calibration.ideal_left_edge_x"), (180, 180, 180), "BORDE IZQ IDEAL", 1)
        vline(self.config.get("calibration.ideal_right_edge_x"), (180, 180, 180), "BORDE DER IDEAL", 1)
        vline(result.ideal_center_x, (255, 0, 255), "CENTRO IDEAL", 2)
        vline(result.left_edge_x, (0, 255, 0) if result.valid else (0, 0, 255), "BORDE IZQ", 3)
        vline(result.right_edge_x, (0, 255, 0) if result.valid else (0, 0, 255), "BORDE DER", 3)
        vline(result.paper_center_x, (255, 0, 0), "CENTRO PAPEL", 2)

        auto_text = "AUTO ON" if self.auto_enabled else "AUTO OFF"
        valid_text = "VISION OK" if result.valid else f"FAULT {result.fault}"
        cv2.rectangle(frame, (5, h - 90), (min(w - 5, 760), h - 5), (0, 0, 0), -1)
        cv2.putText(frame, f"{auto_text} | {valid_text}", (15, h - 62), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        err = "--" if result.error_px is None else f"{result.error_px:.1f}px / {result.error_mm:.2f}mm"
        cv2.putText(frame, f"Error: {err} | Cmd: {self.last_command}", (15, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        if self.pending_click:
            cv2.putText(frame, f"CLICK para setear: {self.pending_click}", (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 255), 2, cv2.LINE_AA)
        return frame

    def _show_frame(self, frame_bgr: np.ndarray) -> None:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        canvas_w = max(320, self.display_w)
        canvas_h = max(240, self.display_h)
        scale = min(canvas_w / w, canvas_h / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        self.scale_x = w / new_w
        self.scale_y = h / new_h
        image = Image.fromarray(frame_rgb).resize((new_w, new_h), Image.Resampling.BILINEAR)
        self.photo_ref = ImageTk.PhotoImage(image=image)
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo_ref)

    def _update_status(self, result: DetectionResult) -> None:
        serial_status = self.serial.status()
        serial_txt = "DRY" if serial_status.dry_run else ("OK" if serial_status.connected else f"NO {serial_status.port}")
        err = "--" if result.error_px is None else f"{result.error_px:.1f}px / {result.error_mm:.2f}mm"
        self.status_label.configure(text=f"AUTO={'ON' if self.auto_enabled else 'OFF'} | SERIE={serial_txt} | VISION={'OK' if result.valid else result.fault} | ERROR={err} | {self.last_command}")

    def _update_info(self, result: Optional[DetectionResult]) -> None:
        serial_status = self.serial.status()
        lines = [
            f"Puerto serie: {serial_status.port}",
            f"Serie conectada: {serial_status.connected}",
            f"Dry-run: {serial_status.dry_run}",
            f"Ultimo error serie: {serial_status.last_error or '-'}",
            "",
        ]
        if result is not None:
            lines += [
                f"Vision valida: {result.valid}",
                f"Falla: {result.fault or '-'}",
                f"Borde izq: {result.left_edge_x}",
                f"Borde der: {result.right_edge_x}",
                f"Centro papel: {None if result.paper_center_x is None else round(result.paper_center_x, 1)}",
                f"Centro ideal: {round(result.ideal_center_x, 1)}",
                f"Error px: {None if result.error_px is None else round(result.error_px, 2)}",
                f"Error mm: {None if result.error_mm is None else round(result.error_mm, 2)}",
                f"Ancho px: {result.paper_width_px}",
                f"Conf izq/der: {result.left_confidence:.2f} / {result.right_confidence:.2f}",
                f"No papel frames: {result.no_paper_counter}",
                f"Ref OK izq/der: {result.left_ref_ok} / {result.right_ref_ok}",
                f"Ultimo comando: {self.last_command}",
            ]
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", "\n".join(lines))
        self.info_text.configure(state="disabled")

    def _toggle_auto_from_key(self) -> None:
        self.auto_var.set(not self.auto_var.get())
        self._toggle_auto()

    def _toggle_auto(self) -> None:
        desired = bool(self.auto_var.get())
        if desired and bool(self.config.get("control.require_serial_ok_for_auto", True)) and not self.serial.is_connected():
            self.serial.open_if_needed()
            if not self.serial.is_connected():
                self.auto_var.set(False)
                self.auto_enabled = False
                messagebox.showwarning("Serie no conectada", "No habilité AUTO porque no está conectado el Arduino. Usá dry-run para probar sin Arduino.")
                return
        self.auto_enabled = desired
        self.config.set("app.auto_start_enabled", bool(self.auto_enabled))
        self.serial.set_enable(self.auto_enabled)
        if not self.auto_enabled:
            self.serial.stop()
        self.logger.info("AUTO=%s", self.auto_enabled)

    def _set_auto_var(self) -> None:
        self.auto_var.set(self.auto_enabled)

    def _toggle_serial_enabled(self) -> None:
        enabled = bool(self.serial_var.get())
        self.config.set("serial.enabled", enabled)
        self.serial.update_config(self.config)
        if not enabled:
            self.serial.stop()
            self.serial.close()

    def _stop_outputs(self) -> None:
        self.last_command = "STOP manual"
        self.serial.stop()

    def _set_pending(self, key: str) -> None:
        self.pending_click = key

    def _on_canvas_click(self, event) -> None:
        if not self.pending_click:
            return
        if self.last_frame_bgr is None:
            return
        x_img = int(event.x * self.scale_x)
        h, w = self.last_frame_bgr.shape[:2]
        x_img = max(0, min(w - 1, x_img))
        self.config.set(f"calibration.{self.pending_click}", int(x_img))
        self.logger.info("Calibrado %s=%s", self.pending_click, x_img)
        self.pending_click = None
        self._recalc_ideal_center(save=False)

    def _use_current_center_as_ideal(self) -> None:
        if self.last_result is None or self.last_result.paper_center_x is None:
            messagebox.showwarning("Sin detección", "No hay centro de papel válido para usar como ideal.")
            return
        self.config.set("calibration.ideal_center_x", float(self.last_result.paper_center_x))
        self.logger.info("Centro ideal actual=%.2f", self.last_result.paper_center_x)

    def _recalc_ideal_center(self, save: bool = False) -> None:
        left = float(self.config.get("calibration.ideal_left_edge_x"))
        right = float(self.config.get("calibration.ideal_right_edge_x"))
        self.config.set("calibration.ideal_center_x", (left + right) / 2.0)
        if save:
            self._save_config()

    def _apply_entries(self) -> None:
        old_backend = str(self.config.get("camera.backend", "dshow"))
        entries = [self.com_entry, self.camera_backend_combo, self.tolerance_entry, self.medium_entry, self.pxmm_entry, self.roi_y1_entry, self.roi_y2_entry]
        for e in entries:
            dotted = e.dotted  # type: ignore[attr-defined]
            raw = e.get().strip()
            old = self.config.get(dotted)
            try:
                if isinstance(old, bool):
                    value = raw.lower() in ("1", "true", "si", "sí", "yes", "on")
                elif isinstance(old, int):
                    value = int(float(raw))
                elif isinstance(old, float):
                    value = float(raw)
                else:
                    value = raw
                self.config.set(dotted, value)
            except ValueError:
                messagebox.showwarning("Valor inválido", f"No pude aplicar {dotted}={raw}")
                return
        self.serial.update_config(self.config)
        self.detector.update_config(self.config)
        if str(self.config.get("camera.backend", "dshow")) != old_backend:
            self._reopen_camera()
        else:
            self._refresh_camera_status_labels()
        self.serial.close()
        self.serial.open_if_needed()

    def _save_config(self) -> None:
        self._apply_entries_silent()
        self.config.save()
        self.logger.info("Configuración guardada en %s", self.config.path)
        self.last_command = "Configuración guardada"

    def _apply_entries_silent(self) -> None:
        entries = [self.com_entry, self.camera_backend_combo, self.tolerance_entry, self.medium_entry, self.pxmm_entry, self.roi_y1_entry, self.roi_y2_entry]
        for e in entries:
            dotted = e.dotted  # type: ignore[attr-defined]
            raw = e.get().strip()
            old = self.config.get(dotted)
            try:
                if isinstance(old, bool):
                    value = raw.lower() in ("1", "true", "si", "sí", "yes", "on")
                elif isinstance(old, int):
                    value = int(float(raw))
                elif isinstance(old, float):
                    value = float(raw)
                else:
                    value = raw
                self.config.set(dotted, value)
            except ValueError:
                pass

    def _toggle_fullscreen(self) -> None:
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not current)

    def shutdown(self) -> None:
        self.running = False
        try:
            self.serial.set_enable(False)
            self.serial.stop()
            self.serial.close()
        except Exception:
            pass
        try:
            if self.capture is not None:
                self.capture.release()
        except Exception:
            pass
        self.root.destroy()


def run_app(config_path: Path, logger: logging.Logger, dry_run: bool = False) -> None:
    config = ConfigStore.load(config_path)
    root = tk.Tk()
    app = CenteringApp(root, config, logger, dry_run=dry_run)
    root.mainloop()
