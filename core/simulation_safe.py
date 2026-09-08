from __future__ import annotations

import numpy as np
import pandas as pd

from core.simulation import (
    CommonFiberParams,
    FiberPulloutModel,
    FiberType,
    PEFiberParams,
    PVAFiberParams,
    SteelFiberParams,
    build_pullout_model,
    simulate_sigma_at_delta,
    simulate_sigma_delta as _simulate_sigma_delta,
)

__all__ = [
    "CommonFiberParams",
    "FiberPulloutModel",
    "FiberType",
    "PEFiberParams",
    "PVAFiberParams",
    "SteelFiberParams",
    "build_pullout_model",
    "simulate_sigma_at_delta",
    "simulate_sigma_delta",
]


def simulate_sigma_delta(
    common: CommonFiberParams,
    pullout_model: FiberPulloutModel,
    progress_callback=None,
) -> pd.DataFrame:
    """Validation wrapper: detect physics bugs; never mutate the curve."""
    if common.V_f <= 0.0:
        raise ValueError("V_f must be greater than 0 for bridging simulation.")

    df = _simulate_sigma_delta(
        common, pullout_model, progress_callback=progress_callback
    )
    delta = df["delta"].to_numpy(dtype=float)
    sigma = df["sigma"].to_numpy(dtype=float)

    if not (np.isfinite(delta).all() and np.isfinite(sigma).all()):
        raise ValueError("Simulated bridging curve contains non-finite values.")
    if np.any(delta < 0.0) or np.any(sigma < 0.0):
        raise ValueError("Simulated bridging curve contains negative values.")
    if len(df) == 0 or not np.isclose(delta[0], 0.0, atol=1e-12):
        raise ValueError("Simulated bridging curve must start at delta=0.")
    expects_zero = getattr(pullout_model, "expects_zero_origin", lambda: True)()
    if (
        expects_zero
        and not np.isclose(sigma[0], 0.0, atol=1e-10)
    ):
        raise ValueError(
            "Simulated bridging stress must be zero at delta=0 for this interface law; "
            "fix the pullout model instead of forcing the first point."
        )
    return df
