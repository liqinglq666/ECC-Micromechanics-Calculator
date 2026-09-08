from __future__ import annotations

import math

import pytest

from core.simulation import (
    CommonFiberParams,
    FiberType,
    PEFiberParams,
    PVAFiberParams,
    _orientation_weight,
    build_pullout_model,
    simulate_sigma_at_delta,
)


def test_orientation_weights_match_yang_randomness_transform() -> None:
    theta = math.pi / 4.0
    assert _orientation_weight(theta, "3d") == pytest.approx(0.5)
    assert _orientation_weight(theta, "2d") == pytest.approx(
        math.sqrt(2.0) / math.pi
    )


def test_pe_zero_chemical_bond_starts_from_zero_traction() -> None:
    common = CommonFiberParams(
        V_f=0.02,
        L_f=12.0,
        d_f=0.039,
        E_f=116.0,
        sigma_fu=2600.0,
        tau_0=1.0,
        f_snubbing=0.2,
        E_m=20.0,
    )
    model = build_pullout_model(
        FiberType.PE, common, pe_params=PEFiberParams(beta=0.0)
    )
    assert model.get_pullout_force(0.0, 6.0, 0.0) == pytest.approx(0.0)


def test_pva_chemical_bond_allows_finite_debond_initiation_traction() -> None:
    common = CommonFiberParams(
        V_f=0.02,
        L_f=12.0,
        d_f=0.039,
        E_f=22.0,
        sigma_fu=1060.0,
        tau_0=1.31,
        f_snubbing=0.2,
        E_m=20.0,
    )
    model = build_pullout_model(
        FiberType.PVA,
        common,
        pva_params=PVAFiberParams(G_d=1.08, beta=0.58),
    )
    assert model.expects_zero_origin() is False
    assert model.get_pullout_force(0.0, 6.0, 0.0) > 0.0


def test_inclination_strength_reduction_lowers_rupture_capacity() -> None:
    common = CommonFiberParams(
        V_f=0.02,
        L_f=12.0,
        d_f=0.039,
        E_f=22.0,
        sigma_fu=1060.0,
        tau_0=1.31,
        f_snubbing=0.2,
        E_m=20.0,
        f_strength_reduction=0.33,
    )
    model = build_pullout_model(
        FiberType.PVA,
        common,
        pva_params=PVAFiberParams(G_d=1.08, beta=0.58),
    )
    assert model.rupture_force(math.pi / 3.0) < model.rupture_force(0.0)


def test_yang_2008_m45_one_way_pva_benchmark() -> None:
    """Check the Yang et al. 2008 M45 one-way baseline.

    Yang et al. report 6.2 MPa at 93 um for the previous one-way-pullout
    model. The current code intentionally omits the later two-way pullout,
    spalling, and Cook-Gordon refinements, so crack opening uses a tolerance
    appropriate to the one-way baseline implementation.
    """
    common = CommonFiberParams(
        V_f=0.02,
        L_f=12.0,
        d_f=0.039,
        E_f=22.0,
        sigma_fu=1060.0,
        tau_0=1.31,
        f_snubbing=0.2,
        E_m=20.0,
        f_strength_reduction=0.33,
        orientation="2d",
    )
    model = build_pullout_model(
        FiberType.PVA,
        common,
        pva_params=PVAFiberParams(G_d=1.08, beta=0.58),
    )

    deltas = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11]
    stresses = [
        simulate_sigma_at_delta(common, model, delta)
        for delta in deltas
    ]
    peak_index = max(range(len(stresses)), key=stresses.__getitem__)
    peak_stress = stresses[peak_index]
    peak_delta = deltas[peak_index]

    assert peak_stress == pytest.approx(6.2, abs=0.5)
    assert peak_delta == pytest.approx(0.093, abs=0.03)
