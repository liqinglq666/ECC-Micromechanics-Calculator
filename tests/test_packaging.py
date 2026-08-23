from __future__ import annotations

from pathlib import Path


def test_required_package_markers_exist() -> None:
    root = Path(__file__).resolve().parents[1]

    for package in ["core", "models", "ui", "utils"]:
        assert (root / package / "__init__.py").exists()
