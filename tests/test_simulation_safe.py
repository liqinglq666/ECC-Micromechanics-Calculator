from __future__ import annotations

import pandas as pd
import pytest

import core.simulation_safe as safe
from core.simulation import CommonFiberParams


def common_params(volume_fraction: float) -> CommonFiberParams:
    return CommonFiberParams(
        V_f=volume_fraction,
        L_f=12.0,
        d_f=0.012,
        E_f=116.0,
        sigma_fu=2600.0,
        tau_0=1.0,
        f_snubbing=0.2,
        n_delta_points=2,
    )


def test_zero_volume_fraction_is_rejected():
    with pytest.raises(ValueError, match="greater than 0"):
        safe.simulate_sigma_delta(common_params(0.0), object())


def test_simulated_curve_starts_at_origin(monkeypatch):
    monkeypatch.setattr(
        safe,
        "_simulate_sigma_delta",
        lambda *args, **kwargs: pd.DataFrame({"delta": [0.0, 0.1], "sigma": [4.2, 3.8]}),
    )

    result = safe.simulate_sigma_delta(common_params(0.02), object())

    assert result.loc[0, "sigma"] == 0.0
