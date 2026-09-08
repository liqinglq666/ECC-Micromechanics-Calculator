"""Theoretical sigma-delta bridging simulation for ECC/SHCC.

The PE/PVA paths implement the one-way Lin/Li debonding -> frictional pullout
baseline. Random fibre orientation can be represented as 2-D planar or 3-D
isotropic. Inclination-dependent snubbing and fibre-strength reduction are
handled separately, and fibre rupture is irreversible.

The one-way PVA path is benchmarkable against the "previous simplified model"
reported by Yang et al. (2008). Two-way pullout, matrix micro-spalling, and
Cook-Gordon effects are intentionally not represented here.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

import numpy as np
import pandas as pd
from numpy.polynomial.legendre import leggauss


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
    sigma_fu: float     # MPa, strength at zero inclination
    tau_0: float        # MPa
    f_snubbing: float
    n_delta_points: int = 300
    E_m: float | None = None  # GPa; eta = Vf Ef / (Vm Em)
    f_strength_reduction: float = 0.0
    orientation: str = "3d"   # "3d" isotropic | "2d" planar random

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
        if self.f_strength_reduction < 0.0:
            raise ValueError(
                "f_strength_reduction cannot be negative; "
                f"got {self.f_strength_reduction}"
            )
        if self.orientation not in {"2d", "3d"}:
            raise ValueError(
                f"orientation must be '2d' or '3d'; got {self.orientation!r}"
            )
        if self.n_delta_points < 2:
            raise ValueError("n_delta_points must be at least 2.")

    @property
    def eta(self) -> float:
        """Effective fibre/matrix stiffness ratio used by the interface model."""
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
    G_d: float = 3.0      # J/m^2
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
    """Single-fibre P(delta, l, theta) with path-dependent rupture."""

    def __init__(self, common: CommonFiberParams) -> None:
        self._c = common
        self._A_f = math.pi * common.d_f**2 / 4.0
        self._rupture_force_0 = common.sigma_fu * self._A_f

    @abstractmethod
    def _straight_pullout(self, delta: float, l: float) -> float:
        ...

    @abstractmethod
    def _max_straight_pullout_up_to(self, delta: float, l: float) -> float:
        ...

    def max_debond_displacement(self, l: float) -> float:
        return 0.0

    def expects_zero_origin(self) -> bool:
        """Whether this interface law should give P(delta=0)=0."""
        return True

    def rupture_force(self, theta: float) -> float:
        """Inclination-reduced tensile capacity, Yang et al. Eq. (7)."""
        return self._rupture_force_0 * math.exp(
            -self._c.f_strength_reduction * theta
        )

    def get_pullout_force(self, delta: float, l: float, theta: float) -> float:
        if delta < 0.0 or l <= 0.0:
            return 0.0
        snub = math.exp(self._c.f_snubbing * theta)
        historical_max = self._max_straight_pullout_up_to(delta, l) * snub
        if historical_max > self.rupture_force(theta):
            return 0.0
        return self._straight_pullout(delta, l) * snub


class _DebondSlidingModel(FiberPulloutModel):
    """Lin/Li one-way debonding followed by frictional sliding."""

    def __init__(self, common: CommonFiberParams, beta: float) -> None:
        super().__init__(common)
        self._beta = beta

    def _gd_n_per_mm(self) -> float:
        return 0.0

    def _debond_displacement(self, l: float) -> float:
        """Complete-debond displacement (Yang et al. 2008, Eq. 5/14)."""
        ef = self._c.E_f * 1000.0
        d = self._c.d_f
        tau = self._c.tau_0
        eta1 = 1.0 + self._c.eta
        gd = self._gd_n_per_mm()
        friction_term = 2.0 * tau * l**2 * eta1 / (ef * d)
        chemical_term = math.sqrt(
            max(0.0, 8.0 * gd * l**2 * eta1 / (ef * d))
        )
        return max(friction_term + chemical_term, 1e-12)

    def max_debond_displacement(self, l: float) -> float:
        return self._debond_displacement(l)

    def _debond_force(self, delta: float, l: float) -> float:
        """Debond force from Yang et al. (2008) Eq. (12)."""
        ef = self._c.E_f * 1000.0
        d = self._c.d_f
        eta1 = 1.0 + self._c.eta
        energy = self._c.tau_0 * max(delta, 0.0) + self._gd_n_per_mm()
        return math.pi * math.sqrt(
            max(0.0, ef * d**3 * eta1 * energy / 2.0)
        )

    def _sliding_force(self, slip: float, l: float) -> float:
        """Post-debond one-way pullout force (Yang et al. Eq. 13)."""
        if slip < 0.0 or slip >= l:
            return 0.0
        multiplier = max(0.0, 1.0 + self._beta * slip / self._c.d_f)
        return (
            math.pi
            * self._c.d_f
            * self._c.tau_0
            * (l - slip)
            * multiplier
        )

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
        debond_at = min(max(delta, 0.0), delta_d)
        maximum = self._debond_force(debond_at, l)
        if delta > delta_d:
            maximum = max(
                maximum,
                self._sliding_max(delta - delta_d, l),
            )
        return maximum


class PEFiberModel(_DebondSlidingModel):
    """PE/PP: G_d ~= 0, debonding followed by frictional pullout."""

    def __init__(self, common: CommonFiberParams, pe_params: PEFiberParams) -> None:
        pe_params.validate()
        super().__init__(common, pe_params.beta)


class PVAFiberModel(_DebondSlidingModel):
    """PVA one-way baseline with chemical bond and slip hardening."""

    def __init__(self, common: CommonFiberParams, pva_params: PVAFiberParams) -> None:
        pva_params.validate()
        super().__init__(common, pva_params.beta)
        self._G_d = pva_params.G_d

    def _gd_n_per_mm(self) -> float:
        return self._G_d * 1e-3

    def expects_zero_origin(self) -> bool:
        # Eq. (12) contains G_d, so a chemically bonded PVA interface may have
        # a finite debond-initiation traction at zero crack opening.
        return self._G_d <= 0.0


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
        friction = (
            math.pi
            * self._c.d_f
            * self._c.tau_0
            * (l - delta)
            * mobilization
        )
        return friction + self._anchor_force(delta)

    def _max_straight_pullout_up_to(self, delta: float, l: float) -> float:
        upper = min(max(delta, 0.0), l)
        if upper <= 0.0:
            return 0.0
        candidates = np.linspace(0.0, upper, 25)
        return max(self._straight_pullout(float(x), l) for x in candidates)


def _orientation_weight(theta: float, orientation: str) -> float:
    """Probability density times crack-crossing Jacobian."""
    if orientation == "3d":
        # p(theta)=sin(theta); dz -> dl contributes cos(theta)
        return math.sin(theta) * math.cos(theta)
    if orientation == "2d":
        # p(theta)=2/pi; dz -> dl contributes cos(theta)
        return (2.0 / math.pi) * math.cos(theta)
    raise ValueError(f"Unsupported orientation mode: {orientation!r}")


def _make_integrand(
    delta: float,
    pullout_model: FiberPulloutModel,
) -> Callable[[float, float], float]:
    orientation = pullout_model._c.orientation

    def integrand(l_: float, theta_: float) -> float:
        p = pullout_model.get_pullout_force(delta, l_, theta_)
        return p * _orientation_weight(theta_, orientation)

    return integrand


def simulate_sigma_at_delta(
    common: CommonFiberParams,
    pullout_model: FiberPulloutModel,
    delta: float,
    integration_order: int = 64,
) -> float:
    """Evaluate macroscopic bridging stress at one crack opening.

    Tensor-product Gauss-Legendre quadrature is used instead of adaptive
    dblquad. The fixed rule is deterministic and much faster for a full
    sigma-delta sweep while retaining sub-percent agreement for the literature
    benchmark at the default order.
    """
    common.validate()
    if common.V_f <= 0.0:
        raise ValueError("V_f must be greater than 0 for bridging simulation.")
    if delta < 0.0:
        raise ValueError(f"delta cannot be negative; got {delta}")
    if integration_order < 8:
        raise ValueError("integration_order must be at least 8.")

    nodes, weights = leggauss(integration_order)

    theta = (math.pi / 4.0) * (nodes + 1.0)
    theta_weights = (math.pi / 4.0) * weights

    max_embed = common.L_f / 2.0
    embedment = (max_embed / 2.0) * (nodes + 1.0)
    embedment_weights = (max_embed / 2.0) * weights

    result = 0.0
    for i, theta_i in enumerate(theta):
        orientation_weight = _orientation_weight(
            float(theta_i), common.orientation
        )
        inner = 0.0
        for j, l_j in enumerate(embedment):
            inner += (
                embedment_weights[j]
                * pullout_model.get_pullout_force(
                    float(delta), float(l_j), float(theta_i)
                )
            )
        result += theta_weights[i] * orientation_weight * inner

    prefactor = (8.0 * common.V_f) / (
        math.pi * common.d_f**2 * common.L_f
    )
    return float(prefactor * result)


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
    sigma_values: list[float] = []
    total = len(delta_arr)

    for idx, delta in enumerate(delta_arr):
        sigma_values.append(
            simulate_sigma_at_delta(common, pullout_model, float(delta))
        )
        if progress_callback is not None:
            progress_callback(idx + 1, total)

    df = pd.DataFrame(
        {"delta": delta_arr, "sigma": np.asarray(sigma_values, dtype=float)}
    )
    df.attrs["source"] = "simulation"
    df.attrs["model_version"] = "one-way-yang2008-v3"
    df.attrs["orientation"] = common.orientation
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
