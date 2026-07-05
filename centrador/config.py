from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "title": "Centrador Corrugadora",
        "auto_start_enabled": False,
        "fullscreen": True,
        "update_interval_ms": 40,
        "save_debug_frames": False,
        "debug_frames_dir": "logs/debug_frames",
    },
    "camera": {
        "index": 0,
        "backend": "dshow",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "flip_horizontal": False,
        "flip_vertical": False,
        "rotate_180": False,
        "autofocus": None,
        "exposure": None,
        "gain": None,
    },
    "roi": {"x1": 0, "x2": 0, "y1": 260, "y2": 460},
    "calibration": {
        "left_reference_x": 150,
        "ideal_left_edge_x": 420,
        "ideal_right_edge_x": 860,
        "right_reference_x": 1130,
        "ideal_center_x": None,
        "px_per_mm": 4.0,
    },
    "vision": {
        "auto_edge_detection_enabled": True,
        "edge_search_window_px": 90,
        "edge_exclusion_margin_px": 25,
        "edge_pair_min_separation_px": 0,
        "edge_pair_max_separation_px": 0,
        "edge_min_confidence": 4.0,
        "profile_smooth_window": 13,
        "min_paper_width_px": 150,
        "max_paper_width_px": 0,
        "no_paper_confirm_frames": 8,
        "reference_check_enabled": False,
        "reference_search_window_px": 30,
        "reference_dark_threshold": 70,
        "reference_min_dark_ratio": 0.08,
    },
    "control": {
        "invert_correction": False,
        "tolerance_px": 18,
        "medium_error_px": 60,
        "pulse_small_ms": 100,
        "pulse_large_ms": 250,
        "cooldown_ms": 500,
        "max_pulse_ms": 800,
        "require_serial_ok_for_auto": True,
        "stop_on_fault": True,
    },
    "display": {
        "line_palette": "industrial",
        "line_width_px": 4,
    },
    "serial": {
        "enabled": True,
        "port": "COM3",
        "baudrate": 115200,
        "timeout_s": 0.2,
        "reconnect_every_s": 3.0,
        "heartbeat_interval_s": 1.0,
        "startup_command": "ENABLE 0",
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class ConfigStore:
    path: Path
    data: Dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "ConfigStore":
        p = Path(path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False, allow_unicode=True)
            raw: Dict[str, Any] = {}
        else:
            with p.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        return cls(path=p, data=deep_merge(DEFAULT_CONFIG, raw))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, sort_keys=False, allow_unicode=True)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value: Any) -> None:
        cur: Any = self.data
        parts = dotted.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def ideal_center_x(self) -> float:
        configured = self.get("calibration.ideal_center_x")
        if configured is not None:
            return float(configured)
        left = float(self.get("calibration.ideal_left_edge_x"))
        right = float(self.get("calibration.ideal_right_edge_x"))
        return (left + right) / 2.0
