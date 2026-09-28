"""Calibrate the explicitly selected model without changing which model starts next."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: calibrate_selected.py <strata-model.json>", file=sys.stderr)
        return 2
    cfg = Path(sys.argv[1]).resolve()
    if cfg.parent != ROOT or not cfg.name.startswith("strata-") or not cfg.is_file():
        print("Select an installed Strata model configuration in the project folder.", file=sys.stderr)
        return 2
    return 0 if setup.calibrate_config(cfg) else 1


if __name__ == "__main__":
    sys.exit(main())
