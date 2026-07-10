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
    "simulate_sigma_delta",
]


def simulate_sigma_delta(
    common: CommonFiberParams,
    pullout_model: FiberPulloutModel,
    progress_callback=None,
) -> pd.DataFrame:
    if common.V_f <= 0.0:
        raise ValueError("V_f must be greater than 0 for bridging simulation.")

    df = _simulate_sigma_delta(common, pullout_model, progress_callback=progress_callback)
    sigma = df["sigma"].to_numpy(dtype=float)
    if not np.isfinite(sigma).all() or np.any(sigma < 0.0):
        raise ValueError("Simulated bridging stress contains invalid values.")

    # 桥接曲线必须过原点，别让简化拔出模型偷带 preload。
    if len(df):
        df.loc[df.index[0], "sigma"] = 0.0
    return df
