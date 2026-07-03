from __future__ import annotations

import argparse
from pathlib import Path
import cv2


def main() -> None:
    parser = argparse.ArgumentParser(description="Detecta cámaras USB disponibles y guarda capturas de prueba.")
    parser.add_argument("--max-index", type=int, default=6)
    parser.add_argument("--out", default="logs/camera_probe")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print("Buscando cámaras...")
    for idx in range(args.max_index + 1):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"[{idx}] no abre")
            continue
        ok, frame = cap.read()
        if not ok or frame is None:
            print(f"[{idx}] abre pero no entrega frame")
            cap.release()
            continue
        h, w = frame.shape[:2]
        path = out / f"camera_{idx}_{w}x{h}.jpg"
        cv2.imwrite(str(path), frame)
        print(f"[{idx}] OK {w}x{h} -> {path}")
        cap.release()
    print("Listo. Abrí las imágenes generadas para elegir camera.index.")


if __name__ == "__main__":
    main()
