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
    """Read, clean, validate, and provenance-tag a sigma-delta CSV."""
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
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    df = df.loc[(df["delta"] >= 0.0) & (df["sigma"] >= 0.0)]
    df = (
        df.sort_values("delta")
        .drop_duplicates(subset="delta", keep="first")
        .reset_index(drop=True)
    )

    if len(df) < 2:
        raise DataLoadError(
            f"After cleaning, {path.name} has fewer than 2 valid rows. "
            "Check negative values, duplicates, or non-numeric entries."
        )

    df.attrs["source"] = "csv"
    df.attrs["csv_path"] = str(path.resolve())
    return df


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
        sigma_fc = (
            result.sigma0 / result.psh_strength
            if result.psh_strength
            else float("nan")
        )
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
