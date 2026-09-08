"""Pure-function physics engine for ECC micromechanics.

Unit conventions:
  length -> mm | force -> N | stress -> MPa | modulus -> GPa | energy -> J/m^2
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
from scipy.integrate import simpson, trapezoid


@dataclass
class SeriesParams:
    """Raw experimental and simulation inputs for one mix-design series."""

    name: str = ""
    variable_value: float = 0.0

    # Single-fibre pullout test
    p_peak: float = 0.0
    d_f: float = 0.0
    l_e: float = 0.0

    # Matrix fracture - SENB 3-point bending
    p_max: float = 0.0
    span: float = 0.0
    b: float = 0.0
    d: float = 0.0
    a0: float = 0.0

    # Matrix elastic modulus / fracture condition
    e_m: float = 0.0
    fracture_condition: str = "plane_stress"
    poisson_ratio: float = 0.20

    # ECC uniaxial tensile test
    sigma_fc: float = 0.0

    # Bridging-curve selection and provenance are intentionally distinct.
    # mode: what the user currently selected in the UI.
    # source: where the currently loaded curve actually came from.
    sigma_delta_mode: str = "csv"  # "csv" | "simulation"
    sigma_delta_path: Path | None = field(default=None, repr=False)
    sigma_delta_df: pd.DataFrame | None = field(default=None, repr=False)
    sigma_delta_source: str = "none"  # "none" | "csv" | "simulation"

    # Theoretical simulation parameters
    sim_fiber_type: str = "PE"
    sim_V_f: float = 0.02
    sim_L_f: float = 12.0
    sim_E_f: float = 116.0
    sim_sigma_fu: float = 2600.0
    sim_G_d: float = 3.0
    sim_beta: float = 0.0
    sim_f_snubbing: float = 0.20
    sim_tau0_override: float = 0.0
    sim_f_strength_reduction: float = 0.0
    sim_orientation: str = "3d"
    sim_n_delta_points: int = 300
    sim_P_anchor_max: float = 0.0
    sim_delta_hook: float = 0.5

    def simulation_signature(self) -> str:
        """Stable fingerprint of every input that affects simulated sigma-delta.

        When tau0 is explicitly overridden, pullout peak load and embedment
        length no longer affect the simulation and are therefore excluded from
        the fingerprint. Fibre diameter remains included because the bridging
        law itself uses d_f.
        """
        tau_source = (
            ("override", self.sim_tau0_override)
            if self.sim_tau0_override > 0.0
            else ("derived", self.p_peak, self.l_e)
        )
        parts = [
            self.sim_fiber_type,
            tau_source,
            self.d_f,
            self.e_m,
            self.sim_V_f,
            self.sim_L_f,
            self.sim_E_f,
            self.sim_sigma_fu,
            self.sim_G_d,
            self.sim_beta,
            self.sim_f_snubbing,
            self.sim_f_strength_reduction,
            self.sim_orientation,
            self.sim_n_delta_points,
            self.sim_P_anchor_max,
            self.sim_delta_hook,
        ]
        payload = "|".join(str(value) for value in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class AnalysisResult:
    """Computed micromechanics outputs for one series."""

    PSH_STRENGTH_THRESHOLD: ClassVar[float] = 1.3
    PSH_ENERGY_THRESHOLD: ClassVar[float] = 2.7

    series_name: str
    variable_value: float
    tau0: float
    km: float
    j_tip: float
    sigma0: float
    delta0: float
    jb_prime: float
    psh_strength: float
    psh_energy: float

    @property
    def psh_strength_pass(self) -> bool:
        return self.psh_strength >= self.PSH_STRENGTH_THRESHOLD

    @property
    def psh_energy_pass(self) -> bool:
        return self.psh_energy >= self.PSH_ENERGY_THRESHOLD


def calc_tau0(p_peak: float, d_f: float, l_e: float) -> float:
    """Average frictional bond stress tau_0 = P/(pi*d_f*L_e), MPa."""
    if p_peak <= 0.0:
        raise ValueError(f"P_peak must be positive; got {p_peak}")
    if d_f <= 0.0 or l_e <= 0.0:
        raise ValueError(f"d_f and l_e must be positive; got d_f={d_f}, l_e={l_e}")
    return p_peak / (math.pi * d_f * l_e)


def _geometry_factor(alpha: float) -> float:
    """Gross-Srawley/ASTM E399 SENB geometry function for S/W ~= 4."""
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"a0/d ratio alpha={alpha:.4f} must be in (0, 1).")
    if not (0.1 <= alpha <= 0.9):
        raise ValueError(
            f"alpha={alpha:.4f} is outside the supported range [0.1, 0.9] "
            "for the selected SENB geometry function."
        )
    numerator = (
        3.0
        * math.sqrt(alpha)
        * (1.99 - alpha * (1.0 - alpha) * (2.15 - 3.93 * alpha + 2.7 * alpha**2))
    )
    denominator = 2.0 * (1.0 + 2.0 * alpha) * (1.0 - alpha) ** 1.5
    return numerator / denominator


def calc_km(p_max: float, span: float, b: float, d: float, a0: float) -> float:
    """SENB K_m in MPa*m^0.5 using the ASTM/Gross-Srawley S/W=4 geometry."""
    if p_max <= 0.0:
        raise ValueError(f"P_max must be positive; got {p_max}")
    if span <= 0.0:
        raise ValueError(f"Span S must be positive; got {span}")
    if b <= 0.0 or d <= 0.0:
        raise ValueError("Specimen dimensions b and d must be positive.")

    span_depth = span / d
    if not math.isclose(span_depth, 4.0, rel_tol=0.025, abs_tol=0.0):
        raise ValueError(
            f"Selected SENB geometry function requires S/d ~= 4.0; got S/d={span_depth:.3f}. "
            "Use an S/d=4 specimen or implement the geometry function matching your test."
        )

    alpha = a0 / d
    km_mm = (p_max * span) / (b * d**1.5) * _geometry_factor(alpha)
    return km_mm / math.sqrt(1000.0)


def calc_j_tip(
    km: float,
    e_m_gpa: float,
    fracture_condition: str = "plane_stress",
    poisson_ratio: float = 0.20,
) -> float:
    """Crack-tip toughness in J/m^2 from K_m and matrix modulus."""
    if km <= 0.0:
        raise ValueError(f"K_m must be positive; got {km}")
    if e_m_gpa <= 0.0:
        raise ValueError(f"E_m must be positive; got {e_m_gpa} GPa")

    condition = fracture_condition.strip().lower()
    if condition not in {"plane_stress", "plane_strain"}:
        raise ValueError(
            "fracture_condition must be 'plane_stress' or 'plane_strain'; "
            f"got {fracture_condition!r}"
        )
    if not (0.0 <= poisson_ratio < 0.5):
        raise ValueError(f"poisson_ratio must be in [0, 0.5); got {poisson_ratio}")

    e_m_mpa = e_m_gpa * 1000.0
    e_eff_mpa = e_m_mpa / (1.0 - poisson_ratio**2) if condition == "plane_strain" else e_m_mpa
    return (km**2 / e_eff_mpa) * 1_000_000.0


def _ensure_origin(delta: np.ndarray, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Prepend a conservative (0,0) only for imported curves starting at delta>0."""
    if delta[0] > 0.0:
        delta = np.insert(delta, 0, 0.0)
        sigma = np.insert(sigma, 0, 0.0)
    return delta, sigma


def calc_jb_prime(delta: np.ndarray, sigma: np.ndarray) -> tuple[float, float, float]:
    """Return sigma0 [MPa], delta0 [mm], J_b' [J/m^2]."""
    if len(delta) != len(sigma):
        raise ValueError(
            f"delta and sigma arrays must have the same length; got {len(delta)} and {len(sigma)}."
        )
    if len(delta) < 2:
        raise ValueError("sigma-delta curve needs at least 2 data points.")
    if not (np.isfinite(delta).all() and np.isfinite(sigma).all()):
        raise ValueError("sigma-delta curve must contain only finite values.")
    if np.any(delta < 0.0) or np.any(sigma < 0.0):
        raise ValueError("sigma-delta curve cannot contain negative values.")
    if np.any(np.diff(delta) <= 0.0):
        raise ValueError("delta values must be strictly increasing.")

    delta, sigma = _ensure_origin(delta.astype(float, copy=False), sigma.astype(float, copy=False))
    peak_idx = int(np.argmax(sigma))
    sigma0 = float(sigma[peak_idx])
    delta0 = float(delta[peak_idx])
    d_up = delta[: peak_idx + 1]
    s_up = sigma[: peak_idx + 1]

    if len(d_up) >= 3:
        area = float(simpson(s_up, x=d_up))
    else:
        # scipy.integrate.trapezoid is available throughout the declared
        # SciPy>=1.11 range and keeps this path compatible with NumPy 1.26.
        area = float(trapezoid(s_up, x=d_up))

    jb_prime_mpa_mm = sigma0 * delta0 - area
    return sigma0, delta0, jb_prime_mpa_mm * 1000.0


def calc_psh(
    sigma0: float,
    sigma_fc: float,
    jb_prime: float,
    j_tip: float,
) -> tuple[float, float]:
    """Return strength and energy PSH indices."""
    if sigma0 <= 0.0:
        raise ValueError(f"sigma0 must be positive; got {sigma0}")
    if sigma_fc <= 0.0:
        raise ValueError(f"sigma_fc must be positive; got {sigma_fc}")
    if jb_prime <= 0.0:
        raise ValueError(f"J_b' must be positive; got {jb_prime}")
    if j_tip <= 0.0:
        raise ValueError(f"J_tip must be positive; got {j_tip}")
    return sigma0 / sigma_fc, jb_prime / j_tip


def _validate_sigma_delta_provenance(params: SeriesParams, df: pd.DataFrame) -> None:
    source = params.sigma_delta_source
    actual_source = df.attrs.get("source")

    if source not in {"csv", "simulation"}:
        raise ValueError(
            f"Series '{params.name}' has no active sigma-delta source. "
            "Import a CSV or run theoretical simulation first."
        )
    if actual_source is not None and actual_source != source:
        raise ValueError(
            f"Series '{params.name}' is set to '{source}', but the loaded sigma-delta curve "
            f"was generated from '{actual_source}'. Re-import or re-simulate the curve."
        )
    if source == "simulation":
        expected = params.simulation_signature()
        actual = df.attrs.get("simulation_signature")
        if actual != expected:
            raise ValueError(
                f"Series '{params.name}' has a stale simulated sigma-delta curve. "
                "Simulation parameters changed after the curve was generated. "
                "Run Simulation again before analysis."
            )


def run_full_analysis(params: SeriesParams) -> AnalysisResult:
    """Run interface, fracture, bridging-energy and PSH calculations."""
    if params.sigma_delta_df is None:
        raise ValueError(
            f"Series '{params.name}' has no sigma-delta data. Import a CSV or run simulation first."
        )

    df = params.sigma_delta_df
    _validate_sigma_delta_provenance(params, df)
    missing_cols = [column for column in ("delta", "sigma") if column not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Series '{params.name}' sigma-delta data is missing column(s): {missing_cols}"
        )

    delta_arr = df["delta"].to_numpy(dtype=float)
    sigma_arr = df["sigma"].to_numpy(dtype=float)

    if params.sigma_delta_source == "simulation" and params.sim_tau0_override > 0.0:
        tau0 = params.sim_tau0_override
    else:
        tau0 = calc_tau0(params.p_peak, params.d_f, params.l_e)
    km = calc_km(params.p_max, params.span, params.b, params.d, params.a0)
    j_tip = calc_j_tip(km, params.e_m, params.fracture_condition, params.poisson_ratio)
    sigma0, delta0, jb_prime = calc_jb_prime(delta_arr, sigma_arr)
    psh_strength, psh_energy = calc_psh(sigma0, params.sigma_fc, jb_prime, j_tip)

    return AnalysisResult(
        series_name=params.name,
        variable_value=params.variable_value,
        tau0=tau0,
        km=km,
        j_tip=j_tip,
        sigma0=sigma0,
        delta0=delta0,
        jb_prime=jb_prime,
        psh_strength=psh_strength,
        psh_energy=psh_energy,
    )
