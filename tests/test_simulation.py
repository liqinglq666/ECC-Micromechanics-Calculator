from __future__ import annotations

import pytest

from core.simulation import (
    CommonFiberParams,
    FiberType,
    PEFiberParams,
    build_pullout_model,
    simulate_sigma_delta,
)


def test_simulated_curve_starts_at_origin_and_is_tagged() -> None:
    common = CommonFiberParams(
        V_f=0.02,
        L_f=12.0,
        d_f=0.04,
        E_f=116.0,
        sigma_fu=2600.0,
        tau_0=1.0,
        f_snubbing=0.2,
        n_delta_points=3,
    )
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.1))

    df = simulate_sigma_delta(common, model)

    assert list(df.columns) == ["delta", "sigma"]
    assert df["delta"].iloc[0] == pytest.approx(0.0)
    assert len(df) == 3
    assert df.attrs["source"] == "simulation"


def test_common_fiber_params_reject_invalid_inputs() -> None:
    common = CommonFiberParams(
        V_f=1.2,
        L_f=12.0,
        d_f=0.04,
        E_f=116.0,
        sigma_fu=2600.0,
        tau_0=1.0,
        f_snubbing=0.2,
        n_delta_points=3,
    )

    with pytest.raises(ValueError, match="V_f"):
        common.validate()
