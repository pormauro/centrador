from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Optional

from .config import ConfigStore
from .detector import DetectionResult


@dataclass
class _MeasurementSample:
    timestamp: float
    left_edge_x: int
    right_edge_x: int
    paper_center_x: float
    paper_width_px: int
    error_px: float
    left_confidence: float
    right_confidence: float


class PaperMeasurementFilter:
    def __init__(self, config: ConfigStore, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild("measurement_filter")
        self._samples: deque[_MeasurementSample] = deque()
        self._candidate_samples: deque[_MeasurementSample] = deque()
        self._last_good_result: Optional[DetectionResult] = None
        self._last_good_time: Optional[float] = None
        self._rejected_count = 0
        self._was_stable = False

    def update_config(self, config: ConfigStore) -> None:
        self.config = config
        self._prune(time.monotonic())

    def reset(self) -> None:
        self._samples.clear()
        self._candidate_samples.clear()
        self._last_good_result = None
        self._last_good_time = None
        self._was_stable = False

    def update(self, raw_result: DetectionResult, now: float | None = None) -> DetectionResult:
        now = time.monotonic() if now is None else now
        self._prune(now)

        if not raw_result.valid or not self._has_full_measurement(raw_result):
            return self._handle_invalid(raw_result, now)

        raw_sample = self._sample_from_result(raw_result, now)
        stable_sample = self._stable_sample()
        stable = stable_sample is not None and len(self._samples) >= self._min_samples()

        if stable and stable_sample is not None and self._is_outlier(raw_sample, stable_sample):
            self._rejected_count += 1
            if self._candidate_confirms_new_width(raw_sample, now):
                self._accept_confirmed_width(now)
                self.logger.info(
                    "Nuevo ancho aceptado por confirmacion: raw_width=%s muestras=%s",
                    raw_sample.paper_width_px,
                    len(self._samples),
                )
                return self._filtered_result(raw_result, "STABLE")
            self._log_rejection(raw_sample, stable_sample)
            return self._hold_result(raw_result, "OUTLIER_REJECTED", now)

        self._candidate_samples.clear()
        self._samples.append(raw_sample)
        self._prune(now)
        state = "STABLE" if len(self._samples) >= self._min_samples() else "WARMUP"
        if state == "STABLE" and not self._was_stable:
            self.logger.info("Filtro de medicion estable: muestras=%s ancho=%.1f", len(self._samples), self._stable_sample().paper_width_px if self._stable_sample() else raw_sample.paper_width_px)
        self._was_stable = state == "STABLE"
        return self._filtered_result(raw_result, state)

    def _handle_invalid(self, raw_result: DetectionResult, now: float) -> DetectionResult:
        self._candidate_samples.clear()
        hold_s = float(self.config.get("vision_filter.hold_last_good_s", 0.8))
        if self._last_good_result is not None and self._last_good_time is not None and now - self._last_good_time <= hold_s:
            return self._hold_result(raw_result, "HOLD_LAST_GOOD", now)
        return replace(
            raw_result,
            raw_paper_width_px=raw_result.paper_width_px,
            raw_paper_center_x=raw_result.paper_center_x,
            filtered=True,
            filter_state="NO_PAPER" if raw_result.fault else "INVALID",
            filter_sample_count=len(self._samples),
            filter_rejected_count=self._rejected_count,
        )

    def _hold_result(self, raw_result: DetectionResult, state: str, now: float) -> DetectionResult:
        if self._last_good_result is None:
            return replace(
                raw_result,
                raw_paper_width_px=raw_result.paper_width_px,
                raw_paper_center_x=raw_result.paper_center_x,
                filtered=True,
                filter_state=state,
                filter_sample_count=len(self._samples),
                filter_rejected_count=self._rejected_count,
            )
        return replace(
            self._last_good_result,
            raw_paper_width_px=raw_result.paper_width_px,
            raw_paper_center_x=raw_result.paper_center_x,
            filtered=True,
            filter_state=state,
            filter_sample_count=len(self._samples),
            filter_rejected_count=self._rejected_count,
        )

    def _filtered_result(self, raw_result: DetectionResult, state: str) -> DetectionResult:
        stable = self._stable_sample()
        if stable is None:
            return replace(raw_result, raw_paper_width_px=raw_result.paper_width_px, raw_paper_center_x=raw_result.paper_center_x, filtered=True, filter_state=state, filter_sample_count=0, filter_rejected_count=self._rejected_count)
        px_per_mm = float(self.config.get("calibration.px_per_mm", 1.0)) or 1.0
        error_px = stable.paper_center_x - raw_result.ideal_center_x
        result = replace(
            raw_result,
            valid=True,
            fault=None,
            left_edge_x=int(round(stable.left_edge_x)),
            right_edge_x=int(round(stable.right_edge_x)),
            paper_center_x=float(stable.paper_center_x),
            error_px=float(error_px),
            error_mm=float(error_px / px_per_mm),
            paper_width_px=int(round(stable.paper_width_px)),
            left_confidence=float(stable.left_confidence),
            right_confidence=float(stable.right_confidence),
            raw_paper_width_px=raw_result.paper_width_px,
            raw_paper_center_x=raw_result.paper_center_x,
            filtered=True,
            filter_state=state,
            filter_sample_count=len(self._samples),
            filter_rejected_count=self._rejected_count,
        )
        self._last_good_result = result
        self._last_good_time = stable.timestamp
        return result

    def _is_outlier(self, raw: _MeasurementSample, stable: _MeasurementSample) -> bool:
        width_diff = abs(raw.paper_width_px - stable.paper_width_px)
        width_jump_px = float(self.config.get("vision_filter.width_jump_px", 80))
        width_jump_ratio = float(self.config.get("vision_filter.width_jump_ratio", 0.22))
        ratio = max(raw.paper_width_px, stable.paper_width_px) / max(1.0, min(raw.paper_width_px, stable.paper_width_px))
        double_ratio = float(self.config.get("vision_filter.double_width_reject_ratio", 1.35))
        center_jump = abs(raw.paper_center_x - stable.paper_center_x)
        center_limit = float(self.config.get("vision_filter.center_jump_px", 90))
        relative_jump = width_diff / max(1.0, stable.paper_width_px)
        return width_diff >= width_jump_px or relative_jump > width_jump_ratio or ratio >= double_ratio or center_jump > center_limit

    def _candidate_confirms_new_width(self, raw: _MeasurementSample, now: float) -> bool:
        confirm_frames = max(1, int(self.config.get("vision_filter.new_width_confirm_frames", 12)))
        if self._candidate_samples:
            candidate_stable = self._aggregate(self._candidate_samples)
            if candidate_stable is not None and self._is_outlier(raw, candidate_stable):
                self._candidate_samples.clear()
        self._candidate_samples.append(raw)
        self._prune_candidates(now)
        return len(self._candidate_samples) >= confirm_frames

    def _accept_confirmed_width(self, now: float) -> None:
        self._samples.clear()
        self._samples.extend(self._candidate_samples)
        self._candidate_samples.clear()
        self._was_stable = len(self._samples) >= self._min_samples()
        self._prune(now)

    def _log_rejection(self, raw: _MeasurementSample, stable: _MeasurementSample) -> None:
        if not bool(self.config.get("vision_filter.log_rejected_samples", True)):
            return
        if self._rejected_count <= 3 or self._rejected_count % 10 == 0:
            ratio = raw.paper_width_px / max(1.0, stable.paper_width_px)
            self.logger.warning(
                "Muestra rechazada: raw_width=%s stable_width=%.1f ratio=%.2f raw_center=%.1f stable_center=%.1f rechazos=%s",
                raw.paper_width_px,
                stable.paper_width_px,
                ratio,
                raw.paper_center_x,
                stable.paper_center_x,
                self._rejected_count,
            )

    def _stable_sample(self) -> Optional[_MeasurementSample]:
        return self._aggregate(self._samples)

    def _aggregate(self, samples: deque[_MeasurementSample]) -> Optional[_MeasurementSample]:
        if not samples:
            return None
        values = list(samples)

        def median(attr: str) -> float:
            return float(statistics.median(getattr(s, attr) for s in values))

        return _MeasurementSample(
            timestamp=max(s.timestamp for s in values),
            left_edge_x=int(round(median("left_edge_x"))),
            right_edge_x=int(round(median("right_edge_x"))),
            paper_center_x=median("paper_center_x"),
            paper_width_px=int(round(median("paper_width_px"))),
            error_px=median("error_px"),
            left_confidence=median("left_confidence"),
            right_confidence=median("right_confidence"),
        )

    def _sample_from_result(self, result: DetectionResult, now: float) -> _MeasurementSample:
        return _MeasurementSample(
            timestamp=now,
            left_edge_x=int(result.left_edge_x or 0),
            right_edge_x=int(result.right_edge_x or 0),
            paper_center_x=float(result.paper_center_x or 0.0),
            paper_width_px=int(result.paper_width_px or 0),
            error_px=float(result.error_px or 0.0),
            left_confidence=float(result.left_confidence),
            right_confidence=float(result.right_confidence),
        )

    def _has_full_measurement(self, result: DetectionResult) -> bool:
        return result.left_edge_x is not None and result.right_edge_x is not None and result.paper_center_x is not None and result.paper_width_px is not None and result.error_px is not None

    def _prune(self, now: float) -> None:
        max_age = min(float(self.config.get("vision_filter.window_s", 1.5)), float(self.config.get("vision_filter.max_sample_age_s", 2.0)))
        while self._samples and now - self._samples[0].timestamp > max_age:
            self._samples.popleft()
        self._prune_candidates(now)

    def _prune_candidates(self, now: float) -> None:
        max_age = float(self.config.get("vision_filter.max_sample_age_s", 2.0))
        while self._candidate_samples and now - self._candidate_samples[0].timestamp > max_age:
            self._candidate_samples.popleft()

    def _min_samples(self) -> int:
        return max(1, int(self.config.get("vision_filter.min_samples", 5)))
