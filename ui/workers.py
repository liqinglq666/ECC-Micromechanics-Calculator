"""ui/workers.py

QThread workers for all blocking IO and computation.
The main thread must never call engine or file-IO functions directly.

Signal contracts:
  CsvLoaderWorker
    loaded(series_index: int, df: pd.DataFrame, path: Path)
    error(series_index: int, message: str)

  BatchAnalysisWorker
    series_done(index: int, result: AnalysisResult)
    progress(current: int, total: int)
    finished()
    error(index: int, message: str)

  SimulationWorker
    progress(current_point: int, total_points: int)
    finished(series_index: int, df: pd.DataFrame)
    error(series_index: int, message: str)
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Signal

from core.engine import AnalysisResult, SeriesParams, run_full_analysis
from core.simulation import (
    CommonFiberParams,
    FiberType,
    PEFiberParams,
    PVAFiberParams,
    SteelFiberParams,
    build_pullout_model,
    simulate_sigma_delta,
)
from models.project import ProjectModel
from utils.io import DataLoadError, load_sigma_delta_csv


class CsvLoaderWorker(QThread):
    """
    Load and clean a single sigma-delta CSV off the main thread.

    Emits `loaded` with (series_index, cleaned_df, resolved_path) on success,
    or `error` with (series_index, human-readable message) on failure.
    """

    loaded: Signal = Signal(int, object, object)  # (int, pd.DataFrame, Path)
    error: Signal = Signal(int, str)

    def __init__(self, series_index: int, csv_path: Path) -> None:
        super().__init__()
        self._series_index = series_index
        self._csv_path = csv_path

    def run(self) -> None:
        try:
            df = load_sigma_delta_csv(self._csv_path)
            self.loaded.emit(self._series_index, df, self._csv_path)
        except (FileNotFoundError, DataLoadError) as exc:
            self.error.emit(self._series_index, str(exc))


class BatchAnalysisWorker(QThread):
    """
    Run run_full_analysis() for every series in *model* that has sigma-delta
    data loaded. Emits granular progress so the UI can update incrementally.

    NOTE: The worker takes a snapshot of params at construction time via
    model.all_params() to avoid data races if the UI mutates the model while
    the worker is running.
    """

    series_done: Signal = Signal(int, object)  # (index, AnalysisResult)
    progress: Signal = Signal(int, int)        # (current, total)
    finished: Signal = Signal()
    error: Signal = Signal(int, str)           # (index, message)

    def __init__(self, model: ProjectModel) -> None:
        super().__init__()
        self._params_snapshot: list[tuple[int, SeriesParams]] = [
            (i, copy.copy(entry.params))
            for i, entry in enumerate(model)
            if entry.params.sigma_delta_df is not None
        ]

    def run(self) -> None:
        total = len(self._params_snapshot)
        for current, (index, params) in enumerate(self._params_snapshot, start=1):
            try:
                result: AnalysisResult = run_full_analysis(params)
                self.series_done.emit(index, result)
            except ValueError as exc:
                self.error.emit(index, str(exc))
            self.progress.emit(current, total)
        self.finished.emit()


class SimulationWorker(QThread):
    """
    Generate a theoretical σ-δ bridging curve for one series via a simplified
    micromechanics double-integral model.

    On success emits `finished(series_index, df)` where df is drop-in compatible
    with the CSV import DataFrame (columns: delta, sigma).  The DataFrame attrs
    carry provenance metadata used by core.engine to reject stale curves.
    """

    progress: Signal = Signal(int, int)     # (current_point, total_points)
    finished: Signal = Signal(int, object)  # (series_index, pd.DataFrame)
    error: Signal = Signal(int, str)        # (series_index, message)

    def __init__(self, series_index: int, params: SeriesParams) -> None:
        super().__init__()
        self._series_index = series_index

        denom = math.pi * params.d_f * params.l_e
        if denom <= 0.0:
            raise ValueError(
                f"Cannot compute τ₀: d_f={params.d_f!r} and l_e={params.l_e!r} "
                "must both be positive non-zero values."
            )
        if params.p_peak <= 0.0:
            raise ValueError(f"Cannot compute τ₀: P_peak must be positive; got {params.p_peak!r}.")

        self._tau_0: float = params.p_peak / denom
        self._params: SeriesParams = copy.copy(params)
        self._simulation_signature = self._params.simulation_signature()

    def run(self) -> None:
        try:
            fiber_type = FiberType[self._params.sim_fiber_type]

            common = CommonFiberParams(
                V_f=self._params.sim_V_f,
                L_f=self._params.sim_L_f,
                d_f=self._params.d_f,
                E_f=self._params.sim_E_f,
                sigma_fu=self._params.sim_sigma_fu,
                tau_0=self._tau_0,
                f_snubbing=self._params.sim_f_snubbing,
                n_delta_points=self._params.sim_n_delta_points,
            )

            pe_params = (
                PEFiberParams(beta=self._params.sim_beta)
                if fiber_type is FiberType.PE
                else None
            )
            pva_params = (
                PVAFiberParams(
                    G_d=self._params.sim_G_d,
                    beta=self._params.sim_beta,
                )
                if fiber_type is FiberType.PVA
                else None
            )
            steel_params = (
                SteelFiberParams(
                    P_anchor_max=self._params.sim_P_anchor_max,
                    delta_hook=self._params.sim_delta_hook,
                )
                if fiber_type is FiberType.STEEL
                else None
            )

            pullout_model = build_pullout_model(
                fiber_type, common, pe_params, pva_params, steel_params
            )
            df = simulate_sigma_delta(
                common,
                pullout_model,
                progress_callback=lambda cur, tot: self.progress.emit(cur, tot),
            )
            df.attrs["source"] = "simulation"
            df.attrs["simulation_signature"] = self._simulation_signature
            self.finished.emit(self._series_index, df)

        except KeyError:
            self.error.emit(
                self._series_index,
                f"Unknown fiber type: '{self._params.sim_fiber_type}'. "
                "Expected one of: PE, PVA, STEEL.",
            )
        except ValueError as exc:
            self.error.emit(self._series_index, str(exc))
        except (RuntimeError, ArithmeticError, OverflowError) as exc:
            self.error.emit(self._series_index, f"Simulation failed: {exc}")
