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
from .windows_startup import disable_startup, enable_startup, restart_to_uefi, startup_status


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
        self.output_direction: Optional[str] = None
        self.output_until = 0.0
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
        self.root.configure(bg="#0b1117")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 24))
        if bool(self.config.get("app.fullscreen", False)):
            self.root.attributes("-fullscreen", True)

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.hmi_font = ("Segoe UI", 20, "bold")
        self.hmi_big_font = ("Segoe UI", 30, "bold")
        self.hmi_value_font = ("Segoe UI", 24, "bold")
        self.hmi_small_font = ("Segoe UI", 16)
        self.config_value_vars: dict[str, tk.StringVar] = {}
        self.config_widgets: dict[str, tk.Widget] = {}

        self.main = tk.Frame(self.root, bg="#0b1117", padx=10, pady=10)
        self.main.pack(fill=tk.BOTH, expand=True)

        self.left = tk.Frame(self.main, bg="#0b1117")
        self.left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_status = tk.Frame(self.left, bg="#0b1117")
        top_status.pack(fill=tk.X, pady=(0, 10))
        self.state_badge = tk.Label(top_status, text="INICIANDO", font=self.hmi_big_font, fg="#ffffff", bg="#64748b", padx=20, pady=12)
        self.state_badge.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.mode_badge = tk.Label(top_status, text="AUTO OFF", font=self.hmi_value_font, fg="#ffffff", bg="#2563eb", padx=18, pady=12)
        self.mode_badge.pack(side=tk.LEFT, padx=(0, 8))
        self.camera_badge = tk.Label(top_status, text="CAM --", font=self.hmi_value_font, fg="#ffffff", bg="#334155", padx=18, pady=12)
        self.camera_badge.pack(side=tk.LEFT)

        self.canvas = tk.Canvas(self.left, bg="black", highlightthickness=3, highlightbackground="#233142")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.status_label = tk.Label(self.left, text="Iniciando...", font=self.hmi_small_font, fg="#dbeafe", bg="#17212e", anchor="w", padx=14, pady=10)

        self.panel = tk.Frame(self.main, bg="#111827", width=340, padx=10, pady=10)
        self.panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.panel.pack_propagate(False)

        title = tk.Label(self.panel, text="CENTRADOR", font=("Segoe UI", 28, "bold"), fg="#e5e7eb", bg="#111827")
        title.pack(fill=tk.X, pady=(0, 10))

        self.auto_var = tk.BooleanVar(value=self.auto_enabled)
        self.serial_var = tk.BooleanVar(value=bool(self.config.get("serial.enabled", True)))
        action_grid = tk.Frame(self.panel, bg="#111827")
        action_grid.pack(fill=tk.X)
        for col in range(2):
            action_grid.columnconfigure(col, weight=1)
        self.auto_button = self._hmi_button(action_grid, "AUTO: OFF", self._toggle_auto_button, "blue")
        self.auto_button.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._hmi_button(action_grid, "STOP", self._stop_outputs, "red").grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self._hmi_button(action_grid, "CONFIG", self._open_config_window, "blue").grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._hmi_button(action_grid, "SALIR", self._confirm_shutdown, "red").grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

        direction_box = tk.Frame(self.panel, bg="#111827")
        direction_box.pack(fill=tk.X, pady=8)
        direction_box.columnconfigure(0, weight=1)
        direction_box.columnconfigure(1, weight=1)
        self.left_output_label = tk.Label(direction_box, text="IZQ\nOFF", font=self.hmi_value_font, fg="#94a3b8", bg="#1f2937", padx=12, pady=18)
        self.left_output_label.grid(row=0, column=0, sticky="nsew", padx=4)
        self.right_output_label = tk.Label(direction_box, text="DER\nOFF", font=self.hmi_value_font, fg="#94a3b8", bg="#1f2937", padx=12, pady=18)
        self.right_output_label.grid(row=0, column=1, sticky="nsew", padx=4)

        self.active_camera_var = tk.StringVar(value="Activa: --")
        self.active_backend_var = tk.StringVar(value="Backend: --")
        self._refresh_camera_status_labels()

        self.summary_var = tk.StringVar(value="Esperando imagen...")
        tk.Label(self.panel, textvariable=self.summary_var, font=("Segoe UI", 17), fg="#dbeafe", bg="#17212e", justify=tk.LEFT, anchor="nw", padx=14, pady=12, wraplength=300).pack(fill=tk.BOTH, expand=True, pady=8)

        self.windows_startup_status_var = tk.StringVar(value="Inicio con Windows: --")
        self.windows_startup_var = tk.BooleanVar(value=False)
        self._refresh_windows_startup_status()

    def _config_sections(self) -> list[tuple[str, list[tuple[str, str, str]]]]:
        return [
            ("Operacion", [("Puerto COM", "serial.port", "text"), ("Usar Arduino/Serie", "serial.enabled", "bool"), ("AUTO al abrir", "app.auto_start_enabled", "bool"), ("Pantalla completa", "app.fullscreen", "bool")]),
            ("Camara", [("Indice camara", "camera.index", "number"), ("Ancho captura", "camera.width", "number"), ("Alto captura", "camera.height", "number"), ("FPS", "camera.fps", "number")]),
            ("Control", [("Tolerancia px", "control.tolerance_px", "number"), ("Error medio px", "control.medium_error_px", "number"), ("Pulso chico ms", "control.pulse_small_ms", "number"), ("Pulso grande ms", "control.pulse_large_ms", "number"), ("Espera entre pulsos ms", "control.cooldown_ms", "number"), ("Invertir correccion", "control.invert_correction", "bool"), ("Parar ante falla", "control.stop_on_fault", "bool")]),
            ("Vision", [("ROI y1", "roi.y1", "number"), ("ROI y2", "roi.y2", "number"), ("Rango busqueda borde px", "vision.edge_search_window_px", "number"), ("Confianza minima borde", "vision.edge_min_confidence", "number"), ("Ancho minimo papel px", "vision.min_paper_width_px", "number"), ("Ancho maximo papel px", "vision.max_paper_width_px", "number"), ("Frames falta papel", "vision.no_paper_confirm_frames", "number")]),
            ("Visualizacion", [("Paleta de lineas", "display.line_palette", "choice"), ("Ancho lineas px", "display.line_width_px", "number")]),
            ("Calibracion", [("Referencia izquierda", "calibration.left_reference_x", "number"), ("Borde izquierdo ideal", "calibration.ideal_left_edge_x", "number"), ("Borde derecho ideal", "calibration.ideal_right_edge_x", "number"), ("Referencia derecha", "calibration.right_reference_x", "number"), ("Centro ideal", "calibration.ideal_center_x", "number"), ("px por mm", "calibration.px_per_mm", "number")]),
            ("Inicio y energia", [("Inicio Windows", "windows.startup", "action"), ("Abrir BIOS/UEFI", "system.uefi", "action")]),
        ]

    def _hmi_button(self, parent, text: str, command, color: str = "gray") -> tk.Button:
        colors = {
            "green": ("#16a34a", "#ffffff", "#22c55e"),
            "red": ("#dc2626", "#ffffff", "#ef4444"),
            "blue": ("#2563eb", "#ffffff", "#3b82f6"),
            "gray": ("#374151", "#ffffff", "#4b5563"),
            "yellow": ("#d97706", "#111827", "#f59e0b"),
        }
        bg, fg, active = colors.get(color, colors["gray"])
        return tk.Button(parent, text=text, command=command, font=self.hmi_font, bg=bg, fg=fg, activebackground=active, activeforeground=fg, relief=tk.FLAT, bd=0, padx=14, pady=18, cursor="hand2")

    def _keypad_button(self, parent, text: str, command, color: str = "blue") -> tk.Button:
        button = self._hmi_button(parent, text, command, color)
        if text in ("BORRAR", "LIMPIAR", "CANCELAR", "ACEPTAR"):
            button.configure(font=("Segoe UI", 25, "bold"))
        else:
            button.configure(font=("Segoe UI", 44, "bold"))
        return button

    def _toggle_auto_button(self) -> None:
        self.auto_var.set(not self.auto_enabled)
        self._toggle_auto()

    def _confirm_shutdown(self) -> None:
        if messagebox.askyesno("Cerrar", "¿Cerrar la aplicacion y apagar salidas?"):
            self.shutdown()

    def _open_config_window(self) -> None:
        if hasattr(self, "config_window") and self.config_window.winfo_exists():
            self.config_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.config_window = win
        win.title("Configuracion")
        win.configure(bg="#0b1117")
        win.transient(self.root)
        try:
            win.attributes("-fullscreen", bool(self.root.attributes("-fullscreen")))
        except tk.TclError:
            pass

        header = tk.Frame(win, bg="#111827", padx=12, pady=10)
        header.pack(fill=tk.X)
        tk.Label(header, text="CONFIGURACION", font=("Segoe UI", 30, "bold"), fg="#e5e7eb", bg="#111827").pack(side=tk.LEFT)
        self._hmi_button(header, "VOLVER", win.destroy, "gray").pack(side=tk.RIGHT, padx=(8, 0))
        self._hmi_button(header, "GUARDAR CONFIGURACION", self._save_config_from_window, "green").pack(side=tk.RIGHT)

        action_bar = tk.Frame(win, bg="#0b1117", padx=12, pady=8)
        action_bar.pack(fill=tk.X)
        for label, key in [("1) REF IZQ", "left_reference_x"), ("2) BORDE IZQ", "ideal_left_edge_x"), ("3) BORDE DER", "ideal_right_edge_x"), ("4) REF DER", "right_reference_x")]:
            self._hmi_button(action_bar, label, lambda k=key: self._set_pending_and_close(k), "blue").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        body = tk.Frame(win, bg="#0b1117")
        body.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(body, bg="#0b1117", highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient=tk.VERTICAL, command=canvas.yview, width=34)
        content = tk.Frame(canvas, bg="#0b1117", padx=12, pady=8)
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.config_value_vars.clear()
        self.config_widgets.clear()
        self._build_camera_config_card(content)
        for section, items in self._config_sections():
            box = tk.LabelFrame(content, text=section.upper(), font=("Segoe UI", 22, "bold"), fg="#f8fafc", bg="#0b1117", bd=2, relief=tk.GROOVE, labelanchor="nw", padx=10, pady=8)
            box.pack(fill=tk.X, pady=10)
            for label, dotted, kind in items:
                self._build_config_row(box, label, dotted, kind)

        bottom = tk.Frame(win, bg="#111827", padx=12, pady=10)
        bottom.pack(fill=tk.X)
        self._hmi_button(bottom, "USAR CENTRO ACTUAL", self._use_current_center_as_ideal, "blue").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._hmi_button(bottom, "RECALCULAR CENTRO", lambda: self._recalc_ideal_center(save=False), "gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._hmi_button(bottom, "CERRAR", win.destroy, "red").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

    def _build_camera_config_card(self, parent) -> None:
        frame = tk.LabelFrame(parent, text="SELECCION DE CAMARA", font=("Segoe UI", 22, "bold"), fg="#f8fafc", bg="#0b1117", bd=2, relief=tk.GROOVE, labelanchor="nw", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=10)
        tk.Label(frame, textvariable=self.active_camera_var, font=self.hmi_small_font, fg="#cbd5e1", bg="#0b1117").pack(anchor="w", pady=2)
        tk.Label(frame, textvariable=self.active_backend_var, font=self.hmi_small_font, fg="#cbd5e1", bg="#0b1117").pack(anchor="w", pady=2)
        self.camera_backend_combo = ttk.Combobox(frame, values=["dshow", "msmf", "default"], state="readonly", font=("Segoe UI", 28), height=5)
        current_backend = str(self.config.get("camera.backend", "dshow"))
        self.camera_backend_combo.set(current_backend if current_backend in ("dshow", "msmf", "default") else "dshow")
        self.camera_backend_combo.dotted = "camera.backend"  # type: ignore[attr-defined]
        self.camera_backend_combo.pack(fill=tk.X, pady=8, ipady=18)
        self.camera_select = ttk.Combobox(frame, state="readonly", font=("Segoe UI", 28), height=8)
        self.camera_select.pack(fill=tk.X, pady=8, ipady=18)
        row = tk.Frame(frame, bg="#0b1117")
        row.pack(fill=tk.X, pady=4)
        self._hmi_button(row, "BUSCAR CAMARAS", self._scan_cameras, "blue").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._hmi_button(row, "USAR SELECCIONADA", self._use_selected_camera, "green").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

    def _build_config_row(self, parent, label: str, dotted: str, kind: str) -> None:
        if kind == "action":
            row = tk.Frame(parent, bg="#1f2937", padx=12, pady=10)
            row.pack(fill=tk.X, pady=6)
            command = self._toggle_windows_startup_action if dotted == "windows.startup" else self._restart_to_uefi
            text = self.windows_startup_status_var.get() if dotted == "windows.startup" else label
            self._hmi_button(row, text, command, "blue").pack(fill=tk.X)
            return
        row = tk.Frame(parent, bg="#1f2937", padx=16, pady=18)
        row.pack(fill=tk.X, pady=8)
        tk.Label(row, text=label, font=("Segoe UI", 24), fg="#e5e7eb", bg="#1f2937", anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        value = self.config.get(dotted, "")
        var = tk.StringVar(value="" if value is None else str(value))
        self.config_value_vars[dotted] = var
        if kind == "bool":
            btn = self._hmi_button(row, "SI" if bool(value) else "NO", lambda d=dotted: self._toggle_config_bool(d), "green" if bool(value) else "gray")
            btn.pack(side=tk.RIGHT, padx=(8, 0))
            self.config_widgets[dotted] = btn
        elif dotted == "serial.port":
            combo = ttk.Combobox(row, textvariable=var, values=self._serial_port_values(), state="readonly", font=("Segoe UI", 28), height=8)
            combo.pack(side=tk.RIGHT, fill=tk.X, expand=False, ipady=18, padx=(8, 0))
            self.config_widgets[dotted] = combo
        elif dotted == "display.line_palette":
            combo = ttk.Combobox(row, textvariable=var, values=self._line_palette_values(), state="readonly", font=("Segoe UI", 28), height=6)
            combo.pack(side=tk.RIGHT, fill=tk.X, expand=False, ipady=18, padx=(8, 0))
            self.config_widgets[dotted] = combo
        elif kind == "text":
            entry = tk.Entry(row, textvariable=var, font=("Segoe UI", 28), bg="#f8fafc", fg="#111827", relief=tk.FLAT)
            entry.pack(side=tk.RIGHT, fill=tk.X, expand=False, ipady=18, padx=(8, 0))
            self.config_widgets[dotted] = entry
        else:
            value_button = self._hmi_button(row, var.get() or "--", lambda d=dotted, l=label: self._open_numeric_keypad(d, l), "blue")
            value_button.configure(font=("Segoe UI", 26, "bold"), width=10)
            value_button.pack(side=tk.RIGHT, padx=(8, 0))
            self.config_widgets[dotted] = value_button

    def _serial_port_values(self) -> list[str]:
        current = str(self.config.get("serial.port", "COM3"))
        ports = [current]
        try:
            from serial.tools import list_ports

            ports += [port.device for port in list_ports.comports()]
        except Exception:
            ports += [f"COM{i}" for i in range(1, 11)]
        seen = set()
        return [port for port in ports if port and not (port in seen or seen.add(port))]

    def _line_palette_values(self) -> list[str]:
        return ["industrial", "alto_contraste", "calida"]

    def _toggle_config_bool(self, dotted: str) -> None:
        var = self.config_value_vars[dotted]
        current = var.get().strip().lower() in ("1", "true", "si", "sí", "yes", "on")
        new_value = not current
        var.set("true" if new_value else "false")
        btn = self.config_widgets.get(dotted)
        if isinstance(btn, tk.Button):
            btn.configure(text="SI" if new_value else "NO", bg="#16a34a" if new_value else "#374151", activebackground="#22c55e" if new_value else "#4b5563")

    def _toggle_windows_startup_action(self) -> None:
        self.windows_startup_var.set(not self.windows_startup_var.get())
        self._toggle_windows_startup()

    def _set_pending_and_close(self, key: str) -> None:
        self._set_pending(key)
        if hasattr(self, "config_window") and self.config_window.winfo_exists():
            self.config_window.destroy()

    def _open_numeric_keypad(self, dotted: str, label: str) -> None:
        var = self.config_value_vars[dotted]
        parent = self.config_window if hasattr(self, "config_window") and self.config_window.winfo_exists() else self.root
        pad = tk.Toplevel(parent)
        pad.title(label)
        pad.configure(bg="#0b1117")
        pad.transient(parent)
        pad.grab_set()
        try:
            fullscreen = bool(parent.attributes("-fullscreen"))
            pad.attributes("-fullscreen", fullscreen)
            if not fullscreen:
                pad.geometry("800x480")
        except tk.TclError:
            pad.geometry("800x480")
        pad.protocol("WM_DELETE_WINDOW", pad.destroy)
        display = tk.StringVar(value=var.get())
        first_key = True
        header = tk.Frame(pad, bg="#0b1117", padx=14, pady=8)
        header.pack(fill=tk.X)
        tk.Label(header, text=label, font=("Segoe UI", 28, "bold"), fg="#e5e7eb", bg="#0b1117", anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(header, textvariable=display, font=("Segoe UI", 54, "bold"), fg="#f8fafc", bg="#17212e", padx=24, pady=6, width=8).pack(side=tk.RIGHT)
        grid = tk.Frame(pad, bg="#0b1117", padx=14, pady=10)
        grid.pack(fill=tk.BOTH, expand=True)

        def press(value: str) -> None:
            nonlocal first_key
            cur = display.get()
            if value == "BORRAR":
                display.set(cur[:-1])
                first_key = False
            elif value == "LIMPIAR":
                display.set("")
                first_key = False
            elif value == "-":
                display.set("-" if first_key else (cur[1:] if cur.startswith("-") else "-" + cur))
                first_key = False
            elif value == ".":
                if first_key:
                    display.set("0.")
                elif "." not in cur:
                    display.set((cur or "0") + ".")
                first_key = False
            else:
                display.set(value if first_key else cur + value)
                first_key = False

        keys = [
            ("7", "8", "9", "BORRAR"),
            ("4", "5", "6", "LIMPIAR"),
            ("1", "2", "3", "CANCELAR"),
            ("-", "0", ".", "ACEPTAR"),
        ]
        for r, row_keys in enumerate(keys):
            grid.rowconfigure(r, weight=1, minsize=86)
            for c, key in enumerate(row_keys):
                grid.columnconfigure(c, weight=1, minsize=120)
                color = "green" if key == "ACEPTAR" else ("red" if key == "CANCELAR" else ("gray" if key in ("BORRAR", "LIMPIAR") else "blue"))
                if key == "CANCELAR":
                    cmd = pad.destroy
                elif key == "ACEPTAR":
                    cmd = lambda: accept()
                else:
                    cmd = lambda k=key: press(k)
                self._keypad_button(grid, key, cmd, color).grid(row=r, column=c, sticky="nsew", padx=6, pady=6)

        def accept() -> None:
            raw = display.get().strip()
            try:
                if raw in ("", "-", ".", "-."):
                    raise ValueError
                float(raw)
            except ValueError:
                messagebox.showwarning("Valor invalido", "Ingresá un numero valido.")
                return
            var.set(raw)
            widget = self.config_widgets.get(dotted)
            if isinstance(widget, tk.Button):
                widget.configure(text=raw)
            pad.destroy()
        pad.lift()
        pad.focus_force()

    def _save_config_from_window(self) -> None:
        self._apply_entries()
        self.config.save()
        self.last_command = "Configuracion guardada"
        messagebox.showinfo("Configuracion", "Configuracion guardada")

    def _adjustment_entries(self) -> list[ttk.Entry | ttk.Combobox]:
        return [self.camera_backend_combo] if hasattr(self, "camera_backend_combo") else []

    def _update_vision_range_label(self) -> None:
        if not hasattr(self, "vision_range_var"):
            return
        try:
            if hasattr(self, "edge_window_entry") and hasattr(self, "pxmm_entry"):
                window_px = float(self.edge_window_entry.get().strip())
                px_per_mm = float(self.pxmm_entry.get().strip())
            else:
                window_px = float(self.config.get("vision.edge_search_window_px"))
                px_per_mm = float(self.config.get("calibration.px_per_mm"))
            if px_per_mm <= 0:
                raise ValueError
            self.vision_range_var.set(f"Rango búsqueda aprox: {window_px / px_per_mm:.1f} mm")
        except ValueError:
            self.vision_range_var.set("Rango búsqueda aprox: -- mm")

    def _refresh_windows_startup_status(self) -> None:
        if not hasattr(self, "windows_startup_status_var"):
            return
        try:
            status = startup_status()
            self.windows_startup_var.set(status.enabled)
            label = "Activado" if status.enabled else "Desactivado"
            detail = f" ({status.detail})" if status.detail else ""
            self.windows_startup_status_var.set(f"Inicio con Windows: {label}{detail}")
        except Exception as exc:
            self.windows_startup_var.set(False)
            self.windows_startup_status_var.set("Inicio con Windows: error")
            self.logger.warning("No se pudo consultar inicio con Windows: %s", exc)

    def _toggle_windows_startup(self) -> None:
        desired = bool(self.windows_startup_var.get())
        try:
            if desired:
                ok, error = enable_startup(self.config.path)
            else:
                ok, error = disable_startup()
            if not ok:
                messagebox.showerror("Inicio con Windows", error or "No se pudo cambiar el inicio con Windows.")
        except Exception as exc:
            messagebox.showerror("Inicio con Windows", f"No se pudo cambiar el inicio con Windows:\n{exc}")
        self._refresh_windows_startup_status()

    def _show_uefi_manual_instructions(self) -> None:
        messagebox.showinfo(
            "Encendido automático al volver la corriente",
            "Esta opción no depende de Windows sino del BIOS/UEFI.\n\n"
            "Reiniciá la PC y entrá al BIOS/UEFI presionando DEL, F2, F10, F12 o ESC según el fabricante.\n\n"
            "Buscá una de estas opciones:\n"
            "- Restore on AC Power Loss\n"
            "- AC Power Recovery\n"
            "- Power On After Power Fail\n"
            "- After Power Loss\n"
            "- State After Power Loss\n"
            "- AC Back\n\n"
            "Configurala en Power On.",
        )

    def _restart_to_uefi(self) -> None:
        confirmed = messagebox.askyesno(
            "Abrir BIOS/UEFI",
            "La computadora se reiniciará y entrará a la configuración UEFI/BIOS. Guardá tu trabajo antes de continuar.\n\n¿Continuar?",
        )
        if not confirmed:
            return
        ok, error = restart_to_uefi()
        if not ok:
            messagebox.showerror("No se pudo abrir UEFI/BIOS", f"{error}\n\nVoy a mostrar las instrucciones manuales.")
            self._show_uefi_manual_instructions()

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
        self._clear_output_indicators()
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
        backend = self.camera_backend_combo.get().strip() if hasattr(self, "camera_backend_combo") else str(self.config.get("camera.backend", "dshow"))
        backend = backend or str(self.config.get("camera.backend", "dshow"))
        self._prepare_camera_change("Buscando cámaras")
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        if hasattr(self, "camera_select"):
            self.camera_select.configure(values=[])
            self.camera_select.set("Buscando...")
        self.root.update_idletasks()
        self.camera_infos = scan_cameras(max_index=8, backend=backend)
        labels = [info.label() for info in self.camera_infos]
        if hasattr(self, "camera_select"):
            self.camera_select.configure(values=labels)
        current_index = int(self.config.get("camera.index", 0))
        selected = next((info.label() for info in self.camera_infos if info.index == current_index), labels[0] if labels else "")
        if hasattr(self, "camera_select"):
            self.camera_select.set(selected)
        self._reopen_camera_unsafe()
        available_count = sum(1 for info in self.camera_infos if info.available)
        self.last_command = f"Cámaras encontradas: {available_count}"

    def _selected_camera_info(self) -> Optional[CameraInfo]:
        if not hasattr(self, "camera_select"):
            return None
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
        backend = self.camera_backend_combo.get().strip() if hasattr(self, "camera_backend_combo") else str(self.config.get("camera.backend", "dshow"))
        backend = backend or str(self.config.get("camera.backend", "dshow"))
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
            self.state_badge.configure(text="SIN CAMARA", bg="#dc2626")
            self.camera_badge.configure(text="SIN CAM", bg="#dc2626")
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
            self._set_output_indicator(direction, ms / 1000.0)
            self.last_command = f"PULSO {direction} {ms} ms"
            self.logger.info("%s | error_px=%.1f error_mm=%s", self.last_command, error, result.error_mm)
        else:
            self.last_command = "No se pudo enviar pulso"

    def _draw_overlay(self, frame: np.ndarray, result: DetectionResult) -> np.ndarray:
        h, w = frame.shape[:2]
        x1, x2, y1, y2 = result.roi
        colors = self._overlay_colors()
        line_w = max(1, min(12, int(self.config.get("display.line_width_px", 4))))
        cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), colors["roi"], max(1, line_w - 1))
        cv2.line(frame, (x1, y1), (x2 - 1, y1), colors["roi"], line_w + 2, cv2.LINE_AA)
        cv2.line(frame, (x1, y2 - 1), (x2 - 1, y2 - 1), colors["roi"], line_w + 2, cv2.LINE_AA)
        cv2.putText(frame, "AREA LECTURA", (max(5, x1 + 8), max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, colors["roi"], 2, cv2.LINE_AA)

        def vline(x: Optional[float], color, label: str, thickness: int):
            if x is None:
                return
            xi = int(round(x))
            cv2.line(frame, (xi, 0), (xi, h - 1), color, thickness)
            cv2.putText(frame, label, (max(5, xi + 5), 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        vline(self.config.get("calibration.left_reference_x"), colors["reference"], "REF IZQ", line_w)
        vline(self.config.get("calibration.right_reference_x"), colors["reference"], "REF DER", line_w)
        vline(self.config.get("calibration.ideal_left_edge_x"), colors["ideal_edge"], "BORDE IZQ IDEAL", max(1, line_w - 2))
        vline(self.config.get("calibration.ideal_right_edge_x"), colors["ideal_edge"], "BORDE DER IDEAL", max(1, line_w - 2))
        vline(result.ideal_center_x, colors["ideal_center"], "CENTRO IDEAL", line_w)
        vline(result.left_edge_x, colors["detected_edge"] if result.valid else colors["fault"], "BORDE IZQ", line_w + 1)
        vline(result.right_edge_x, colors["detected_edge"] if result.valid else colors["fault"], "BORDE DER", line_w + 1)
        vline(result.paper_center_x, colors["paper_center"], "CENTRO PAPEL", line_w)

        auto_text = "AUTO ON" if self.auto_enabled else "AUTO OFF"
        valid_text = "VISION OK" if result.valid else f"FAULT {result.fault}"
        cv2.rectangle(frame, (5, h - 90), (min(w - 5, 760), h - 5), (0, 0, 0), -1)
        cv2.putText(frame, f"{auto_text} | {valid_text}", (15, h - 62), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        err = "--" if result.error_px is None else f"{result.error_px:.1f}px / {result.error_mm:.2f}mm"
        cv2.putText(frame, f"Error: {err} | Cmd: {self.last_command}", (15, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        if self.pending_click:
            cv2.putText(frame, f"CLICK para setear: {self.pending_click}", (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colors["roi"], 2, cv2.LINE_AA)
        return frame

    def _overlay_colors(self) -> dict[str, tuple[int, int, int]]:
        palette = str(self.config.get("display.line_palette", "industrial"))
        palettes = {
            "industrial": {
                "roi": (0, 180, 255),
                "reference": (255, 220, 0),
                "ideal_edge": (190, 190, 190),
                "ideal_center": (255, 0, 255),
                "detected_edge": (80, 255, 80),
                "paper_center": (255, 140, 0),
                "fault": (0, 0, 255),
            },
            "alto_contraste": {
                "roi": (0, 255, 255),
                "reference": (255, 255, 255),
                "ideal_edge": (0, 165, 255),
                "ideal_center": (255, 0, 255),
                "detected_edge": (0, 255, 0),
                "paper_center": (255, 255, 0),
                "fault": (0, 0, 255),
            },
            "calida": {
                "roi": (0, 140, 255),
                "reference": (0, 215, 255),
                "ideal_edge": (160, 160, 220),
                "ideal_center": (255, 120, 255),
                "detected_edge": (90, 255, 120),
                "paper_center": (255, 200, 80),
                "fault": (0, 0, 255),
            },
        }
        return palettes.get(palette, palettes["industrial"])

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
        if result.valid:
            self.state_badge.configure(text="VISION OK", bg="#16a34a")
        else:
            self.state_badge.configure(text=f"FALLA {result.fault or 'VISION'}", bg="#dc2626")
        self.mode_badge.configure(text="AUTO ON" if self.auto_enabled else "AUTO OFF", bg="#16a34a" if self.auto_enabled else "#2563eb")
        opened = self.capture is not None and self.capture.isOpened()
        self.camera_badge.configure(text=f"CAM {self.config.get('camera.index', '--')}" if opened else "SIN CAM", bg="#334155" if opened else "#dc2626")
        self.auto_button.configure(text="AUTO: ON" if self.auto_enabled else "AUTO: OFF", bg="#16a34a" if self.auto_enabled else "#2563eb", activebackground="#22c55e" if self.auto_enabled else "#3b82f6")
        self._update_output_indicators()

    def _set_output_indicator(self, direction: str, duration_s: float) -> None:
        self.output_direction = direction.upper()
        self.output_until = time.monotonic() + max(0.2, duration_s)
        self._update_output_indicators()

    def _clear_output_indicators(self) -> None:
        self.output_direction = None
        self.output_until = 0.0
        self._update_output_indicators()

    def _update_output_indicators(self) -> None:
        if not hasattr(self, "left_output_label") or not hasattr(self, "right_output_label"):
            return
        active = self.output_direction if time.monotonic() <= self.output_until else None
        if active is None:
            self.output_direction = None
        left_on = active == "LEFT"
        right_on = active == "RIGHT"
        self.left_output_label.configure(text="IZQ\nON" if left_on else "IZQ\nOFF", bg="#16a34a" if left_on else "#1f2937", fg="#ffffff" if left_on else "#94a3b8")
        self.right_output_label.configure(text="DER\nON" if right_on else "DER\nOFF", bg="#16a34a" if right_on else "#1f2937", fg="#ffffff" if right_on else "#94a3b8")

    def _update_info(self, result: Optional[DetectionResult]) -> None:
        serial_status = self.serial.status()
        lines = self._summary_lines([
            ("Puerto serie", serial_status.port),
            ("Serie", "DRY" if serial_status.dry_run else ("OK" if serial_status.connected else "DESCONECTADA")),
            ("Error serie", serial_status.last_error or "-"),
        ])
        if result is not None:
            lines += self._summary_lines([
                ("Vision", "OK" if result.valid else (result.fault or "FALLA")),
                ("Borde izq", result.left_edge_x),
                ("Borde der", result.right_edge_x),
                ("Centro papel", None if result.paper_center_x is None else round(result.paper_center_x, 1)),
                ("Centro ideal", round(result.ideal_center_x, 1)),
                ("Error", "--" if result.error_px is None else f"{result.error_px:.1f}px / {result.error_mm:.2f}mm"),
                ("Ancho", result.paper_width_px),
                ("Ultimo comando", self.last_command or "-"),
            ])
        if hasattr(self, "summary_var"):
            self.summary_var.set("\n".join(lines[:24]))
        if hasattr(self, "info_text"):
            self.info_text.configure(state="normal")
            self.info_text.delete("1.0", tk.END)
            self.info_text.insert("1.0", "\n".join(lines))
            self.info_text.configure(state="disabled")

    def _summary_lines(self, items: list[tuple[str, object]]) -> list[str]:
        lines: list[str] = []
        for label, value in items:
            lines.append(f"{label.upper()}: {value}")
        return lines

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
        if hasattr(self, "auto_button"):
            self.auto_button.configure(text="AUTO: ON" if self.auto_enabled else "AUTO: OFF", bg="#16a34a" if self.auto_enabled else "#2563eb", activebackground="#22c55e" if self.auto_enabled else "#3b82f6")
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
        self._clear_output_indicators()
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
        if hasattr(self, "config_value_vars"):
            for dotted, var in self.config_value_vars.items():
                if not self._apply_config_value(dotted, var.get(), warn=True):
                    return
        for e in self._adjustment_entries():
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
        self._update_vision_range_label()
        self.serial.update_config(self.config)
        self.detector.update_config(self.config)
        if str(self.config.get("camera.backend", "dshow")) != old_backend:
            self._reopen_camera()
        else:
            self._refresh_camera_status_labels()
        self.serial.close()
        self.serial.open_if_needed()

    def _apply_config_value(self, dotted: str, raw: str, warn: bool) -> bool:
        old = self.config.get(dotted)
        try:
            if isinstance(old, bool):
                value = raw.strip().lower() in ("1", "true", "si", "sí", "yes", "on")
            elif isinstance(old, int):
                value = int(float(raw))
            elif isinstance(old, float) or old is None:
                value = None if raw.strip() == "" else float(raw)
            else:
                value = raw.strip()
            self.config.set(dotted, value)
            return True
        except ValueError:
            if warn:
                messagebox.showwarning("Valor invalido", f"No pude aplicar {dotted}={raw}")
            return False

    def _save_config(self) -> None:
        self._apply_entries_silent()
        self.config.save()
        self.logger.info("Configuración guardada en %s", self.config.path)
        self.last_command = "Configuración guardada"

    def _apply_entries_silent(self) -> None:
        if hasattr(self, "config_value_vars"):
            for dotted, var in self.config_value_vars.items():
                self._apply_config_value(dotted, var.get(), warn=False)
        for e in self._adjustment_entries():
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
        self._update_vision_range_label()

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
