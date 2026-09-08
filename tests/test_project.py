from __future__ import annotations

import pytest

from core.engine import AnalysisResult, SeriesParams
from models.project import ProjectModel


def _result(name: str, variable_value: float) -> AnalysisResult:
    return AnalysisResult(
        series_name=name,
        variable_value=variable_value,
        tau0=1.0,
        km=1.0,
        j_tip=1.0,
        sigma0=1.0,
        delta0=1.0,
        jb_prime=1.0,
        psh_strength=1.0,
        psh_energy=1.0,
    )


def test_x_labels_use_series_names_when_variable_values_duplicate() -> None:
    model = ProjectModel()
    first = model.add_series(SeriesParams(name="A", variable_value=1.0))
    second = model.add_series(SeriesParams(name="B", variable_value=1.0))
    first.result = _result("A", 1.0)
    second.result = _result("B", 1.0)
    assert model.x_labels() == ["A", "B"]


def test_generated_series_names_remain_unique_after_removal() -> None:
    model = ProjectModel()
    model.add_series()
    model.add_series()
    model.remove_series(0)
    entry = model.add_series()
    assert entry.params.name == "Series 3"


def test_series_id_is_stable_when_earlier_series_is_removed() -> None:
    model = ProjectModel()
    first = model.add_series(SeriesParams(name="A"))
    second = model.add_series(SeriesParams(name="B"))
    second_id = second.series_id

    model.remove_series_by_id(first.series_id)

    assert model.index_of(second_id) == 0
    assert model.get_entry_by_id(second_id).params.name == "B"


def test_unknown_series_id_raises_clear_error() -> None:
    model = ProjectModel()
    with pytest.raises(KeyError, match="Unknown series_id"):
        model.get_entry_by_id("missing")


def test_clear_curve_preserves_selected_mode_but_removes_provenance() -> None:
    model = ProjectModel()
    entry = model.add_series(SeriesParams(name="A", sigma_delta_mode="simulation"))
    entry.params.sigma_delta_source = "simulation"
    entry.params.sigma_delta_df = object()  # type: ignore[assignment]
    entry.result = _result("A", 1.0)

    model.clear_curve(entry.series_id)

    assert entry.params.sigma_delta_mode == "simulation"
    assert entry.params.sigma_delta_source == "none"
    assert entry.params.sigma_delta_df is None
    assert entry.result is None
