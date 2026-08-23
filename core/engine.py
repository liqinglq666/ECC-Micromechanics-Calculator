"""core/engine.py

Pure-function physics engine for ECC micromechanics.
Zero Qt / IO dependencies — importable in headless test environments.

Unit conventions (enforced throughout):
  length → mm | force → N | stress → MPa | modulus → GPa | energy → J/m²
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional

import numpy as np
import pandas as pd
from scipy.integrate import simpson


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------

@dataclass
class SeriesParams:
    """Raw experimental inputs for one mix-design series."""

    name: str = ""
    variable_value: float = 0.0

    # Single-fibre pullout test
    p_peak: float = 0.0        # N
    d_f: float = 0.0           # mm
    l_e: float = 0.0           # mm

    # Matrix fracture — 3-point bending
    p_max: float = 0.0         # N
    span: float = 0.0          # mm
    b: float = 0.0             # mm
    d: float = 0.0             # mm
    a0: float = 0.0            # mm

    # Matrix elastic modulus / fracture condition
    e_m: float = 0.0           # GPa
    fracture_condition: str = "plane_stress"  # "plane_stress" | "plane_strain"
    poisson_ratio: float = 0.20

    # ECC uniaxial tensile test
    sigma_fc: float = 0.0      # MPa  (first-crack composite strength)

    sigma_delta_path: Optional[Path] = field(default=None, repr=False)
    sigma_delta_df: Optional[pd.DataFrame] = field(default=None, repr=False)

    # σ-δ data provenance — written to export log and validated before math
    sigma_delta_source: str = "none"   # "none" | "csv" | "simulation"

    # ── Theoretical simulation parameters ──────────────────────────────
    # Only interpreted by SimulationEngine; engine.py reads them only to build
    # a reproducibility signature that prevents stale simulated curves.
    sim_fiber_type: str = "PE"          # "PE" | "PVA" | "STEEL"
    sim_V_f: float = 0.02
    sim_L_f: float = 12.0
    sim_E_f: float = 116.0              # GPa
    sim_sigma_fu: float = 2600.0        # MPa
    sim_G_d: float = 3.0                # J/m²  (PVA only)
    sim_beta: float = 0.15
    sim_f_snubbing: float = 0.20
    sim_n_delta_points: int = 300
    sim_P_anchor_max: float = 0.0       # N  (Steel only)
    sim_delta_hook: float = 0.5         # mm (Steel only)

    def simulation_signature(self) -> str:
        """
        Stable fingerprint for all inputs that affect theoretical σ–δ curves.

        The GUI may keep a simulated DataFrame cached while the user edits
        parameters.  This signature is stored on DataFrame.attrs at simulation
        time and checked in run_full_analysis() so stale curves cannot be used
        silently with new inputs.
        """
        parts = [
            self.sim_fiber_type,
            self.p_peak,
            self.d_f,
            self.l_e,
            self.sim_V_f,
            self.sim_L_f,
            self.sim_E_f,
            self.sim_sigma_fu,
            self.sim_G_d,
            self.sim_beta,
            self.sim_f_snubbing,
            self.sim_n_delta_points,
            self.sim_P_anchor_max,
            self.sim_delta_hook,
        ]
        payload = "|".join(str(x) for x in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class AnalysisResult:
    """Computed micromechanics outputs for one series."""

    # ------------------------------------------------------------------
    # Class-level thresholds (ClassVar — accessible without an instance).
    # These are the *only* authoritative copies in the codebase; all other
    # modules (e.g. result_table_model.py) must read from here.
    #
    # Basis: practical ECC/SHCC micromechanics design indices.
    #   PSH_strength >= 1.3  (accounts for material scatter)
    #   PSH_energy   >= 2.7  (accounts for size effects)
    # ------------------------------------------------------------------
    PSH_STRENGTH_THRESHOLD: ClassVar[float] = 1.3
    PSH_ENERGY_THRESHOLD:   ClassVar[float] = 2.7

    series_name: str
    variable_value: float

    tau0: float          # MPa
    km: float            # MPa·m^0.5
    j_tip: float         # J/m²
    sigma0: float        # MPa
    delta0: float        # mm
    jb_prime: float      # J/m²
    psh_strength: float  # dimensionless
    psh_energy: float    # dimensionless

    @property
    def psh_strength_pass(self) -> bool:
        return self.psh_strength >= self.PSH_STRENGTH_THRESHOLD

    @property
    def psh_energy_pass(self) -> bool:
        return self.psh_energy >= self.PSH_ENERGY_THRESHOLD


# ---------------------------------------------------------------------------
# Step 1 — Interface frictional bond stress
# ---------------------------------------------------------------------------

def calc_tau0(p_peak: float, d_f: float, l_e: float) -> float:
    """tau_0 = P_peak / (pi * d_f * L_e)  ->  MPa  (N / mm^2 = MPa)"""
    if p_peak <= 0.0:
        raise ValueError(f"P_peak must be positive; got {p_peak}")
    if d_f <= 0.0 or l_e <= 0.0:
        raise ValueError(f"d_f and l_e must be positive; got d_f={d_f}, l_e={l_e}")
    return p_peak / (math.pi * d_f * l_e)


# ---------------------------------------------------------------------------
# Step 2 — Matrix stress-intensity factor and crack-tip toughness
# ---------------------------------------------------------------------------

def _geometry_factor(alpha: float) -> float:
    """
    Gross-Srawley geometry correction F(alpha) for a single-edge-notched beam
    (SENB) under 3-point bending, alpha = a0/d.

    Reference: Gross, B. & Srawley, J.E. (1965), NASA TN D-2603;
    also ASTM E399-22, Annex A1, Eq. A1.2.
    Valid range: 0 < alpha < 1  (typically 0.2 <= alpha <= 0.7 in practice).

    Formula:
        F(alpha) = 3*sqrt(alpha) * [1.99 - alpha*(1-alpha)*(2.15 - 3.93*alpha + 2.7*alpha^2)]
                   / [2*(1 + 2*alpha)*(1 - alpha)^1.5]
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"a0/d ratio alpha={alpha:.4f} must be in (0, 1).")
    if not (0.1 <= alpha <= 0.9):
        raise ValueError(
            f"alpha={alpha:.4f} is outside the reliable range [0.1, 0.9] "
            "for the Gross-Srawley SENB formula."
        )
    numerator = (
        3.0 * math.sqrt(alpha)
        * (1.99 - alpha * (1.0 - alpha) * (2.15 - 3.93 * alpha + 2.7 * alpha ** 2))
    )
    denominator = 2.0 * (1.0 + 2.0 * alpha) * (1.0 - alpha) ** 1.5
    return numerator / denominator


def calc_km(p_max: float, span: float, b: float, d: float, a0: float) -> float:
    """
    K_m = (P_max * S) / (b * d^1.5) * f(a0/d)

    Input: N, mm  ->  Output: MPa*m^0.5
    Conversion: MPa*mm^0.5 / sqrt(1000) = MPa*m^0.5
    """
    if p_max <= 0.0:
        raise ValueError(f"P_max must be positive; got {p_max}")
    if span <= 0.0:
        raise ValueError(f"Span S must be positive; got {span}")
    if b <= 0.0 or d <= 0.0:
        raise ValueError("Specimen dimensions b and d must be positive.")
    alpha = a0 / d
    km_mm = (p_max * span) / (b * d ** 1.5) * _geometry_factor(alpha)
    return km_mm / math.sqrt(1_000.0)


def calc_j_tip(
    km: float,
    e_m_gpa: float,
    fracture_condition: str = "plane_stress",
    poisson_ratio: float = 0.20,
) -> float:
    """
    Crack-tip toughness from K_m.

    plane_stress: J_tip = K_m^2 / E
    plane_strain: J_tip = K_m^2 / E' where E' = E / (1 - nu^2)

    Units:
        km [MPa·m^0.5], E [GPa] → J/m² after multiplying MPa·m by 1e6.
    """
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

    e_m_mpa = e_m_gpa * 1_000.0
    if condition == "plane_strain":
        e_eff_mpa = e_m_mpa / (1.0 - poisson_ratio ** 2)
    else:
        e_eff_mpa = e_m_mpa

    return (km ** 2 / e_eff_mpa) * 1_000_000.0


# ---------------------------------------------------------------------------
# Step 3 — Fibre-bridging complementary energy
# ---------------------------------------------------------------------------

def _ensure_origin(delta: np.ndarray, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Ensure numerical integration covers 0 → δ0.

    Imported or simulated curves occasionally start from a small positive crack
    opening.  Omitting that initial segment overestimates J_b'.  We prepend a
    conservative origin when the first point is positive.
    """
    if delta[0] > 0.0:
        delta = np.insert(delta, 0, 0.0)
        sigma = np.insert(sigma, 0, 0.0)
    return delta, sigma


def calc_jb_prime(
    delta: np.ndarray,
    sigma: np.ndarray,
) -> tuple[float, float, float]:
    """
    Extract (sigma0, delta0) from the sigma-delta curve and compute J_b'.

    J_b' = sigma0 * delta0 - integral_0^delta0 sigma(delta) d_delta

    Uses scipy Simpson's rule (O(h^4)). Falls back to np.trapz when
    fewer than 3 points precede the peak — error negligible in that region.

    Returns: (sigma0 [MPa], delta0 [mm], jb_prime [J/m^2])
    Unit: MPa*mm * 1000 = J/m^2
    """
    if len(delta) != len(sigma):
        raise ValueError(
            "delta and sigma arrays must have the same length; "
            f"got {len(delta)} and {len(sigma)}."
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
        # NOTE: Simpson requires >= 3 points; trapezoid used as graceful
        # degradation when peak appears in the first two samples.
        area = float(np.trapz(s_up, x=d_up))

    jb_prime_mpa_mm = sigma0 * delta0 - area
    return sigma0, delta0, jb_prime_mpa_mm * 1_000.0


# ---------------------------------------------------------------------------
# Step 4 — PSH criteria
# ---------------------------------------------------------------------------

def calc_psh(
    sigma0: float,
    sigma_fc: float,
    jb_prime: float,
    j_tip: float,
) -> tuple[float, float]:
    """
    PSH_strength = sigma0 / sigma_fc   (engineering pass: >= 1.3)
    PSH_energy   = J_b' / J_tip        (engineering pass: >= 2.7)
    """
    if sigma0 <= 0.0:
        raise ValueError(f"sigma0 must be positive; got {sigma0}")
    if sigma_fc <= 0.0:
        raise ValueError(f"sigma_fc must be positive; got {sigma_fc}")
    if jb_prime <= 0.0:
        raise ValueError(f"J_b' must be positive; got {jb_prime}")
    if j_tip <= 0.0:
        raise ValueError(f"J_tip must be positive; got {j_tip}")
    return sigma0 / sigma_fc, jb_prime / j_tip


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------

def _validate_sigma_delta_provenance(params: SeriesParams, df: pd.DataFrame) -> None:
    """Reject stale or mismatched σ–δ data before any physics calculation."""
    source = params.sigma_delta_source
    actual_source = df.attrs.get("source")

    if source not in {"csv", "simulation"}:
        raise ValueError(
            f"Series '{params.name}' has no active σ–δ source. "
            "Import a CSV or run theoretical simulation first."
        )

    if actual_source is not None and actual_source != source:
        raise ValueError(
            f"Series '{params.name}' is set to '{source}', but the loaded σ–δ curve "
            f"was generated from '{actual_source}'. Re-import or re-simulate the curve."
        )

    if source == "simulation":
        expected = params.simulation_signature()
        actual = df.attrs.get("simulation_signature")
        if actual != expected:
            raise ValueError(
                f"Series '{params.name}' has a stale simulated σ–δ curve. "
                "Simulation parameters changed after the curve was generated. "
                "Run Simulation again before analysis."
            )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_full_analysis(params: SeriesParams) -> AnalysisResult:
    """
    Run all four calculation stages for one series.
    Raises ValueError on physically inconsistent inputs.
    Must be called from a QThread worker, never from the main thread.
    """
    if params.sigma_delta_df is None:
        raise ValueError(
            f"Series '{params.name}' has no sigma-delta data. Import a CSV or run simulation first."
        )

    df = params.sigma_delta_df
    _validate_sigma_delta_provenance(params, df)

    missing_cols = [c for c in ("delta", "sigma") if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Series '{params.name}' sigma-delta data is missing column(s): {missing_cols}"
        )

    delta_arr = df["delta"].to_numpy(dtype=float)
    sigma_arr = df["sigma"].to_numpy(dtype=float)

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
