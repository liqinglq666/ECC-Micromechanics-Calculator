from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from utils.io import DataLoadError, load_sigma_delta_csv


def test_load_sigma_delta_csv_tags_provenance(tmp_path: Path) -> None:
    path = tmp_path / "curve.csv"
    pd.DataFrame({"delta": [0.0, 0.1], "sigma": [0.0, 2.0]}).to_csv(path, index=False)

    df = load_sigma_delta_csv(path)

    assert list(df.columns) == ["delta", "sigma"]
    assert df["delta"].tolist() == [0.0, 0.1]
    assert df.attrs["source"] == "csv"
    assert df.attrs["csv_path"] == str(path.resolve())
    assert df.attrs["validation"] == "strict"


def test_load_sigma_delta_csv_requires_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"x": [0.0], "y": [0.0]}).to_csv(path, index=False)

    with pytest.raises(DataLoadError, match="Missing required column"):
        load_sigma_delta_csv(path)


def test_load_sigma_delta_csv_rejects_normalized_duplicate_columns(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-columns.csv"
    path.write_text("delta, Delta ,sigma\n0,0,0\n0.1,0.1,1\n", encoding="utf-8")

    with pytest.raises(DataLoadError, match="duplicated"):
        load_sigma_delta_csv(path)


def test_load_sigma_delta_csv_rejects_non_monotonic_delta_instead_of_sorting(tmp_path: Path) -> None:
    path = tmp_path / "unsorted.csv"
    pd.DataFrame({"delta": [0.1, 0.0], "sigma": [2.0, 0.0]}).to_csv(path, index=False)

    with pytest.raises(DataLoadError, match="strictly increasing"):
        load_sigma_delta_csv(path)


def test_load_sigma_delta_csv_rejects_duplicate_delta_instead_of_dropping_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicate-delta.csv"
    pd.DataFrame({"delta": [0.0, 0.1, 0.1], "sigma": [0.0, 1.0, 1.1]}).to_csv(
        path, index=False
    )

    with pytest.raises(DataLoadError, match="duplicate delta"):
        load_sigma_delta_csv(path)


def test_load_sigma_delta_csv_rejects_non_numeric_rows_instead_of_dropping_them(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nonnumeric.csv"
    path.write_text("delta,sigma\n0,0\n0.1,bad\n0.2,2\n", encoding="utf-8")

    with pytest.raises(DataLoadError, match="missing or non-numeric"):
        load_sigma_delta_csv(path)


def test_load_sigma_delta_csv_rejects_negative_values(tmp_path: Path) -> None:
    path = tmp_path / "negative.csv"
    pd.DataFrame({"delta": [0.0, 0.1], "sigma": [0.0, -1.0]}).to_csv(path, index=False)

    with pytest.raises(DataLoadError, match="negative"):
        load_sigma_delta_csv(path)
