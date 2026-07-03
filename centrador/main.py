from __future__ import annotations

import argparse
from pathlib import Path

from .app import run_app
from .logger_setup import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Centrador de papel para corrugadora con cámara USB + Arduino UNO")
    parser.add_argument("--config", default="config/config.yaml", help="Ruta al archivo YAML de configuración")
    parser.add_argument("--dry-run", action="store_true", help="Probar sin Arduino: no envía nada al puerto serie")
    args = parser.parse_args()

    base_dir = Path.cwd()
    logger = setup_logging(base_dir)
    logger.info("Iniciando Centrador Corrugadora | config=%s | dry_run=%s", args.config, args.dry_run)
    run_app(Path(args.config), logger, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
