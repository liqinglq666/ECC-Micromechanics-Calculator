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

    Cleaning steps (all vectorised, no row-level iteration):
      1. Strip whitespace from column names.
      2. Require exactly the two columns 'delta' and 'sigma'.
      3. Coerce to float64; non-numeric entries become NaN.
      4. Drop rows containing NaN or Inf.
      5. Drop rows where delta < 0 or sigma < 0.
         NOTE: delta == 0 is intentionally kept — it represents the physically
         meaningful initial state (crack not yet opened) and must not be
         discarded.
      6. Sort ascending by delta, then drop duplicate delta values
         (keeps the first occurrence, i.e. the lower sigma on the way up).
      7. Require at least 2 rows to survive cleaning.

    Returns a clean DataFrame with columns ['delta', 'sigma'].
    Raises DataLoadError on any validation failure.
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

    # Normalise header
    df.columns = df.columns.str.strip().str.lower()

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataLoadError(
            f"Missing required column(s) {missing} in {path.name}. "
            "Expected headers: 'delta', 'sigma'."
        )

    df = df[["delta", "sigma"]].copy()

    # Coerce and drop non-finite rows
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna()

    # Reject physically impossible negative values.
    # >= 0 is intentional: delta == 0 (uncracked state) is a valid data point.
    df = df.loc[(df["delta"] >= 0.0) & (df["sigma"] >= 0.0)]

    # Sort and deduplicate on delta
    df = (
        df.sort_values("delta")
        .drop_duplicates(subset="delta")
        .reset_index(drop=True)
    )

    if len(df) < 2:
        raise DataLoadError(
            f"After cleaning, {path.name} has fewer than 2 valid rows. "
            "Check for negative values, duplicates, or non-numeric entries."
        )

    return df


# ---------------------------------------------------------------------------
# Export helpers
#
# NOTE: These helpers produce a single-sheet lightweight export suitable for
# quick inspection or copy-paste into a report.
# For the full three-sheet project export (Summary / Sigma-Delta Curves /
# Settings Log) use utils.export.DataExportWorker instead.
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
    """
    Convert a list of AnalysisResult objects into a tidy DataFrame.

    sigma_fc is back-calculated as sigma0 / psh_strength.  When psh_strength
    is zero (pathological input) the cell is filled with NaN rather than
    silently producing a wrong value.
    """
    rows = [
        {
            "Series": r.series_name,
            "Variable Value": r.variable_value,
            "sigma0 (MPa)": round(r.sigma0, 4),
            # BUG-FIX: replaced `r.psh_strength and r.sigma0 / r.psh_strength`
            # (Python and-shortcut that returns int 0 on falsy psh_strength)
            # with an explicit guard that produces NaN on zero.
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
    """
    Write results DataFrame to a single-sheet Excel file (.xlsx).

    Requires openpyxl: pip install openpyxl

    NOTE: This writes only the summary sheet.  Use utils.export.DataExportWorker
    for the full three-sheet project workbook.
    """
    try:
        results_to_dataframe(results).to_excel(path, index=False, engine="openpyxl")
    except ImportError as exc:
        raise DataLoadError(
            "openpyxl is required for Excel export. Run: pip install openpyxl"
        ) from exc
