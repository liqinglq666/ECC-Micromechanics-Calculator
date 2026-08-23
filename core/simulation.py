"""core/simulation.py

Theoretical σ-δ bridging curve simulation engine based on the ECC/SHCC
micromechanics framework.

Architecture: Strategy Pattern for fiber pullout physics.
  - FiberPulloutModel (ABC) defines the interface.
  - PEFiberModel / PVAFiberModel / SteelFiberModel implement P(δ, l, θ).
  - simulate_sigma_delta owns the double-integral framework and is fiber-agnostic.

Unit conventions:
  length → mm | stress → MPa | modulus → GPa | energy → J/m²
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

# ---------------------------------------------------------------------------
# Numba JIT — compiled ONCE at module level, graceful degradation when absent
# ---------------------------------------------------------------------------

try:
    import numba  # type: ignore

    _NUMBA_AVAILABLE = True

    @numba.jit(nopython=True, cache=True)
    def _jit_pe_straight(
        delta: float,
        l: float,
        d_f: float,
        tau_0: float,
        beta: float,
    ) -> float:
        """PE straight-pullout force kernel, Numba-compiled."""
        remaining = l - delta
        if remaining <= 0.0:
            return 0.0
        return math.pi * d_f * tau_0 * remaining * (1.0 + beta * delta / d_f)

except ImportError:
    _NUMBA_AVAILABLE = False
    warnings.warn(
        "numba is not installed. σ-δ simulation will run in pure-SciPy mode, "
        "which may be slower. Install the optional accel dependency for production use.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Fiber type enumeration
# ---------------------------------------------------------------------------

class FiberType(Enum):
    PE = auto()     # Polyethylene — smooth, no chemical bond, slip-hardening
    PVA = auto()    # Polyvinyl alcohol — bonded, chemical debonding approximation
    STEEL = auto()  # Steel hooked-end — friction + simplified anchorage


# ---------------------------------------------------------------------------
# Simulation parameter containers
# ---------------------------------------------------------------------------

@dataclass
class CommonFiberParams:
    """Parameters shared by all fiber types and the integration framework."""

    V_f: float             # fiber volume fraction (–), e.g. 0.02
    L_f: float             # fiber length (mm)
    d_f: float             # fiber diameter (mm)
    E_f: float             # fiber elastic modulus (GPa)
    sigma_fu: float        # fiber tensile strength (MPa)
    tau_0: float           # interface frictional bond stress (MPa)
    f_snubbing: float      # snubbing coefficient (–)
    n_delta_points: int = 300

    def validate(self) -> None:
        if not (0.0 <= self.V_f <= 1.0):
            raise ValueError(f"V_f must be in [0, 1]; got {self.V_f}")
        if self.L_f <= 0.0:
            raise ValueError(f"L_f must be positive; got {self.L_f}")
        if self.d_f <= 0.0:
            raise ValueError(f"d_f must be positive; got {self.d_f}")
        if self.E_f <= 0.0:
            raise ValueError(f"E_f must be positive; got {self.E_f}")
        if self.sigma_fu <= 0.0:
            raise ValueError(f"sigma_fu must be positive; got {self.sigma_fu}")
        if self.tau_0 <= 0.0:
            raise ValueError(f"tau_0 must be positive; got {self.tau_0}")
        if self.f_snubbing < 0.0:
            raise ValueError(f"f_snubbing cannot be negative; got {self.f_snubbing}")
        if self.n_delta_points < 2:
            raise ValueError("n_delta_points must be at least 2.")


@dataclass
class PEFiberParams:
    """Additional parameters specific to PE/PP fibers."""

    beta: float = 0.15

    def validate(self) -> None:
        if self.beta < 0.0:
            raise ValueError(f"beta cannot be negative; got {self.beta}")


@dataclass
class PVAFiberParams:
    """Additional parameters specific to PVA fibers."""

    G_d: float = 3.0      # chemical bond energy (J/m²)
    beta: float = 0.50

    def validate(self) -> None:
        if self.G_d < 0.0:
            raise ValueError(f"G_d cannot be negative; got {self.G_d}")
        if self.beta < 0.0:
            raise ValueError(f"beta cannot be negative; got {self.beta}")


@dataclass
class SteelFiberParams:
    """Additional parameters specific to hooked-end steel fibers."""

    P_anchor_max: float = 0.0   # N — peak anchorage force per fiber
    delta_hook: float = 0.5     # mm — slip distance to fully straighten hook

    def validate(self) -> None:
        if self.P_anchor_max < 0.0:
            raise ValueError(f"P_anchor_max cannot be negative; got {self.P_anchor_max}")
        if self.delta_hook < 0.0:
            raise ValueError(f"delta_hook cannot be negative; got {self.delta_hook}")


# ---------------------------------------------------------------------------
# Abstract fiber pullout model (Strategy interface)
# ---------------------------------------------------------------------------

class FiberPulloutModel(ABC):
    """Single-fiber pullout force model P(δ, l, θ)."""

    def __init__(self, common: CommonFiberParams) -> None:
        self._c = common
        self._A_f: float = math.pi * common.d_f ** 2 / 4.0   # mm²
        self._rupture_force: float = common.sigma_fu * self._A_f  # N

    @abstractmethod
    def _straight_pullout(self, delta: float, l: float) -> float:
        """Pullout force for a fiber perpendicular to the crack plane."""
        ...

    def get_pullout_force(self, delta: float, l: float, theta: float) -> float:
        """Apply snubbing amplification and rupture cutoff."""
        p_straight = self._straight_pullout(delta, l)
        p_snubbed = p_straight * math.exp(self._c.f_snubbing * theta)

        # Fiber rupture boundary — once exceeded, bridging contribution is lost.
        if p_snubbed > self._rupture_force:
            return 0.0
        return p_snubbed


# ---------------------------------------------------------------------------
# PE / PP fiber model
# ---------------------------------------------------------------------------

class PEFiberModel(FiberPulloutModel):
    """Smooth PE/PP fiber: frictional sliding plus slip-hardening."""

    def __init__(self, common: CommonFiberParams, pe_params: PEFiberParams) -> None:
        pe_params.validate()
        super().__init__(common)
        self._beta = pe_params.beta

    def _straight_pullout(self, delta: float, l: float) -> float:
        remaining_embed = l - delta
        if remaining_embed <= 0.0:
            return 0.0
        hardening = 1.0 + self._beta * delta / self._c.d_f
        return math.pi * self._c.d_f * self._c.tau_0 * remaining_embed * hardening


# ---------------------------------------------------------------------------
# PVA fiber model
# ---------------------------------------------------------------------------

class PVAFiberModel(FiberPulloutModel):
    """
    Simplified PVA pullout model.

    Stage 1: chemical debonding ramp.
    Stage 2: frictional sliding plus slip-hardening.
    """

    def __init__(self, common: CommonFiberParams, pva_params: PVAFiberParams) -> None:
        pva_params.validate()
        super().__init__(common)
        self._G_d = pva_params.G_d
        self._beta = pva_params.beta

        G_d_Nmm = pva_params.G_d * 1e-3          # J/m² → N/mm
        E_f_Nmm2 = common.E_f * 1_000.0          # GPa → N/mm²
        tau0_Nmm2 = common.tau_0                 # MPa = N/mm²

        numerator = G_d_Nmm * E_f_Nmm2 * self._A_f
        denominator = math.pi * common.d_f * tau0_Nmm2 ** 2
        arg = numerator / max(denominator, 1e-30)
        self._delta_d: float = max(math.sqrt(arg), 1e-9)  # mm

    def _straight_pullout(self, delta: float, l: float) -> float:
        remaining_embed = l - delta
        if remaining_embed <= 0.0:
            return 0.0

        if delta < self._delta_d:
            fraction = delta / self._delta_d
            p_peak_debond = math.pi * self._c.d_f * self._c.tau_0 * remaining_embed
            return p_peak_debond * fraction ** 2

        hardening = 1.0 + self._beta * delta / self._c.d_f
        return math.pi * self._c.d_f * self._c.tau_0 * remaining_embed * hardening


# ---------------------------------------------------------------------------
# Steel (hooked-end) fiber model
# ---------------------------------------------------------------------------

class SteelFiberModel(FiberPulloutModel):
    """Simplified hooked-end steel fiber: friction + linearly decaying anchorage."""

    def __init__(self, common: CommonFiberParams, steel_params: SteelFiberParams) -> None:
        steel_params.validate()
        super().__init__(common)
        self._P_anchor_max = steel_params.P_anchor_max
        self._delta_hook = steel_params.delta_hook

    def _straight_pullout(self, delta: float, l: float) -> float:
        remaining_embed = l - delta
        if remaining_embed <= 0.0:
            return 0.0

        p_friction = math.pi * self._c.d_f * self._c.tau_0 * remaining_embed

        if delta < self._delta_hook and self._delta_hook > 0.0:
            p_anchor = self._P_anchor_max * (1.0 - delta / self._delta_hook)
        else:
            p_anchor = 0.0

        return p_friction + p_anchor


# ---------------------------------------------------------------------------
# Double-integral simulation engine
# ---------------------------------------------------------------------------

def _make_integrand(
    delta: float,
    pullout_model: FiberPulloutModel,
) -> Callable[[float, float], float]:
    """
    Return integrand(l, theta) for scipy.dblquad.

    dblquad calls f(inner_var, outer_var), so f(l, theta) is correct for:
      theta ∈ [0, π/2], l ∈ [0, L_f/2]
    """
    if _NUMBA_AVAILABLE and isinstance(pullout_model, PEFiberModel):
        d_f_ = pullout_model._c.d_f
        tau_0_ = pullout_model._c.tau_0
        f_s_ = pullout_model._c.f_snubbing
        rupture_ = pullout_model._rupture_force
        beta_ = pullout_model._beta

        def integrand(l_: float, theta_: float) -> float:
            p = _jit_pe_straight(delta, l_, d_f_, tau_0_, beta_)
            p_snubbed = p * math.exp(f_s_ * theta_)
            if p_snubbed > rupture_:
                return 0.0
            return p_snubbed * math.sin(theta_)

    else:
        def integrand(l_: float, theta_: float) -> float:
            p = pullout_model.get_pullout_force(delta, l_, theta_)
            return p * math.sin(theta_)

    return integrand


def simulate_sigma_delta(
    common: CommonFiberParams,
    pullout_model: FiberPulloutModel,
    progress_callback: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """
    Compute macroscopic bridging stress σ(δ) via double integration.

    σ(δ) = (8 V_f) / (π d_f² L_f) ∫₀^(π/2) ∫₀^(L_f/2)
           P(δ,l,θ)·sin(θ) dl dθ

    The returned curve starts at δ = 0 so J_b' integration covers the full
    complementary-energy rectangle and does not overestimate PSH_energy.
    """
    common.validate()

    delta_arr = np.linspace(0.0, common.L_f / 2.0, common.n_delta_points)

    prefactor = (8.0 * common.V_f) / (math.pi * common.d_f ** 2 * common.L_f)
    sigma_values: list[float] = []
    total = len(delta_arr)

    for idx, delta in enumerate(delta_arr):
        integrand = _make_integrand(float(delta), pullout_model)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", IntegrationWarning)

            result, _abserr = dblquad(
                integrand,
                0.0,
                math.pi / 2.0,
                0.0,
                common.L_f / 2.0,
                epsabs=1e-4,
                epsrel=1e-4,
            )

            if caught:
                warnings.warn(
                    f"Integration warning at δ={delta:.4f} mm: {caught[0].message}",
                    stacklevel=2,
                )

        sigma_values.append(prefactor * result)

        if progress_callback is not None:
            progress_callback(idx + 1, total)

    df = pd.DataFrame({"delta": delta_arr, "sigma": np.array(sigma_values)})
    df.attrs["source"] = "simulation"
    return df


# ---------------------------------------------------------------------------
# Factory helpers — called by UI layer to construct the right strategy
# ---------------------------------------------------------------------------

def build_pullout_model(
    fiber_type: FiberType,
    common: CommonFiberParams,
    pe_params: PEFiberParams | None = None,
    pva_params: PVAFiberParams | None = None,
    steel_params: SteelFiberParams | None = None,
) -> FiberPulloutModel:
    """Instantiate the correct FiberPulloutModel subclass based on fiber_type."""
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
        steel_params = steel_params or SteelFiberParams()
        return SteelFiberModel(common, steel_params)

    raise ValueError(f"Unsupported fiber type: {fiber_type!r}")
