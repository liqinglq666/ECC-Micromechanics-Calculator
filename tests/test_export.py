from __future__ import annotations

import pandas as pd

from core.engine import SeriesParams
from models.project import ProjectModel
from utils.export import build_settings_log_df


def test_settings_log_contains_full_simulation_provenance() -> None:
    model = ProjectModel()
    params = SeriesParams(
        name="PVA-A",
        sigma_delta_mode="simulation",
        sigma_delta_source="simulation",
        sim_fiber_type="PVA",
        sim_tau0_override=1.31,
        sim_f_strength_reduction=0.33,
        sim_orientation="2d",
    )
    df = pd.DataFrame({"delta": [0.0, 0.1], "sigma": [0.5, 1.0]})
    df.attrs["source"] = "simulation"
    df.attrs["simulation_signature"] = "abc123"
    df.attrs["model_version"] = "one-way-yang2008-v3"
    params.sigma_delta_df = df
    model.add_series(params, series_id="stable-id")

    exported = build_settings_log_df(model)
    row = exported.iloc[0]

    assert row["Series ID"] == "stable-id"
    assert row["Selected Bridging Mode"] == "simulation"
    assert row["Active Curve Source"] == "simulation"
    assert row["Simulation Signature"] == "abc123"
    assert row["Model Version"] == "one-way-yang2008-v3"
    assert row["tau0 override (MPa)"] == 1.31
    assert row["f' strength reduction"] == 0.33
    assert row["Fiber Orientation"] == "2d"
