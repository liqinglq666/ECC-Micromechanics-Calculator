"""utils/io.py

CSV ingestion with a strict data-cleaning pipeline, plus DataFrame export
helpers for the summary table.

All file-path handling uses pathlib.Path exclusively.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.engine import AnalysisResult


# ---------------------------------------------------------------------------
# Custom exception so callers can catch domain errors without bare excepts
# ---------------------------------------------------------------------------

class DataLoadError(Exception):
    """Raised when a CSV cannot be parsed into a valid sigma-delta table."""


# ---------------------------------------------------------------------------
# CSV reader + cleaning pipeline
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS: tuple[str, str] = ("delta", "sigma")


def load_sigma_delta_csv(path: Path) -> pd.DataFrame:
    """
    Read and validate a two-column sigma-delta CSV.

    Cleaning steps:
      1. Strip whitespace from column names.
      2. Require columns 'delta' and 'sigma'.
      3. Coerce to float64; non-numeric entries become NaN.
      4. Drop rows containing NaN or Inf.
      5. Drop rows where delta < 0 or sigma < 0.
      6. Sort ascending by delta, then drop duplicate delta values.
      7. Require at least 2 rows to survive cleaning.

    Returns a clean DataFrame with columns ['delta', 'sigma'] and attrs['source']
    set to 'csv'.  That provenance tag is validated before analysis so the UI
    cannot accidentally run a CSV-mode analysis on a simulated curve, or vice versa.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

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

    df.columns = df.columns.str.strip().str.lower()

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataLoadError(
            f"Missing required column(s) {missing} in {path.name}. "
            "Expected headers: 'delta', 'sigma'."
        )

    df = df[["delta", "sigma"]].copy()
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna()
    df = df.loc[(df["delta"] >= 0.0) & (df["sigma"] >= 0.0)]

    df = (
        df.sort_values("delta")
        .drop_duplicates(subset="delta", keep="first")
        .reset_index(drop=True)
    )

    if len(df) < 2:
        raise DataLoadError(
            f"After cleaning, {path.name} has fewer than 2 valid rows. "
            "Check for negative values, duplicates, or non-numeric entries."
        )

    df.attrs["source"] = "csv"
    df.attrs["csv_path"] = str(path)
    return df


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

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
    """Convert a list of AnalysisResult objects into a tidy DataFrame."""
    rows = [
        {
            "Series": r.series_name,
            "Variable Value": r.variable_value,
            "sigma0 (MPa)": round(r.sigma0, 4),
            "sigma_fc (MPa)": round(
                r.sigma0 / r.psh_strength if r.psh_strength else float("nan"), 4
            ),
            "PSH Strength": round(r.psh_strength, 4),
            "K_m (MPa*m^0.5)": round(r.km, 4),
            "J_tip (J/m^2)": round(r.j_tip, 4),
            "J_b' (J/m^2)": round(r.jb_prime, 4),
            "PSH Energy": round(r.psh_energy, 4),
        }
        for r in results
    ]
    return pd.DataFrame(rows, columns=_RESULT_COLUMNS)


def export_to_csv(results: list[AnalysisResult], path: Path) -> None:
    """Write results DataFrame to a UTF-8 CSV file."""
    results_to_dataframe(results).to_csv(path, index=False, encoding="utf-8-sig")


def export_to_excel(results: list[AnalysisResult], path: Path) -> None:
    """Write results DataFrame to a single-sheet Excel file (.xlsx)."""
    try:
        results_to_dataframe(results).to_excel(path, index=False, engine="openpyxl")
    except ImportError as exc:
        raise DataLoadError(
            "openpyxl is required for Excel export. Run: pip install openpyxl"
        ) from exc
