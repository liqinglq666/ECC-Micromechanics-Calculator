from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from utils.io import DataLoadError, load_sigma_delta_csv


def test_load_sigma_delta_csv_tags_provenance(tmp_path: Path) -> None:
    path = tmp_path / "curve.csv"
    pd.DataFrame({"delta": [0.1, 0.0], "sigma": [2.0, 0.0]}).to_csv(path, index=False)

    df = load_sigma_delta_csv(path)

    assert list(df.columns) == ["delta", "sigma"]
    assert df["delta"].tolist() == [0.0, 0.1]
    assert df.attrs["source"] == "csv"
    assert df.attrs["csv_path"] == str(path)


def test_load_sigma_delta_csv_requires_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"x": [0.0], "y": [0.0]}).to_csv(path, index=False)

    with pytest.raises(DataLoadError, match="Missing required column"):
        load_sigma_delta_csv(path)
