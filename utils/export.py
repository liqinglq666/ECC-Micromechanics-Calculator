"""Multi-sheet Excel export for ECC Micromechanics Calculator."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from PySide6.QtCore import QThread, Signal

from core.engine import AnalysisResult
from models.project import ProjectModel

_log = logging.getLogger(__name__)

_SIM_PARAM_FIELDS: list[tuple[str, str]] = [
    ("sim_fiber_type", "Fiber Type"),
    ("sim_V_f", "V_f (vol. fraction)"),
    ("sim_L_f", "L_f (mm)"),
    ("sim_E_f", "E_f (GPa)"),
    ("sim_sigma_fu", "sigma_fu (MPa)"),
    ("sim_G_d", "G_d (J/m^2)"),
    ("sim_beta", "beta (slip-hardening)"),
    ("sim_f_snubbing", "f_snubbing"),
    ("sim_tau0_override", "tau0 override (MPa)"),
    ("sim_f_strength_reduction", "f' strength reduction"),
    ("sim_orientation", "Fiber Orientation"),
    ("sim_n_delta_points", "Curve Points"),
    ("sim_P_anchor_max", "P_anchor_max (N)"),
    ("sim_delta_hook", "delta_hook (mm)"),
]


def build_summary_df(model: ProjectModel) -> pd.DataFrame:
    rows: list[dict] = []
    for entry in model:
        if entry.result is None:
            continue
        result = entry.result
        params = entry.params
        rows.append(
            {
                "Series ID": entry.series_id,
                "Series Name": params.name,
                "Variable Name": model.variable_name,
                "Variable Value": round(params.variable_value, 3),
                "tau0 (MPa)": round(result.tau0, 3),
                "E_m (GPa)": round(params.e_m, 3),
                "Fracture Condition": params.fracture_condition,
                "Poisson Ratio": round(params.poisson_ratio, 3),
                "K_m (MPa*m^0.5)": round(result.km, 3),
                "sigma_fc (MPa)": round(params.sigma_fc, 3),
                "J_tip (J/m^2)": round(result.j_tip, 3),
                "sigma0 (MPa)": round(result.sigma0, 3),
                "delta0 (mm)": round(result.delta0, 3),
                "J_b' (J/m^2)": round(result.jb_prime, 3),
                "PSH Strength": round(result.psh_strength, 3),
                "PSH Energy": round(result.psh_energy, 3),
            }
        )

    columns = [
        "Series ID",
        "Series Name",
        "Variable Name",
        "Variable Value",
        "tau0 (MPa)",
        "E_m (GPa)",
        "Fracture Condition",
        "Poisson Ratio",
        "K_m (MPa*m^0.5)",
        "sigma_fc (MPa)",
        "J_tip (J/m^2)",
        "sigma0 (MPa)",
        "delta0 (mm)",
        "J_b' (J/m^2)",
        "PSH Strength",
        "PSH Energy",
    ]
    return pd.DataFrame(rows, columns=columns)


def build_sigma_delta_df(model: ProjectModel) -> pd.DataFrame:
    column_pairs: list[pd.DataFrame] = []
    for entry in model:
        df = entry.params.sigma_delta_df
        if df is None or df.empty:
            continue
        name = entry.params.name
        column_pairs.append(
            pd.DataFrame(
                {
                    f"{name}_delta (mm)": df["delta"].reset_index(drop=True),
                    f"{name}_sigma (MPa)": df["sigma"].reset_index(drop=True),
                }
            )
        )
    return pd.concat(column_pairs, axis=1) if column_pairs else pd.DataFrame()


def build_settings_log_df(model: ProjectModel) -> pd.DataFrame:
    rows: list[dict] = []
    for entry in model:
        params = entry.params
        df = params.sigma_delta_df
        row: dict = {
            "Series ID": entry.series_id,
            "Series Name": params.name,
            "Selected Bridging Mode": params.sigma_delta_mode,
            "Active Curve Source": params.sigma_delta_source,
            "CSV Path": str(params.sigma_delta_path) if params.sigma_delta_path else "",
            "Curve Source Attr": df.attrs.get("source", "") if df is not None else "",
            "Simulation Signature": (
                df.attrs.get("simulation_signature", "") if df is not None else ""
            ),
            "Model Version": df.attrs.get("model_version", "") if df is not None else "",
            "P_peak (N)": params.p_peak,
            "d_f (mm)": params.d_f,
            "L_e (mm)": params.l_e,
            "P_max (N)": params.p_max,
            "Span S (mm)": params.span,
            "Width b (mm)": params.b,
            "Depth d (mm)": params.d,
            "Notch a0 (mm)": params.a0,
            "E_m (GPa)": params.e_m,
            "Fracture Condition": params.fracture_condition,
            "Poisson Ratio": params.poisson_ratio,
            "sigma_fc (MPa)": params.sigma_fc,
        }
        for attr, column in _SIM_PARAM_FIELDS:
            row[column] = getattr(params, attr, np.nan)
            if not hasattr(params, attr):
                _log.warning("SeriesParams missing %r; exporting NaN", attr)
        rows.append(row)

    if rows:
        return pd.DataFrame(rows)

    return pd.DataFrame(
        columns=[
            "Series ID",
            "Series Name",
            "Selected Bridging Mode",
            "Active Curve Source",
            "CSV Path",
            "Curve Source Attr",
            "Simulation Signature",
            "Model Version",
            "P_peak (N)",
            "d_f (mm)",
            "L_e (mm)",
            "P_max (N)",
            "Span S (mm)",
            "Width b (mm)",
            "Depth d (mm)",
            "Notch a0 (mm)",
            "E_m (GPa)",
            "Fracture Condition",
            "Poisson Ratio",
            "sigma_fc (MPa)",
            *[column for _, column in _SIM_PARAM_FIELDS],
        ]
    )


def write_excel(
    path: Path,
    summary_df: pd.DataFrame,
    sigma_delta_df: pd.DataFrame,
    settings_df: pd.DataFrame,
) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary_Results", index=False)
        sigma_delta_df.to_excel(writer, sheet_name="Sigma_Delta_Curves", index=False)
        settings_df.to_excel(writer, sheet_name="Project_Settings_Log", index=False)

        workbook = writer.book
        pass_fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
        fail_fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")

        for worksheet in workbook.worksheets:
            worksheet.freeze_panes = "A2"
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")

            for column_cells in worksheet.columns:
                col_letter = column_cells[0].column_letter
                max_length = max(
                    (len(str(cell.value)) for cell in column_cells if cell.value is not None),
                    default=0,
                )
                worksheet.column_dimensions[col_letter].width = min(max_length + 2.5, 60)

            if worksheet.title != "Summary_Results":
                continue

            headers = {cell.value: cell.column for cell in worksheet[1]}
            strength_col = headers.get("PSH Strength")
            energy_col = headers.get("PSH Energy")
            for row in range(2, worksheet.max_row + 1):
                for column, threshold in (
                    (strength_col, AnalysisResult.PSH_STRENGTH_THRESHOLD),
                    (energy_col, AnalysisResult.PSH_ENERGY_THRESHOLD),
                ):
                    if not column:
                        continue
                    cell = worksheet.cell(row=row, column=column)
                    try:
                        value = float(cell.value)
                    except (TypeError, ValueError):
                        continue
                    cell.fill = pass_fill if value >= threshold else fail_fill


class DataExportWorker(QThread):
    """Own all Excel disk I/O off the GUI thread."""

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, model: ProjectModel, output_path: Path) -> None:
        super().__init__()
        # Snapshot dataframes on the GUI thread so the worker never reads a
        # model that may be edited concurrently.
        self._summary_df = build_summary_df(model)
        self._sigma_delta_df = build_sigma_delta_df(model)
        self._settings_df = build_settings_log_df(model)
        self._output_path = output_path.resolve()

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            self.progress.emit(20, "Writing Summary_Results…")
            self.progress.emit(50, "Writing Sigma_Delta_Curves…")
            self.progress.emit(75, "Writing Project_Settings_Log…")
            write_excel(
                self._output_path,
                self._summary_df,
                self._sigma_delta_df,
                self._settings_df,
            )
        except PermissionError:
            self.failed.emit(
                f"Export failed: '{self._output_path.name}' is open in another application. "
                "Please close it and try again."
            )
            return
        except OSError as exc:
            self.failed.emit(f"Export failed (I/O error): {exc}")
            return
        except Exception as exc:
            self.failed.emit(f"Export failed (unexpected): {exc}")
            return

        if self.isInterruptionRequested():
            return
        self.progress.emit(100, "Done.")
        self.succeeded.emit(self._output_path)
