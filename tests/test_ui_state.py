from __future__ import annotations

import pandas as pd
import pytest

from core.engine import AnalysisResult
from ui.main_window import MainWindow


def _result(name: str) -> AnalysisResult:
    return AnalysisResult(
        series_name=name,
        variable_value=1.0,
        tau0=1.0,
        km=1.0,
        j_tip=1.0,
        sigma0=4.0,
        delta0=0.2,
        jb_prime=400.0,
        psh_strength=1.5,
        psh_energy=3.0,
    )


def _curve(source: str = "csv") -> pd.DataFrame:
    df = pd.DataFrame({"delta": [0.0, 0.1, 0.2], "sigma": [0.0, 2.0, 4.0]})
    df.attrs["source"] = source
    return df


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_form_edits_persist_when_switching_series(window: MainWindow, qtbot) -> None:
    window._on_add_series()
    first_id = window._current_series_id
    assert first_id is not None

    window._sb_p_peak.setValue(42.0)
    window._sb_d_f.setValue(0.039)
    assert window._model.get_entry_by_id(first_id).params.p_peak == pytest.approx(42.0)

    window._on_add_series()
    first_item = window._tree_item_for_id(first_id)
    assert first_item is not None
    window._tree.setCurrentItem(first_item)
    qtbot.wait(10)

    assert window._sb_p_peak.value() == pytest.approx(42.0)
    assert window._sb_d_f.value() == pytest.approx(0.039)


def test_editing_simulation_parameter_invalidates_old_curve(window: MainWindow) -> None:
    window._on_add_series()
    entry = window._current_entry()
    assert entry is not None

    entry.params.sigma_delta_mode = "simulation"
    entry.params.sigma_delta_source = "simulation"
    df = _curve("simulation")
    df.attrs["simulation_signature"] = entry.params.simulation_signature()
    entry.params.sigma_delta_df = df
    entry.result = _result(entry.params.name)
    window._populate_form_by_id(entry.series_id)

    window._sb_beta.setValue(0.25)

    assert entry.params.sigma_delta_df is None
    assert entry.params.sigma_delta_source == "none"
    assert entry.params.sigma_delta_mode == "simulation"
    assert entry.result is None


def test_mode_switch_clears_incompatible_curve_provenance(window: MainWindow) -> None:
    window._on_add_series()
    entry = window._current_entry()
    assert entry is not None
    entry.params.sigma_delta_mode = "csv"
    entry.params.sigma_delta_source = "csv"
    entry.params.sigma_delta_df = _curve("csv")
    entry.result = _result(entry.params.name)
    window._populate_form_by_id(entry.series_id)

    window._on_mode_switched(1)

    assert entry.params.sigma_delta_mode == "simulation"
    assert entry.params.sigma_delta_source == "none"
    assert entry.params.sigma_delta_df is None
    assert entry.result is None


def test_simulation_result_is_routed_by_stable_id_after_index_shift(window: MainWindow) -> None:
    window._on_add_series()
    first = window._current_entry()
    assert first is not None
    window._on_add_series()
    second = window._current_entry()
    assert second is not None

    window._model.remove_series_by_id(first.series_id)
    first_item = window._tree_item_for_id(first.series_id)
    if first_item is not None:
        index = window._tree.indexOfTopLevelItem(first_item)
        window._tree.takeTopLevelItem(index)

    second.params.sigma_delta_mode = "simulation"
    df = _curve("simulation")
    df.attrs["simulation_signature"] = second.params.simulation_signature()
    window._on_sim_result(second.series_id, df)

    assert window._model.index_of(second.series_id) == 0
    assert second.params.sigma_delta_df is df
    assert second.params.sigma_delta_source == "simulation"


def test_simulation_button_state_is_per_selected_series(window: MainWindow) -> None:
    window._on_add_series()
    first = window._current_entry()
    assert first is not None
    window._on_add_series()
    second = window._current_entry()
    assert second is not None

    window._sim_workers[first.series_id] = object()  # type: ignore[assignment]

    first_item = window._tree_item_for_id(first.series_id)
    second_item = window._tree_item_for_id(second.series_id)
    assert first_item is not None and second_item is not None

    window._tree.setCurrentItem(first_item)
    window._sync_simulation_ui()
    assert not window._btn_run_sim.isEnabled()

    window._tree.setCurrentItem(second_item)
    window._sync_simulation_ui()
    assert window._btn_run_sim.isEnabled()

    window._sim_workers.clear()


def test_analysis_preflight_reports_missing_and_stale_curves(window: MainWindow) -> None:
    window._on_add_series()
    missing = window._current_entry()
    assert missing is not None

    window._on_add_series()
    stale = window._current_entry()
    assert stale is not None
    stale.params.sigma_delta_mode = "simulation"
    stale.params.sigma_delta_source = "simulation"
    stale_df = _curve("simulation")
    stale_df.attrs["simulation_signature"] = "stale"
    stale.params.sigma_delta_df = stale_df

    problems = window._analysis_preflight()

    assert any(missing.params.name in problem and "no active" in problem for problem in problems)
    assert any(stale.params.name in problem and "stale" in problem for problem in problems)
