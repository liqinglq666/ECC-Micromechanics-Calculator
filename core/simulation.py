"""Theoretical sigma-delta bridging simulation for ECC/SHCC.

The PE path implements a debonding -> frictional pullout law rather than the
previous preload-at-delta=0 approximation. Random 3-D orientation uses the
crossing-probability factor sin(theta)*cos(theta). Fibre rupture is irreversible:
once the historical pullout force exceeds tensile capacity, that fibre never
contributes again at larger crack openings.

PVA and hooked steel remain explicitly simplified mechanistic models; use
experimentally measured sigma-delta curves for publication-grade quantitative
claims unless those branches are independently calibrated.
"""
from __future__ import annotations

import math
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

import numpy as np
import pandas as pd
from scipy.integrate import IntegrationWarning, dblquad


class FiberType(Enum):
    PE = auto()
    PVA = auto()
    STEEL = auto()


@dataclass
class CommonFiberParams:
    V_f: float
    L_f: float
    d_f: float
    E_f: float          # GPa
    sigma_fu: float     # MPa
    tau_0: float        # MPa
    f_snubbing: float
    n_delta_points: int = 300
    E_m: float | None = None  # GPa; used in eta = Vf Ef / (Vm Em)

    def validate(self) -> None:
        if not (0.0 <= self.V_f < 1.0):
            raise ValueError(f"V_f must be in [0, 1); got {self.V_f}")
        if self.L_f <= 0.0:
            raise ValueError(f"L_f must be positive; got {self.L_f}")
        if self.d_f <= 0.0:
            raise ValueError(f"d_f must be positive; got {self.d_f}")
        if self.E_f <= 0.0:
            raise ValueError(f"E_f must be positive; got {self.E_f}")
        if self.E_m is not None and self.E_m <= 0.0:
            raise ValueError(f"E_m must be positive when supplied; got {self.E_m}")
        if self.sigma_fu <= 0.0:
            raise ValueError(f"sigma_fu must be positive; got {self.sigma_fu}")
        if self.tau_0 <= 0.0:
            raise ValueError(f"tau_0 must be positive; got {self.tau_0}")
        if self.f_snubbing < 0.0:
            raise ValueError(f"f_snubbing cannot be negative; got {self.f_snubbing}")
        if self.n_delta_points < 2:
            raise ValueError("n_delta_points must be at least 2.")

    @property
    def eta(self) -> float:
        """Composite stiffness ratio used by the debonding model."""
        if self.E_m is None:
            return 0.0
        v_m = 1.0 - self.V_f
        return (self.V_f * self.E_f) / (v_m * self.E_m)


@dataclass
class PEFiberParams:
    beta: float = 0.0

    def validate(self) -> None:
        if self.beta < -1.0:
            raise ValueError(f"beta is unrealistically negative; got {self.beta}")


@dataclass
class PVAFiberParams:
    G_d: float = 3.0
    beta: float = 0.50

    def validate(self) -> None:
        if self.G_d < 0.0:
            raise ValueError(f"G_d cannot be negative; got {self.G_d}")
        if self.beta < -1.0:
            raise ValueError(f"beta is unrealistically negative; got {self.beta}")


@dataclass
class SteelFiberParams:
    P_anchor_max: float = 0.0
    delta_hook: float = 0.5

    def validate(self) -> None:
        if self.P_anchor_max < 0.0:
            raise ValueError(f"P_anchor_max cannot be negative; got {self.P_anchor_max}")
        if self.delta_hook < 0.0:
            raise ValueError(f"delta_hook cannot be negative; got {self.delta_hook}")


class FiberPulloutModel(ABC):
    """Single-fibre P(delta, l, theta) with irreversible rupture."""

    def __init__(self, common: CommonFiberParams) -> None:
        self._c = common
        self._A_f = math.pi * common.d_f**2 / 4.0
        self._rupture_force = common.sigma_fu * self._A_f

    @abstractmethod
    def _straight_pullout(self, delta: float, l: float) -> float:
        ...

    @abstractmethod
    def _max_straight_pullout_up_to(self, delta: float, l: float) -> float:
        ...

    def max_debond_displacement(self, l: float) -> float:
        return 0.0

    def get_pullout_force(self, delta: float, l: float, theta: float) -> float:
        if delta < 0.0 or l <= 0.0:
            return 0.0
        snub = math.exp(self._c.f_snubbing * theta)
        historical_max = self._max_straight_pullout_up_to(delta, l) * snub
        if historical_max > self._rupture_force:
            return 0.0
        return self._straight_pullout(delta, l) * snub


class _DebondSlidingModel(FiberPulloutModel):
    """Shared Lin-type debonding + frictional sliding mechanics."""

    def __init__(self, common: CommonFiberParams, beta: float) -> None:
        super().__init__(common)
        self._beta = beta

    def _gd_n_per_mm(self) -> float:
        return 0.0

    def _debond_displacement(self, l: float) -> float:
        # Lin/Gao-type complete-debond displacement. G_d is J/m^2 = 1e-3 N/mm.
        ef = self._c.E_f * 1000.0
        d = self._c.d_f
        tau = self._c.tau_0
        eta1 = 1.0 + self._c.eta
        gd = self._gd_n_per_mm()
        friction_term = 2.0 * tau * l**2 * eta1 / (ef * d)
        chemical_term = math.sqrt(max(0.0, 8.0 * gd * l**2 * eta1 / (ef * d)))
        return max(friction_term + chemical_term, 1e-12)

    def max_debond_displacement(self, l: float) -> float:
        return self._debond_displacement(l)

    def _debond_force(self, delta: float, l: float) -> float:
        """Override in subclasses when chemical debonding is treated differently."""
        ef = self._c.E_f * 1000.0
        d = self._c.d_f
        tau = self._c.tau_0
        eta1 = 1.0 + self._c.eta
        return math.pi * math.sqrt(max(0.0, ef * d**3 * tau * eta1 * delta / 2.0))

    def _sliding_force(self, slip: float, l: float) -> float:
        if slip < 0.0 or slip >= l:
            return 0.0
        multiplier = max(0.0, 1.0 + self._beta * slip / self._c.d_f)
        return math.pi * self._c.d_f * self._c.tau_0 * (l - slip) * multiplier

    def _straight_pullout(self, delta: float, l: float) -> float:
        delta_d = self._debond_displacement(l)
        if delta <= delta_d:
            return self._debond_force(delta, l)
        return self._sliding_force(delta - delta_d, l)

    def _sliding_max(self, max_slip: float, l: float) -> float:
        max_slip = min(max(max_slip, 0.0), l)
        candidates = [0.0, max_slip]
        beta = self._beta
        if beta != 0.0:
            x_star = (beta * l - self._c.d_f) / (2.0 * beta)
            if 0.0 < x_star < max_slip:
                candidates.append(x_star)
        return max(self._sliding_force(x, l) for x in candidates)

    def _max_straight_pullout_up_to(self, delta: float, l: float) -> float:
        delta_d = self._debond_displacement(l)
        debond_at = min(delta, delta_d)
        maximum = self._debond_force(debond_at, l)
        if delta > delta_d:
            maximum = max(maximum, self._sliding_max(delta - delta_d, l))
        return maximum


class PEFiberModel(_DebondSlidingModel):
    """PE/PP: frictional debonding (G_d ~= 0) followed by sliding."""

    def __init__(self, common: CommonFiberParams, pe_params: PEFiberParams) -> None:
        pe_params.validate()
        super().__init__(common, pe_params.beta)


class PVAFiberModel(_DebondSlidingModel):
    """Simplified PVA model with chemical-debond peak and frictional sliding."""

    def __init__(self, common: CommonFiberParams, pva_params: PVAFiberParams) -> None:
        pva_params.validate()
        super().__init__(common, pva_params.beta)
        self._G_d = pva_params.G_d

    def _gd_n_per_mm(self) -> float:
        return self._G_d * 1e-3

    def _debond_force(self, delta: float, l: float) -> float:
        # Publication-grade PVA should be calibrated from P_a/P_b. This ramp
        # keeps sigma(0)=0 while preserving a chemical-bond-enhanced debond peak.
        delta_d = self._debond_displacement(l)
        if delta <= 0.0:
            return 0.0
        ef = self._c.E_f * 1000.0
        d = self._c.d_f
        eta1 = 1.0 + self._c.eta
        friction_peak = math.pi * d * self._c.tau_0 * l
        chemical_peak = math.pi * math.sqrt(max(0.0, self._gd_n_per_mm() * ef * d**3 * eta1 / 2.0))
        peak = friction_peak + chemical_peak
        return peak * math.sqrt(min(delta / delta_d, 1.0))


class SteelFiberModel(FiberPulloutModel):
    """Simplified hooked steel: friction + zero-preload triangular anchorage."""

    def __init__(self, common: CommonFiberParams, steel_params: SteelFiberParams) -> None:
        steel_params.validate()
        super().__init__(common)
        self._P_anchor_max = steel_params.P_anchor_max
        self._delta_hook = steel_params.delta_hook

    def _anchor_force(self, delta: float) -> float:
        if self._delta_hook <= 0.0 or delta <= 0.0 or delta >= self._delta_hook:
            return 0.0
        half = self._delta_hook / 2.0
        if delta <= half:
            return self._P_anchor_max * delta / half
        return self._P_anchor_max * (self._delta_hook - delta) / half

    def _straight_pullout(self, delta: float, l: float) -> float:
        if delta <= 0.0 or delta >= l:
            return 0.0
        mobilization = min(delta / max(self._c.d_f, 1e-12), 1.0)
        friction = math.pi * self._c.d_f * self._c.tau_0 * (l - delta) * mobilization
        return friction + self._anchor_force(delta)

    def _max_straight_pullout_up_to(self, delta: float, l: float) -> float:
        upper = min(max(delta, 0.0), l)
        if upper <= 0.0:
            return 0.0
        candidates = np.linspace(0.0, upper, 25)
        return max(self._straight_pullout(float(x), l) for x in candidates)


def _make_integrand(delta: float, pullout_model: FiberPulloutModel) -> Callable[[float, float], float]:
    """Return f(l, theta) including 3-D orientation and crack-crossing weight."""
    def integrand(l_: float, theta_: float) -> float:
        p = pullout_model.get_pullout_force(delta, l_, theta_)
        return p * math.sin(theta_) * math.cos(theta_)

    return integrand


def simulate_sigma_delta(
    common: CommonFiberParams,
    pullout_model: FiberPulloutModel,
    progress_callback: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Compute macroscopic bridging stress sigma(delta) by double integration."""
    common.validate()
    if common.V_f <= 0.0:
        raise ValueError("V_f must be greater than 0 for bridging simulation.")

    max_embed = common.L_f / 2.0
    delta_max = max_embed + pullout_model.max_debond_displacement(max_embed)
    delta_arr = np.linspace(0.0, delta_max, common.n_delta_points)

    prefactor = (8.0 * common.V_f) / (math.pi * common.d_f**2 * common.L_f)
    sigma_values: list[float] = []
    total = len(delta_arr)

    for idx, delta in enumerate(delta_arr):
        if delta == 0.0:
            sigma_values.append(0.0)
        else:
            integrand = _make_integrand(float(delta), pullout_model)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", IntegrationWarning)
                result, _abserr = dblquad(
                    integrand,
                    0.0,
                    math.pi / 2.0,
                    0.0,
                    max_embed,
                    epsabs=1e-4,
                    epsrel=1e-4,
                )
                if caught:
                    warnings.warn(
                        f"Integration warning at delta={delta:.4f} mm: {caught[0].message}",
                        stacklevel=2,
                    )
            sigma_values.append(prefactor * result)

        if progress_callback is not None:
            progress_callback(idx + 1, total)

    df = pd.DataFrame({"delta": delta_arr, "sigma": np.asarray(sigma_values, dtype=float)})
    df.attrs["source"] = "simulation"
    df.attrs["model_version"] = "debond-orientation-irreversible-v2"
    return df


def build_pullout_model(
    fiber_type: FiberType,
    common: CommonFiberParams,
    pe_params: PEFiberParams | None = None,
    pva_params: PVAFiberParams | None = None,
    steel_params: SteelFiberParams | None = None,
) -> FiberPulloutModel:
    common.validate()

    if fiber_type is FiberType.PE:
        if pe_params is None:
            raise ValueError("PEFiberParams required for FiberType.PE")
        return PEFiberModel(common, pe_params)
    if fiber_type is FiberType.PVA:
        if pva_params is None:
            raise ValueError("PVAFiberParams required for FiberType.PVA")
        return PVAFiberModel(common, pva_params)
    if fiber_type is FiberType.STEEL:
        return SteelFiberModel(common, steel_params or SteelFiberParams())
    raise ValueError(f"Unsupported fiber type: {fiber_type!r}")
