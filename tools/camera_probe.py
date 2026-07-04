from __future__ import annotations

import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from centrador.camera_discovery import scan_cameras


def main() -> None:
    parser = argparse.ArgumentParser(description="Detecta cámaras USB disponibles y guarda capturas de prueba.")
    parser.add_argument("--max-index", type=int, default=6)
    parser.add_argument("--out", default="logs/camera_probe")
    parser.add_argument("--backend", choices=["dshow", "msmf", "default"], default="dshow")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Buscando cámaras con backend={args.backend}...")
    for info in scan_cameras(max_index=args.max_index, backend=args.backend, keep_frames=True):
        if not info.available or info.frame is None:
            detail = f": {info.error}" if info.error else ""
            print(f"[{info.index}] no disponible{detail}")
            continue
        path = out / f"camera_{info.index}_{info.width}x{info.height}.jpg"
        cv2.imwrite(str(path), info.frame)
        print(f"[{info.index}] OK {info.width}x{info.height} -> {path}")
    print("Listo. También podés elegir la cámara desde la pantalla principal con Buscar cámaras.")


if __name__ == "__main__":
    main()
