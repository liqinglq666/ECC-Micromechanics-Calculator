"""Background workers for file loading, simulation, and batch analysis.

Workers communicate with the UI exclusively through stable series UUIDs.
No worker relies on mutable list indices, and no custom signal shadows
QThread.finished.
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.engine import AnalysisResult, SeriesParams, calc_tau0, run_full_analysis
from core.simulation_safe import (
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
    loaded = Signal(str, object, object)
    failed = Signal(str, str)

    def __init__(self, series_id: str, csv_path: Path) -> None:
        super().__init__()
        self._series_id = series_id
        self._csv_path = csv_path

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            df = load_sigma_delta_csv(self._csv_path)
            if not self.isInterruptionRequested():
                self.loaded.emit(self._series_id, df, self._csv_path)
        except (FileNotFoundError, DataLoadError, OSError) as exc:
            self.failed.emit(self._series_id, str(exc))
        except Exception as exc:  # keep thread failures visible to the user
            self.failed.emit(self._series_id, f"Unexpected CSV load error: {exc}")


class BatchAnalysisWorker(QThread):
    series_done = Signal(str, object)
    series_failed = Signal(str, str)
    progress = Signal(int, int)
    completed = Signal(int, int)

    def __init__(self, model: ProjectModel) -> None:
        super().__init__()
        self._params_snapshot: list[tuple[str, SeriesParams]] = [
            (entry.series_id, copy.copy(entry.params)) for entry in model
        ]

    def run(self) -> None:
        total = len(self._params_snapshot)
        succeeded = 0

        for current, (series_id, params) in enumerate(self._params_snapshot, start=1):
            if self.isInterruptionRequested():
                break
            try:
                result: AnalysisResult = run_full_analysis(params)
                self.series_done.emit(series_id, result)
                succeeded += 1
            except ValueError as exc:
                self.series_failed.emit(series_id, str(exc))
            except Exception as exc:
                self.series_failed.emit(series_id, f"Unexpected analysis error: {exc}")
            self.progress.emit(current, total)

        if not self.isInterruptionRequested():
            self.completed.emit(succeeded, total)


class SimulationWorker(QThread):
    progress = Signal(str, int, int)
    result_ready = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, series_id: str, params: SeriesParams) -> None:
        super().__init__()
        self._series_id = series_id
        self._params = copy.copy(params)

        if self._params.d_f <= 0.0:
            raise ValueError(f"d_f must be positive; got {self._params.d_f}")
        if self._params.sim_tau0_override > 0.0:
            self._tau_0 = self._params.sim_tau0_override
        else:
            self._tau_0 = calc_tau0(
                self._params.p_peak,
                self._params.d_f,
                self._params.l_e,
            )
        self._simulation_signature = self._params.simulation_signature()

    def _report_progress(self, current: int, total: int) -> None:
        if self.isInterruptionRequested():
            raise InterruptedError
        self.progress.emit(self._series_id, current, total)

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
                E_m=self._params.e_m,
                f_strength_reduction=self._params.sim_f_strength_reduction,
                orientation=self._params.sim_orientation,
            )

            pe_params = (
                PEFiberParams(beta=self._params.sim_beta)
                if fiber_type is FiberType.PE
                else None
            )
            pva_params = (
                PVAFiberParams(G_d=self._params.sim_G_d, beta=self._params.sim_beta)
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
                fiber_type,
                common,
                pe_params,
                pva_params,
                steel_params,
            )
            df = simulate_sigma_delta(
                common,
                pullout_model,
                progress_callback=self._report_progress,
            )
            df.attrs["source"] = "simulation"
            df.attrs["simulation_signature"] = self._simulation_signature

            if self.isInterruptionRequested():
                self.cancelled.emit(self._series_id)
                return
            self.result_ready.emit(self._series_id, df)
        except InterruptedError:
            self.cancelled.emit(self._series_id)
        except KeyError:
            self.failed.emit(
                self._series_id,
                f"Unknown fiber type: '{self._params.sim_fiber_type}'. Expected PE, PVA or STEEL.",
            )
        except ValueError as exc:
            self.failed.emit(self._series_id, str(exc))
        except (RuntimeError, ArithmeticError, OverflowError) as exc:
            self.failed.emit(self._series_id, f"Simulation failed: {exc}")
        except Exception as exc:
            self.failed.emit(self._series_id, f"Unexpected simulation error: {exc}")
