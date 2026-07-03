from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np

from centrador.config import ConfigStore
from centrador.detector import PaperDetector


def make_frame(offset_px: int = 0, no_paper: bool = False) -> np.ndarray:
    frame = np.full((720, 1280, 3), 180, dtype=np.uint8)
    # referencias negras fijas
    cv2.rectangle(frame, (145, 0), (165, 719), (0, 0, 0), -1)
    cv2.rectangle(frame, (1125, 0), (1145, 719), (0, 0, 0), -1)
    if not no_paper:
        left = 420 + offset_px
        right = 860 + offset_px
        cv2.rectangle(frame, (left, 0), (right, 719), (235, 235, 235), -1)
        cv2.line(frame, (left, 0), (left, 719), (80, 80, 80), 2)
        cv2.line(frame, (right, 0), (right, 719), (80, 80, 80), 2)
    return frame


def main() -> None:
    cfg = ConfigStore.load("config/config.yaml")
    detector = PaperDetector(cfg)
    out = Path("logs/synthetic")
    out.mkdir(parents=True, exist_ok=True)
    for offset in [-80, -20, 0, 35, 90]:
        frame = make_frame(offset)
        result = detector.detect(frame)
        print(offset, result)
        cv2.imwrite(str(out / f"synthetic_{offset:+d}.jpg"), frame)
    for i in range(10):
        result = detector.detect(make_frame(no_paper=True))
    print("no_paper", result)


if __name__ == "__main__":
    main()
