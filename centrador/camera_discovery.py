from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class CameraInfo:
    index: int
    available: bool
    width: Optional[int] = None
    height: Optional[int] = None
    error: Optional[str] = None
    frame: Optional[np.ndarray] = None

    def label(self) -> str:
        if self.available and self.width and self.height:
            return f"{self.index} - OK {self.width}x{self.height}"
        if self.available:
            return f"{self.index} - OK"
        return f"{self.index} - no disponible"


def backend_api(backend: str) -> Optional[int]:
    normalized = backend.lower().strip()
    if normalized == "dshow":
        return cv2.CAP_DSHOW
    if normalized == "msmf":
        return cv2.CAP_MSMF
    return None


def open_camera(index: int, backend: str) -> cv2.VideoCapture:
    api = backend_api(backend)
    return cv2.VideoCapture(index, api) if api is not None else cv2.VideoCapture(index)


def probe_camera(index: int, backend: str, keep_frame: bool = False) -> CameraInfo:
    cap: Optional[cv2.VideoCapture] = None
    try:
        cap = open_camera(index, backend)
        if not cap.isOpened():
            return CameraInfo(index=index, available=False, error="no abre")
        ok, frame = cap.read()
        if not ok or frame is None:
            return CameraInfo(index=index, available=False, error="sin frame")
        height, width = frame.shape[:2]
        return CameraInfo(
            index=index,
            available=True,
            width=int(width),
            height=int(height),
            frame=frame.copy() if keep_frame else None,
        )
    except Exception as exc:
        return CameraInfo(index=index, available=False, error=str(exc))
    finally:
        if cap is not None:
            cap.release()


def scan_cameras(max_index: int = 8, backend: str = "dshow", keep_frames: bool = False) -> list[CameraInfo]:
    max_index = max(0, int(max_index))
    return [probe_camera(index, backend, keep_frame=keep_frames) for index in range(max_index + 1)]
