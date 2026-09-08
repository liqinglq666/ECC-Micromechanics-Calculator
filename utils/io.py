"""CSV ingestion and lightweight result export helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import AnalysisResult


class DataLoadError(Exception):
    """Raised when a CSV cannot be parsed into a valid sigma-delta table."""


_REQUIRED_COLUMNS: tuple[str, str] = ("delta", "sigma")


def load_sigma_delta_csv(path: Path) -> pd.DataFrame:
    """Read, strictly validate, and provenance-tag a sigma-delta CSV.

    Scientific input is never silently repaired here. Invalid rows, duplicate
    crack openings, or non-monotonic crack openings are rejected so the user
    can correct the source data explicitly instead of analysing a modified
    curve without noticing.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise DataLoadError(f"Not a regular file: {path}")

    try:
        df = pd.read_csv(path, header=0)
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"The file is empty: {path}") from exc
    except pd.errors.ParserError as exc:
        raise DataLoadError(f"CSV parse error in {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise DataLoadError(
            f"Cannot decode {path} as UTF-8. Save the file as UTF-8 and retry."
        ) from exc
    except OSError as exc:
        raise DataLoadError(f"Cannot read {path}: {exc}") from exc

    normalized_columns = [str(column).strip().lower() for column in df.columns]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise DataLoadError(
            "Column names become duplicated after trimming/case normalization. "
            "Use one unique 'delta' column and one unique 'sigma' column."
        )
    df.columns = normalized_columns

    missing = [column for column in _REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise DataLoadError(
            f"Missing required column(s) {missing} in {path.name}. "
            "Expected headers: 'delta', 'sigma'."
        )

    df = df.loc[:, ["delta", "sigma"]].copy()
    if len(df) < 2:
        raise DataLoadError(f"{path.name} must contain at least 2 data rows.")

    numeric = df.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise DataLoadError(
            f"{path.name} contains missing or non-numeric values in 'delta'/'sigma'. "
            "Correct the source CSV instead of relying on automatic row removal."
        )

    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DataLoadError(
            f"{path.name} contains non-finite values (inf or -inf) in 'delta'/'sigma'."
        )
    if np.any(values < 0.0):
        raise DataLoadError(
            f"{path.name} contains negative delta or sigma values; both must be non-negative."
        )

    delta = numeric["delta"].to_numpy(dtype=float)
    if numeric["delta"].duplicated().any():
        duplicates = numeric.loc[numeric["delta"].duplicated(keep=False), "delta"].unique()
        preview = ", ".join(f"{value:g}" for value in duplicates[:5])
        suffix = "…" if len(duplicates) > 5 else ""
        raise DataLoadError(
            f"{path.name} contains duplicate delta values ({preview}{suffix}). "
            "Each crack-opening value must appear exactly once."
        )
    if np.any(np.diff(delta) <= 0.0):
        raise DataLoadError(
            f"{path.name} delta values must be strictly increasing in file order. "
            "Sort or correct the source CSV explicitly before import."
        )

    numeric = numeric.reset_index(drop=True)
    numeric.attrs["source"] = "csv"
    numeric.attrs["csv_path"] = str(path.resolve())
    numeric.attrs["validation"] = "strict"
    return numeric


_RESULT_COLUMNS: list[str] = [
    "Series",
    "Variable Value",
    "sigma0 (MPa)",
    "sigma_fc (MPa)",
    "PSH Strength",
    "K_m (MPa*m^0.5)",
    "J_tip (J/m^2)",
    "J_b' (J/m^2)",
    "PSH Energy",
]


def results_to_dataframe(results: list[AnalysisResult]) -> pd.DataFrame:
    """Convert analysis results into the compact table used by the GUI/CSV export."""
    rows = []
    for result in results:
        sigma_fc = result.sigma0 / result.psh_strength if result.psh_strength else float("nan")
        rows.append(
            {
                "Series": result.series_name,
                "Variable Value": result.variable_value,
                "sigma0 (MPa)": round(result.sigma0, 4),
                "sigma_fc (MPa)": round(sigma_fc, 4),
                "PSH Strength": round(result.psh_strength, 4),
                "K_m (MPa*m^0.5)": round(result.km, 4),
                "J_tip (J/m^2)": round(result.j_tip, 4),
                "J_b' (J/m^2)": round(result.jb_prime, 4),
                "PSH Energy": round(result.psh_energy, 4),
            }
        )
    return pd.DataFrame(rows, columns=_RESULT_COLUMNS)


def export_to_csv(results: list[AnalysisResult], path: Path) -> None:
    results_to_dataframe(results).to_csv(path, index=False, encoding="utf-8-sig")


def export_to_excel(results: list[AnalysisResult], path: Path) -> None:
    """Legacy single-sheet export retained for API compatibility."""
    try:
        results_to_dataframe(results).to_excel(path, index=False, engine="openpyxl")
    except ImportError as exc:
        raise DataLoadError(
            "openpyxl is required for Excel export. Run: pip install openpyxl"
        ) from exc
