"""Generate real UI screenshots for software copyright documentation.

This script runs the actual PySide6 application and the current micromechanics
engine. It creates three PE-ECC series, performs theoretical sigma-delta
simulation and full PSH analysis, then captures the rendered application tabs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QTreeWidgetItem

from core.engine import SeriesParams, calc_tau0, run_full_analysis
from core.simulation_safe import (
    CommonFiberParams,
    FiberType,
    PEFiberParams,
    build_pullout_model,
    simulate_sigma_delta,
)
from ui.main_window import MainWindow
from utils.export import build_settings_log_df, build_sigma_delta_df, build_summary_df, write_excel

OUT = Path(os.environ.get("ECC_SCREENSHOT_DIR", "copyright_screenshots"))
OUT.mkdir(parents=True, exist_ok=True)


def _settle(app: QApplication, ms: int = 500) -> None:
    app.processEvents()
    QTest.qWait(ms)
    app.processEvents()


def _capture(app: QApplication, window: MainWindow, filename: str) -> None:
    _settle(app, 700)
    pixmap = window.grab()
    path = OUT / filename
    if not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"Failed to save screenshot: {path}")
    print(f"saved: {path} ({pixmap.width()}x{pixmap.height()})")


def _set_visible_form(window: MainWindow) -> None:
    """Populate the visible first-series form with a representative PE-ECC case."""
    window._sb_name.setText("PE-ECC-1")
    window._sb_varval.setValue(0.75)
    window._sb_p_peak.setValue(0.75)
    window._sb_d_f.setValue(0.039)
    window._sb_l_e.setValue(6.0)
    window._sb_p_max.setValue(150.0)
    window._sb_span.setValue(160.0)
    window._sb_b.setValue(40.0)
    window._sb_d.setValue(40.0)
    window._sb_a0.setValue(16.0)
    window._sb_e_m.setValue(20.0)
    window._sb_sigma_fc.setValue(3.2)

    window._radio_sim.setChecked(True)
    window._sd_stack.setCurrentIndex(1)
    window._cmb_fiber_type.setCurrentIndex(0)
    window._sb_V_f.setValue(0.02)
    window._sb_L_f.setValue(12.0)
    window._sb_E_f.setValue(116.0)
    window._sb_sigma_fu.setValue(2600.0)
    window._sb_beta.setValue(0.0)
    window._sb_f_snubbing.setValue(0.20)
    window._sb_n_points.setValue(300)
    window._write_form_to_model(0)
    window._model.get_entry(0).params.sigma_delta_source = "simulation"


def _capture_simulation_controls(app: QApplication, window: MainWindow) -> None:
    """Scroll the real left parameter pane to expose the theoretical simulation controls."""
    scroll_areas = window.findChildren(QScrollArea)
    if not scroll_areas:
        raise RuntimeError("No QScrollArea found in MainWindow")
    left_scroll = scroll_areas[0]
    bar = left_scroll.verticalScrollBar()
    previous = bar.value()
    bar.setValue(bar.maximum())
    _capture(app, window, "02b_theoretical_simulation_controls.png")
    bar.setValue(previous)
    _settle(app, 300)


def _build_and_run(
    name: str,
    variable_value: float,
    p_peak: float,
    p_max: float,
    e_m: float,
    sigma_fc: float,
) -> tuple[SeriesParams, object]:
    params = SeriesParams(
        name=name,
        variable_value=variable_value,
        p_peak=p_peak,
        d_f=0.039,
        l_e=6.0,
        p_max=p_max,
        span=160.0,
        b=40.0,
        d=40.0,
        a0=16.0,
        e_m=e_m,
        fracture_condition="plane_stress",
        poisson_ratio=0.20,
        sigma_fc=sigma_fc,
        sigma_delta_source="simulation",
        sim_fiber_type="PE",
        sim_V_f=0.02,
        sim_L_f=12.0,
        sim_E_f=116.0,
        sim_sigma_fu=2600.0,
        sim_G_d=0.0,
        sim_beta=0.0,
        sim_f_snubbing=0.20,
        sim_tau0_override=0.0,
        sim_f_strength_reduction=0.0,
        sim_orientation="3d",
        sim_n_delta_points=300,
    )

    tau0 = calc_tau0(params.p_peak, params.d_f, params.l_e)
    common = CommonFiberParams(
        V_f=params.sim_V_f,
        L_f=params.sim_L_f,
        d_f=params.d_f,
        E_f=params.sim_E_f,
        sigma_fu=params.sim_sigma_fu,
        tau_0=tau0,
        f_snubbing=params.sim_f_snubbing,
        n_delta_points=params.sim_n_delta_points,
        E_m=params.e_m,
        f_strength_reduction=params.sim_f_strength_reduction,
        orientation=params.sim_orientation,
    )
    pullout = build_pullout_model(
        FiberType.PE,
        common,
        pe_params=PEFiberParams(beta=params.sim_beta),
    )
    df = simulate_sigma_delta(common, pullout)
    df.attrs["source"] = "simulation"
    df.attrs["simulation_signature"] = params.simulation_signature()
    params.sigma_delta_df = df
    result = run_full_analysis(params)
    return params, result


def _populate_real_results(window: MainWindow) -> None:
    cases = [
        ("PE-ECC-1", 0.75, 0.75, 150.0, 20.0, 3.20),
        ("PE-ECC-2", 0.90, 0.90, 180.0, 22.0, 3.30),
        ("PE-ECC-3", 1.05, 1.05, 210.0, 24.0, 3.40),
    ]

    for idx, case in enumerate(cases):
        params, result = _build_and_run(*case)
        if idx == 0:
            entry = window._model.get_entry(0)
            entry.params = params
            entry.result = result
            window._tree.topLevelItem(0).setText(0, params.name)
        else:
            entry = window._model.add_series(params)
            entry.result = result
            window._tree.addTopLevelItem(QTreeWidgetItem([params.name]))

    window._model.variable_name = "Pullout peak load P_peak (N)"
    window._var_name_edit.setText(window._model.variable_name)
    window._tree.setCurrentItem(window._tree.topLevelItem(0))
    window._current_index = 0
    window._populate_form(0)
    window._refresh_single_tab(0)
    window._refresh_summary_tab()
    window._refresh_comparative_tab()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("ECC Micromechanics Calculator")
    app.setStyle("Fusion")

    window = MainWindow()
    window.resize(1500, 860)
    window.show()
    _settle(app, 900)

    _capture(app, window, "01_startup_main_window.png")

    window._on_add_series()
    _set_visible_form(window)
    _capture(app, window, "02_pe_ecc_parameter_input.png")
    _capture_simulation_controls(app, window)

    _populate_real_results(window)

    window._tabs.setCurrentIndex(0)
    _capture(app, window, "03_single_series_results.png")

    window._tabs.setCurrentIndex(1)
    _capture(app, window, "04_data_summary.png")

    window._tabs.setCurrentIndex(2)
    _capture(app, window, "05_comparative_analytics.png")

    export_path = OUT / "ECC_MC_real_run_results.xlsx"
    write_excel(
        export_path,
        build_summary_df(window._model),
        build_sigma_delta_df(window._model),
        build_settings_log_df(window._model),
    )
    print(f"exported: {export_path}")

    provenance = OUT / "RUN_PROVENANCE.txt"
    provenance.write_text(
        "ECC Micromechanics Calculator real UI capture\n"
        "source: GitHub Actions runner\n"
        "UI: PySide6 / Qt Fusion / offscreen platform plugin\n"
        "calculation: core.simulation_safe.simulate_sigma_delta + core.engine.run_full_analysis\n"
        "series: PE-ECC-1, PE-ECC-2, PE-ECC-3\n"
        "curve resolution: 300 points per series\n",
        encoding="utf-8",
    )

    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
