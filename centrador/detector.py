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
    raw_paper_width_px: Optional[int] = None
    raw_paper_center_x: Optional[float] = None
    filtered: bool = False
    filter_state: str = ""
    filter_sample_count: int = 0
    filter_rejected_count: int = 0


class PaperDetector:
    """Detecta automaticamente los dos bordes reales del papel en la ROI.

    Estrategia:
    - Recorta una ROI horizontal.
    - Convierte a gris y calcula gradiente vertical con Sobel X.
    - Promedia el gradiente por columna.
    - Busca candidatos de borde en toda la ROI, sin depender del ancho ideal anterior.
    - Elige el par confiable que mejor representa el papel y valida el ancho.

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

        profile, signed_profile, gray = self._edge_profile(roi)
        min_conf = float(self.config.get("vision.edge_min_confidence", 4.0))

        if bool(self.config.get("vision.auto_edge_detection_enabled", True)):
            left, right = self._find_paper_edges(profile, signed_profile, x1)
        else:
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

    def _edge_profile(self, roi_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        profile = np.mean(np.abs(sobel_x), axis=0)
        signed_profile = np.mean(sobel_x, axis=0)
        smooth_window = int(self.config.get("vision.profile_smooth_window", 13))
        if smooth_window > 1:
            if smooth_window % 2 == 0:
                smooth_window += 1
            kernel = np.ones(smooth_window, dtype=np.float32) / float(smooth_window)
            profile = np.convolve(profile, kernel, mode="same")
            signed_profile = np.convolve(signed_profile, kernel, mode="same")
        return profile, signed_profile, gray

    def _find_paper_edges(self, profile: np.ndarray, signed_profile: np.ndarray, roi_x1: int) -> Tuple[EdgeDetection, EdgeDetection]:
        candidates = self._edge_candidates(profile)
        if len(candidates) < 2:
            return EdgeDetection(None, 0.0, 0, (0, len(profile))), EdgeDetection(None, 0.0, len(profile) - 1, (0, len(profile)))

        min_width = int(self.config.get("vision.min_paper_width_px", 150))
        max_width = int(self.config.get("vision.max_paper_width_px", 0))
        pair_min = int(self.config.get("vision.edge_pair_min_separation_px", 0))
        pair_max = int(self.config.get("vision.edge_pair_max_separation_px", 0))
        min_sep = max(min_width, pair_min)
        max_sep = max_width if max_width > 0 else pair_max
        ideal_center = self.config.ideal_center_x()
        best: Optional[tuple[float, EdgeDetection, EdgeDetection]] = None

        for i, left in enumerate(candidates[:-1]):
            for right in candidates[i + 1 :]:
                width = int((right.x or 0) - (left.x or 0))
                if width < min_sep:
                    continue
                if max_sep > 0 and width > max_sep:
                    continue
                internal = [c for c in candidates if left.x is not None and right.x is not None and left.x < (c.x or 0) < right.x]
                center = ((left.x or 0) + (right.x or 0)) / 2.0 + roi_x1
                center_penalty = abs(center - ideal_center) / max(1.0, len(profile))
                orientation_bonus = 2.0 if signed_profile[left.x or 0] * signed_profile[right.x or 0] < 0 else 0.0
                internal_penalty = sum(c.confidence for c in internal) * 0.7
                score = min(left.confidence, right.confidence) * 4.0 + (left.confidence + right.confidence) * 0.5 + orientation_bonus - internal_penalty - center_penalty
                if best is None or score > best[0]:
                    best = (score, left, right)

        if best is None:
            return EdgeDetection(None, 0.0, 0, (0, len(profile))), EdgeDetection(None, 0.0, len(profile) - 1, (0, len(profile)))
        return best[1], best[2]

    def _edge_candidates(self, profile: np.ndarray) -> list[EdgeDetection]:
        n = len(profile)
        margin = max(0, int(self.config.get("vision.edge_exclusion_margin_px", 25)))
        min_conf = float(self.config.get("vision.edge_min_confidence", 4.0))
        median = float(np.median(profile))
        mad = float(np.median(np.abs(profile - median))) + 1e-6
        noise = mad * 1.4826 + 1e-6
        raw: list[EdgeDetection] = []
        for x in range(max(1, margin), min(n - 1, n - margin)):
            if profile[x] < profile[x - 1] or profile[x] < profile[x + 1]:
                continue
            confidence = max(0.0, float(profile[x] - median) / noise)
            if confidence >= min_conf:
                raw.append(EdgeDetection(x, min(confidence, 999.0), x, (max(0, x - 1), min(n, x + 2))))

        min_distance = max(3, int(self.config.get("vision.profile_smooth_window", 13)) // 2)
        selected: list[EdgeDetection] = []
        for candidate in sorted(raw, key=lambda c: c.confidence, reverse=True):
            if all(abs((candidate.x or 0) - (existing.x or 0)) >= min_distance for existing in selected):
                selected.append(candidate)
        return sorted(selected, key=lambda c: c.x or 0)

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
