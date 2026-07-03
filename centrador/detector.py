from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import ConfigStore


@dataclass
class EdgeDetection:
    x: Optional[int]
    confidence: float
    target_x: int
    window: Tuple[int, int]


@dataclass
class DetectionResult:
    valid: bool
    fault: Optional[str]
    left_edge_x: Optional[int]
    right_edge_x: Optional[int]
    paper_center_x: Optional[float]
    ideal_center_x: float
    error_px: Optional[float]
    error_mm: Optional[float]
    paper_width_px: Optional[int]
    left_confidence: float
    right_confidence: float
    no_paper_counter: int
    roi: Tuple[int, int, int, int]
    left_ref_ok: bool
    right_ref_ok: bool


class PaperDetector:
    """Detecta dos bordes del papel contra referencias calibradas.

    Estrategia:
    - Recorta una ROI horizontal.
    - Convierte a gris y calcula gradiente vertical con Sobel X.
    - Promedia el gradiente por columna.
    - Busca el pico de borde cerca de cada borde ideal calibrado.
    - Si los bordes no tienen confianza suficiente o el ancho no cierra, declara falta de papel.

    Esto está pensado para una instalación industrial simple y calibrable, no para adivinar escenas complejas.
    """

    def __init__(self, config: ConfigStore):
        self.config = config
        self.no_paper_counter = 0

    def update_config(self, config: ConfigStore) -> None:
        self.config = config

    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        height, width = frame_bgr.shape[:2]
        x1, x2, y1, y2 = self._roi_bounds(width, height)
        roi = frame_bgr[y1:y2, x1:x2]

        if roi.size == 0 or roi.shape[0] < 5 or roi.shape[1] < 5:
            self.no_paper_counter += 1
            return self._result(False, "ROI_INVALIDA", None, None, None, None, None, None, 0, 0, (x1, x2, y1, y2), False, False)

        profile, gray = self._edge_profile(roi)
        min_conf = float(self.config.get("vision.edge_min_confidence", 4.0))
        window = int(self.config.get("vision.edge_search_window_px", 90))

        target_left = int(self.config.get("calibration.ideal_left_edge_x", 0)) - x1
        target_right = int(self.config.get("calibration.ideal_right_edge_x", 0)) - x1

        left = self._find_edge(profile, target_left, window)
        right = self._find_edge(profile, target_right, window)

        left_x = left.x + x1 if left.x is not None else None
        right_x = right.x + x1 if right.x is not None else None

        left_ref_ok, right_ref_ok = self._check_references(gray, x1)

        fault: Optional[str] = None
        valid = True

        if left.x is None or right.x is None:
            valid = False
            fault = "BORDE_NO_DETECTADO"
        elif left.confidence < min_conf or right.confidence < min_conf:
            valid = False
            fault = "CONFIANZA_BAJA"
        elif left_x is not None and right_x is not None and right_x <= left_x:
            valid = False
            fault = "BORDES_CRUZADOS"

        width_px: Optional[int] = None
        if valid and left_x is not None and right_x is not None:
            width_px = int(right_x - left_x)
            min_width = int(self.config.get("vision.min_paper_width_px", 150))
            max_width = int(self.config.get("vision.max_paper_width_px", 0))
            if width_px < min_width:
                valid = False
                fault = "PAPEL_DEMASIADO_ANGOSTO_O_AUSENTE"
            if max_width > 0 and width_px > max_width:
                valid = False
                fault = "PAPEL_DEMASIADO_ANCHO"

        if self.config.get("vision.reference_check_enabled", False):
            if not left_ref_ok or not right_ref_ok:
                valid = False
                fault = "REFERENCIA_NO_VISIBLE"

        if not valid:
            self.no_paper_counter += 1
        else:
            self.no_paper_counter = 0

        confirm_frames = int(self.config.get("vision.no_paper_confirm_frames", 8))
        if self.no_paper_counter >= confirm_frames:
            fault = "FALTA_DE_PAPEL_O_VISION_INVALIDA"
            valid = False

        ideal_center = self.config.ideal_center_x()
        center: Optional[float] = None
        error_px: Optional[float] = None
        error_mm: Optional[float] = None
        if valid and left_x is not None and right_x is not None:
            center = (left_x + right_x) / 2.0
            error_px = center - ideal_center
            px_per_mm = float(self.config.get("calibration.px_per_mm", 1.0)) or 1.0
            error_mm = error_px / px_per_mm

        return self._result(
            valid,
            fault,
            left_x,
            right_x,
            center,
            error_px,
            error_mm,
            width_px,
            left.confidence,
            right.confidence,
            (x1, x2, y1, y2),
            left_ref_ok,
            right_ref_ok,
        )

    def _result(
        self,
        valid: bool,
        fault: Optional[str],
        left_x: Optional[int],
        right_x: Optional[int],
        center: Optional[float],
        error_px: Optional[float],
        error_mm: Optional[float],
        width_px: Optional[int],
        left_conf: float,
        right_conf: float,
        roi: Tuple[int, int, int, int],
        left_ref_ok: bool,
        right_ref_ok: bool,
    ) -> DetectionResult:
        return DetectionResult(
            valid=valid,
            fault=fault,
            left_edge_x=left_x,
            right_edge_x=right_x,
            paper_center_x=center,
            ideal_center_x=self.config.ideal_center_x(),
            error_px=error_px,
            error_mm=error_mm,
            paper_width_px=width_px,
            left_confidence=left_conf,
            right_confidence=right_conf,
            no_paper_counter=self.no_paper_counter,
            roi=roi,
            left_ref_ok=left_ref_ok,
            right_ref_ok=right_ref_ok,
        )

    def _roi_bounds(self, width: int, height: int) -> Tuple[int, int, int, int]:
        x1 = int(self.config.get("roi.x1", 0))
        x2 = int(self.config.get("roi.x2", 0))
        y1 = int(self.config.get("roi.y1", 0))
        y2 = int(self.config.get("roi.y2", height))
        if x2 <= 0:
            x2 = width
        x1 = max(0, min(width - 1, x1))
        x2 = max(x1 + 1, min(width, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(y1 + 1, min(height, y2))
        return x1, x2, y1, y2

    def _edge_profile(self, roi_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        profile = np.mean(np.abs(sobel_x), axis=0)
        smooth_window = int(self.config.get("vision.profile_smooth_window", 13))
        if smooth_window > 1:
            if smooth_window % 2 == 0:
                smooth_window += 1
            kernel = np.ones(smooth_window, dtype=np.float32) / float(smooth_window)
            profile = np.convolve(profile, kernel, mode="same")
        return profile, gray

    def _find_edge(self, profile: np.ndarray, target_x: int, window: int) -> EdgeDetection:
        n = len(profile)
        left = max(0, int(target_x - window))
        right = min(n, int(target_x + window + 1))
        if right <= left + 2:
            return EdgeDetection(None, 0.0, target_x, (left, right))

        segment = profile[left:right]
        idx = int(np.argmax(segment))
        x = left + idx
        peak = float(segment[idx])

        # Confianza relativa contra el ruido base de toda la ROI.
        median = float(np.median(profile))
        mad = float(np.median(np.abs(profile - median))) + 1e-6
        confidence = (peak - median) / (mad * 1.4826 + 1e-6)
        if confidence < 0:
            confidence = 0.0
        confidence = min(confidence, 999.0)
        return EdgeDetection(x, confidence, target_x, (left, right))

    def _check_references(self, gray_roi: np.ndarray, roi_x1: int) -> Tuple[bool, bool]:
        if not self.config.get("vision.reference_check_enabled", False):
            return True, True
        ref_window = int(self.config.get("vision.reference_search_window_px", 30))
        dark_threshold = int(self.config.get("vision.reference_dark_threshold", 70))
        min_ratio = float(self.config.get("vision.reference_min_dark_ratio", 0.08))
        left_x = int(self.config.get("calibration.left_reference_x", 0)) - roi_x1
        right_x = int(self.config.get("calibration.right_reference_x", 0)) - roi_x1
        return (
            self._is_dark_reference_visible(gray_roi, left_x, ref_window, dark_threshold, min_ratio),
            self._is_dark_reference_visible(gray_roi, right_x, ref_window, dark_threshold, min_ratio),
        )

    @staticmethod
    def _is_dark_reference_visible(gray_roi: np.ndarray, center_x: int, window: int, threshold: int, min_ratio: float) -> bool:
        h, w = gray_roi.shape[:2]
        left = max(0, center_x - window)
        right = min(w, center_x + window + 1)
        if right <= left:
            return False
        patch = gray_roi[:, left:right]
        dark_ratio = float(np.mean(patch < threshold))
        return dark_ratio >= min_ratio
