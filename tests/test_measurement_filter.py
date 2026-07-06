from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path

from centrador.config import DEFAULT_CONFIG, ConfigStore
from centrador.detector import DetectionResult
from centrador.measurement_filter import PaperMeasurementFilter


def make_config() -> ConfigStore:
    data = deepcopy(DEFAULT_CONFIG)
    data["vision_filter"]["min_samples"] = 4
    data["vision_filter"]["new_width_confirm_frames"] = 4
    data["vision_filter"]["hold_last_good_s"] = 0.5
    data["calibration"]["ideal_center_x"] = 640.0
    data["calibration"]["px_per_mm"] = 4.0
    return ConfigStore(Path("test.yml"), data)


def result(width: int | None, center: float | None = 640.0, valid: bool = True) -> DetectionResult:
    left = None if width is None or center is None else int(round(center - width / 2.0))
    right = None if width is None or center is None else int(round(center + width / 2.0))
    error_px = None if center is None or not valid else center - 640.0
    return DetectionResult(
        valid=valid,
        fault=None if valid else "BORDE_NO_DETECTADO",
        left_edge_x=left,
        right_edge_x=right,
        paper_center_x=center if valid else None,
        ideal_center_x=640.0,
        error_px=error_px,
        error_mm=None if error_px is None else error_px / 4.0,
        paper_width_px=width if valid else None,
        left_confidence=12.0,
        right_confidence=12.0,
        no_paper_counter=0 if valid else 1,
        roi=(0, 1280, 260, 460),
        left_ref_ok=True,
        right_ref_ok=True,
    )


def make_filter() -> PaperMeasurementFilter:
    return PaperMeasurementFilter(make_config(), logging.getLogger("test"))


def feed(filter_: PaperMeasurementFilter, widths: list[int], start: float = 0.0) -> DetectionResult:
    out = result(widths[-1])
    for i, width in enumerate(widths):
        out = filter_.update(result(width), now=start + i * 0.1)
    return out


def test_stable_sequence_filters_near_width() -> None:
    filter_ = make_filter()
    out = feed(filter_, [420, 421, 419, 420])
    assert out.valid
    assert out.filter_state == "STABLE"
    assert abs((out.paper_width_px or 0) - 420) <= 1


def test_false_double_width_jump_is_rejected() -> None:
    filter_ = make_filter()
    feed(filter_, [420, 421, 419, 420])
    out = filter_.update(result(840), now=0.5)
    out2 = filter_.update(result(839), now=0.6)
    assert out.valid and out2.valid
    assert out.filter_state == "OUTLIER_REJECTED"
    assert abs((out.paper_width_px or 0) - 420) <= 1
    assert abs((out2.paper_width_px or 0) - 420) <= 1
    assert out2.filter_rejected_count == 2


def test_consistent_new_width_is_accepted_after_confirmation() -> None:
    filter_ = make_filter()
    feed(filter_, [420, 421, 419, 420])
    out = result(420)
    for i in range(4):
        out = filter_.update(result(500), now=0.5 + i * 0.1)
    assert out.valid
    assert out.filter_state == "STABLE"
    assert abs((out.paper_width_px or 0) - 500) <= 1


def test_single_invalid_frame_holds_last_good() -> None:
    filter_ = make_filter()
    feed(filter_, [420, 421, 419, 420])
    out = filter_.update(result(None, None, valid=False), now=0.5)
    assert out.valid
    assert out.filter_state == "HOLD_LAST_GOOD"
    assert abs((out.paper_width_px or 0) - 420) <= 1


def test_persistent_invalid_frames_return_invalid_after_hold_time() -> None:
    filter_ = make_filter()
    feed(filter_, [420, 421, 419, 420])
    out = filter_.update(result(None, None, valid=False), now=1.2)
    assert not out.valid
    assert out.filter_state == "NO_PAPER"


def test_error_is_recalculated_from_filtered_center() -> None:
    filter_ = make_filter()
    feed(filter_, [420, 420, 420, 420])
    out = filter_.update(result(421, center=660.0), now=0.5)
    assert out.valid
    assert out.error_px == 0.0
    assert out.error_mm == 0.0
