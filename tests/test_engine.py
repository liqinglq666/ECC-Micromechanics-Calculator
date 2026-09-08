from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.engine import (
    SeriesParams,
    calc_j_tip,
    calc_jb_prime,
    calc_km,
    calc_tau0,
    run_full_analysis,
)


def test_calc_tau0_uses_pullout_geometry() -> None:
    assert calc_tau0(100.0, 0.04, 6.0) == pytest.approx(100.0 / (math.pi * 0.04 * 6.0))


def test_calc_tau0_rejects_non_positive_peak_load() -> None:
    with pytest.raises(ValueError, match="P_peak must be positive"):
        calc_tau0(0.0, 0.04, 6.0)


def test_calc_km_rejects_wrong_span_depth_ratio_for_selected_geometry() -> None:
    with pytest.raises(ValueError, match="S/d ~= 4.0"):
        calc_km(500.0, 120.0, 40.0, 40.0, 16.0)


def test_calc_km_accepts_astm_span_depth_ratio() -> None:
    assert calc_km(500.0, 160.0, 40.0, 40.0, 16.0) > 0.0


def test_calc_j_tip_supports_plane_stress_and_plane_strain() -> None:
    plane_stress = calc_j_tip(1.0, 20.0, "plane_stress", 0.2)
    plane_strain = calc_j_tip(1.0, 20.0, "plane_strain", 0.2)
    assert plane_stress == pytest.approx(50.0)
    assert plane_strain == pytest.approx(48.0)


def test_calc_jb_prime_integrates_to_peak() -> None:
    delta = np.array([0.0, 0.1, 0.2, 0.3])
    sigma = np.array([0.0, 2.0, 4.0, 3.0])
    sigma0, delta0, jb_prime = calc_jb_prime(delta, sigma)
    assert sigma0 == pytest.approx(4.0)
    assert delta0 == pytest.approx(0.2)
    assert jb_prime == pytest.approx(400.0)


def test_calc_jb_prime_two_point_curve_uses_compatible_trapezoid() -> None:
    delta = np.array([0.0, 0.1])
    sigma = np.array([0.0, 2.0])

    sigma0, delta0, jb_prime = calc_jb_prime(delta, sigma)

    assert sigma0 == pytest.approx(2.0)
    assert delta0 == pytest.approx(0.1)
    assert jb_prime == pytest.approx(100.0)


def test_calc_jb_prime_prepends_origin_when_imported_curve_starts_positive() -> None:
    delta = np.array([0.1, 0.2, 0.3])
    sigma = np.array([2.0, 4.0, 3.0])
    sigma0, delta0, jb_prime = calc_jb_prime(delta, sigma)
    assert sigma0 == pytest.approx(4.0)
    assert delta0 == pytest.approx(0.2)
    assert jb_prime == pytest.approx(400.0)


@pytest.mark.parametrize(
    ("delta", "sigma", "message"),
    [
        (np.array([0.0, 0.1]), np.array([1.0]), "same length"),
        (np.array([0.0, np.nan]), np.array([1.0, 2.0]), "finite"),
        (np.array([0.0, -0.1]), np.array([1.0, 2.0]), "negative"),
        (np.array([0.1, 0.1]), np.array([1.0, 2.0]), "strictly increasing"),
    ],
)
def test_calc_jb_prime_rejects_invalid_curves(delta, sigma, message) -> None:
    with pytest.raises(ValueError, match=message):
        calc_jb_prime(delta, sigma)


def _positive_energy_curve() -> pd.DataFrame:
    return pd.DataFrame({"delta": [0.0, 0.1, 0.2, 0.3], "sigma": [0.0, 2.0, 4.0, 3.0]})


def _valid_params(df: pd.DataFrame) -> SeriesParams:
    return SeriesParams(
        name="A",
        p_peak=100.0,
        d_f=0.04,
        l_e=6.0,
        p_max=500.0,
        span=160.0,
        b=40.0,
        d=40.0,
        a0=16.0,
        e_m=20.0,
        sigma_fc=2.5,
        sigma_delta_mode="csv",
        sigma_delta_source="csv",
        sigma_delta_df=df,
    )


def test_run_full_analysis_rejects_source_mismatch() -> None:
    df = _positive_energy_curve()
    df.attrs["source"] = "simulation"
    params = _valid_params(df)
    with pytest.raises(ValueError, match="was generated from 'simulation'"):
        run_full_analysis(params)


def test_run_full_analysis_rejects_stale_simulation_signature() -> None:
    df = _positive_energy_curve()
    df.attrs["source"] = "simulation"
    df.attrs["simulation_signature"] = "old-signature"
    params = _valid_params(df)
    params.sigma_delta_mode = "simulation"
    params.sigma_delta_source = "simulation"
    with pytest.raises(ValueError, match="stale simulated"):
        run_full_analysis(params)


def test_simulation_signature_changes_when_matrix_modulus_changes() -> None:
    params = SeriesParams(e_m=20.0)
    sig1 = params.simulation_signature()
    params.e_m = 25.0
    assert params.simulation_signature() != sig1


def test_tau_override_decouples_signature_from_pullout_peak_and_embedment_length() -> None:
    params = SeriesParams(
        p_peak=100.0,
        d_f=0.04,
        l_e=6.0,
        sim_tau0_override=1.25,
    )
    signature = params.simulation_signature()
    params.p_peak = 999.0
    params.l_e = 12.0
    assert params.simulation_signature() == signature


def test_run_full_analysis_uses_tau_override_for_simulated_curve() -> None:
    df = _positive_energy_curve()
    params = _valid_params(df)
    params.sigma_delta_mode = "simulation"
    params.sigma_delta_source = "simulation"
    params.sim_tau0_override = 1.75
    df.attrs["source"] = "simulation"
    df.attrs["simulation_signature"] = params.simulation_signature()

    result = run_full_analysis(params)

    assert result.tau0 == pytest.approx(1.75)
