from __future__ import annotations

import math

import pytest

from core.simulation import (
    CommonFiberParams,
    FiberType,
    PEFiberParams,
    _make_integrand,
    build_pullout_model,
    simulate_sigma_delta,
)


def common_params(**overrides) -> CommonFiberParams:
    values = dict(
        V_f=0.02,
        L_f=12.0,
        d_f=0.04,
        E_f=116.0,
        sigma_fu=2600.0,
        tau_0=1.0,
        f_snubbing=0.2,
        n_delta_points=3,
        E_m=20.0,
    )
    values.update(overrides)
    return CommonFiberParams(**values)


def test_pe_pullout_force_is_zero_at_zero_opening() -> None:
    common = common_params()
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.0))
    assert model.get_pullout_force(0.0, 6.0, 0.0) == pytest.approx(0.0)


def test_pe_has_nonzero_debonding_force_after_crack_opens() -> None:
    common = common_params()
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.0))
    assert model.get_pullout_force(0.001, 6.0, 0.0) > 0.0


def test_fiber_rupture_is_irreversible() -> None:
    common = common_params(sigma_fu=500.0)
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.1))
    delta_d = model.max_debond_displacement(6.0)
    assert model.get_pullout_force(delta_d + 5.9, 6.0, 0.0) == pytest.approx(0.0)


def test_random_orientation_integrand_contains_crossing_cosine() -> None:
    common = common_params()
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.0))
    delta = 0.001
    l = 3.0
    theta = math.pi / 4.0
    p = model.get_pullout_force(delta, l, theta)
    value = _make_integrand(delta, model)(l, theta)
    assert value == pytest.approx(p * 0.5, rel=1e-12)


def test_simulated_curve_starts_at_physical_origin_and_is_tagged() -> None:
    common = common_params(n_delta_points=3)
    model = build_pullout_model(FiberType.PE, common, pe_params=PEFiberParams(beta=0.0))
    df = simulate_sigma_delta(common, model)
    assert list(df.columns) == ["delta", "sigma"]
    assert df["delta"].iloc[0] == pytest.approx(0.0)
    assert df["sigma"].iloc[0] == pytest.approx(0.0)
    assert len(df) == 3
    assert df.attrs["source"] == "simulation"


def test_common_fiber_params_reject_invalid_inputs() -> None:
    common = common_params(V_f=1.2)
    with pytest.raises(ValueError, match="V_f"):
        common.validate()
