from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np

from centrador.config import DEFAULT_CONFIG, ConfigStore
from centrador.detector import PaperDetector


def make_detector() -> PaperDetector:
    data = deepcopy(DEFAULT_CONFIG)
    data["calibration"]["left_reference_x"] = 150
    data["calibration"]["right_reference_x"] = 950
    data["calibration"]["ideal_center_x"] = 668.0
    data["vision"]["edge_min_confidence"] = 1.0
    data["vision"]["min_paper_width_px"] = 150
    data["vision"]["reject_edges_outside_references"] = True
    data["vision"]["reference_inner_margin_px"] = 20
    return PaperDetector(ConfigStore(Path("test.yml"), data))


def profile_with_edges(edges: dict[int, float], width: int = 1000) -> np.ndarray:
    profile = np.zeros(width, dtype=np.float32)
    for x, value in edges.items():
        profile[x] = value
    return profile


def paper_gray(left: int, right: int, width: int = 1000) -> np.ndarray:
    gray = np.full((80, width), 45, dtype=np.uint8)
    gray[:, left:right] = 180
    return gray


def test_rejects_strong_external_edge_outside_references() -> None:
    detector = make_detector()
    profile = profile_with_edges({80: 200.0, 439: 80.0, 897: 90.0})
    signed = np.zeros_like(profile)
    signed[80] = 200.0
    signed[439] = 80.0
    signed[897] = -90.0

    left, right = detector._find_paper_edges(profile, signed, paper_gray(439, 897), 0)

    assert left.x == 439
    assert right.x == 897


def test_rejects_pair_too_far_from_ideal_center_when_configured() -> None:
    detector = make_detector()
    detector.config.set("vision.reject_edges_outside_references", False)
    detector.config.set("vision.max_center_error_for_edge_pair_px", 80)
    profile = profile_with_edges({200: 200.0, 600: 190.0, 439: 80.0, 897: 90.0})
    signed = np.zeros_like(profile)
    signed[200] = 200.0
    signed[600] = -190.0
    signed[439] = 80.0
    signed[897] = -90.0

    left, right = detector._find_paper_edges(profile, signed, paper_gray(439, 897), 0)

    assert left.x == 439
    assert right.x == 897


def test_rejects_same_polarity_edge_pair() -> None:
    detector = make_detector()
    profile = profile_with_edges({439: 120.0, 897: 120.0})
    signed = np.zeros_like(profile)
    signed[439] = 120.0
    signed[897] = 120.0

    left, right = detector._find_paper_edges(profile, signed, paper_gray(439, 897), 0)

    assert left.x is None
    assert right.x is None
