from __future__ import annotations

import math

import numpy as np
import pytest

from core.engine import calc_jb_prime, calc_tau0


def test_calc_tau0_uses_pullout_geometry() -> None:
    assert calc_tau0(100.0, 0.04, 6.0) == pytest.approx(100.0 / (math.pi * 0.04 * 6.0))


def test_calc_jb_prime_integrates_to_peak() -> None:
    delta = np.array([0.0, 0.1, 0.2, 0.3])
    sigma = np.array([0.0, 2.0, 4.0, 3.0])

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
def test_calc_jb_prime_rejects_invalid_curves(
    delta: np.ndarray,
    sigma: np.ndarray,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calc_jb_prime(delta, sigma)
