"""core/simulation.py

Theoretical σ-δ bridging curve simulation engine based on Victor C. Li's
micromechanics model (Li & Leung 1992; Li 1993).

Architecture: Strategy Pattern for fiber pullout physics.
  - FiberPulloutModel (ABC) defines the interface.
  - PEFiberModel / PVAFiberModel / SteelFiberModel implement P(δ, l, θ).
  - SimulationEngine owns the double-integral framework and is fiber-agnostic.

The double-integral kernel function is accelerated with Numba JIT where
available (PE fiber only — PVA/Steel use pure-SciPy path due to model
complexity). On import failure, a pure-Python fallback is used automatically
and a warning is issued — the program never crashes due to missing Numba.

Unit conventions (enforced throughout):
  length → mm | stress → MPa | modulus → GPa | energy → J/m²

Fix log
-------
v2  2026-06-03
  [BUG-1] Numba path in _make_integrand was hardcoded to PE slip-hardening
          formula regardless of actual pullout_model type. PVA/Steel results
          were silently wrong. Fix: Numba acceleration is now gated on
          isinstance(pullout_model, PEFiberModel).
  [BUG-2] PVA _delta_d formula had a unit inconsistency:
          G_d_Nmm [N/mm] × E_f_mpa [N/mm²] × A_f [mm²] / (τ₀ [N/mm²] × d_f [mm])
          = N·mm → sqrt → mm^0.5  (wrong).
          Correct derivation (Li 2002, energy balance on debond front):
          δ_d = G_d_Nmm × E_f_mpa × A_f / (π × d_f × τ₀²)  [mm]  ✓
  [BUG-3] @numba.jit decorator was executed inside the per-δ loop, triggering
          300 decorator evaluations per simulation run. JIT kernel is now
          compiled once at module import time.
  [NOTE]  dblquad argument order (outer=theta, inner=l) matches integrand
          signature integrand(l, theta) — this is correct per SciPy convention
          f(inner, outer). Clarifying comment added.
"""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

import math
import numpy as np
import pandas as pd
from scipy.integrate import dblquad, IntegrationWarning

# ---------------------------------------------------------------------------
# Numba JIT — compiled ONCE at module level, graceful degradation when absent
# ---------------------------------------------------------------------------

try:
    import numba  # type: ignore

    _NUMBA_AVAILABLE = True

    # FIX-3: compile the PE kernel exactly once here, not inside the per-δ loop.
    # nopython=True  — no Python object overhead in the hot path
    # cache=True     — persist compiled artifact to disk across sessions
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
        "which may be 10–50× slower. Install numba for production use.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Fiber type enumeration
# ---------------------------------------------------------------------------


class FiberType(Enum):
    PE = auto()     # Polyethylene — smooth, no chemical bond, slip-hardening
    PVA = auto()    # Polyvinyl alcohol — strong chemical bond, prone to rupture
    STEEL = auto()  # Steel hooked-end — no slip-hardening, mechanical anchorage


# ---------------------------------------------------------------------------
# Simulation parameter containers
# ---------------------------------------------------------------------------


@dataclass
class CommonFiberParams:
    """Parameters shared by all fiber types and the integration framework."""

    V_f: float             # fiber volume fraction (–), e.g. 0.02
    L_f: float             # fiber length (mm)
    d_f: float             # fiber diameter (mm) — reused from pullout test
    E_f: float             # fiber elastic modulus (GPa)
    sigma_fu: float        # fiber tensile strength (MPa)
    tau_0: float           # interface frictional bond stress (MPa) — from pullout
    f_snubbing: float      # snubbing (friction-pulley) coefficient (–)
    n_delta_points: int = 300   # discretisation resolution for δ axis


@dataclass
class PEFiberParams:
    """Additional parameters specific to PE/PP fibers."""

    beta: float = 0.15    # slip-hardening coefficient (–)


@dataclass
class PVAFiberParams:
    """Additional parameters specific to PVA fibers."""

    G_d: float = 3.0      # chemical bond energy (J/m²)
    beta: float = 0.50    # slip-hardening coefficient — stronger for PVA


@dataclass
class SteelFiberParams:
    """Additional parameters specific to hooked-end steel fibers."""

    # Mechanical anchorage adds a supplemental force component at δ = 0 that
    # decays linearly as the hook is straightened over δ_hook mm.
    P_anchor_max: float = 0.0   # N — peak anchorage force per fiber
    delta_hook: float = 0.5     # mm — slip distance to fully straighten hook


# ---------------------------------------------------------------------------
# Abstract fiber pullout model (Strategy interface)
# ---------------------------------------------------------------------------


class FiberPulloutModel(ABC):
    """
    Defines the contract for single-fiber pullout force P(δ, l, θ).

    Subclasses implement the physical pull-out mechanics for a specific
    fiber type. The double-integral engine calls only get_pullout_force()
    and is completely decoupled from fiber-specific physics.
    """

    def __init__(self, common: CommonFiberParams) -> None:
        self._c = common
        self._A_f: float = math.pi * common.d_f ** 2 / 4.0   # mm²
        self._rupture_force: float = common.sigma_fu * self._A_f  # N

    @abstractmethod
    def _straight_pullout(self, delta: float, l: float) -> float:
        """
        Compute pullout force for a fiber perfectly perpendicular to the crack.
        Returns force in Newtons. Must return 0 when fiber is fully extracted.
        """
        ...

    def get_pullout_force(self, delta: float, l: float, theta: float) -> float:
        """
        Apply snubbing amplification and rupture cutoff on top of straight
        pullout force. This method is the same for all fiber types.

        Snubbing factor e^(f·θ) models the friction-pulley effect at the
        fiber exit point in the matrix (Lim, Nawy & Li 1987).
        """
        p_straight = self._straight_pullout(delta, l)
        p_snubbed = p_straight * math.exp(self._c.f_snubbing * theta)

        # Fiber rupture boundary — load exceeding tensile capacity → zero bridging
        if p_snubbed > self._rupture_force:
            return 0.0
        return p_snubbed


# ---------------------------------------------------------------------------
# PE / PP fiber model
# ---------------------------------------------------------------------------


class PEFiberModel(FiberPulloutModel):
    """
    PE/PP fiber pullout model.

    Physical rationale: PE surface is hydrophobic and chemically inert with
    cement hydrates → G_d ≈ 0 → no debonding stage. Load is carried purely by
    interfacial friction τ₀ from the first instant of crack opening.
    Slip-hardening (β > 0) reflects the progressive tightening of the
    mechanical interlock as the fiber slides deeper.
    """

    def __init__(self, common: CommonFiberParams, pe_params: PEFiberParams) -> None:
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
    PVA fiber pullout model.

    Physical rationale: PVA surface forms strong hydrogen bonds with C-S-H
    during cement hydration → large G_d. A debonding front must propagate
    before frictional sliding begins, producing a non-linear rising branch.
    The high G_d also means fibers often rupture before full extraction.

    Implementation follows Li et al. (2002) simplified bilinear model:
      Stage 1 (δ < δ_d): quadratic ramp up to peak debonding force
      Stage 2 (δ ≥ δ_d): friction + slip-hardening, analogous to PE model

    δ_d derivation (energy balance on debond front, Li 2002):
      Work done by pullout force = fracture energy released at debond tip
      → δ_d = G_d [N/mm] × E_f [N/mm²] × A_f [mm²] / (π × d_f [mm] × τ₀² [N/mm²]²)

      Unit check:
        (N/mm)(N/mm²)(mm²) / ((mm)(N/mm²)²)
        = N²/mm / (N²/mm³)
        = mm²  → sqrt → mm  ✓

    NOTE: δ_d clamped to minimum 1e-9 mm to guard against division-by-zero
    when G_d is near zero.
    """

    def __init__(self, common: CommonFiberParams, pva_params: PVAFiberParams) -> None:
        super().__init__(common)
        self._G_d = pva_params.G_d
        self._beta = pva_params.beta

        # Unit conversions
        G_d_Nmm = pva_params.G_d * 1e-3          # J/m²  → N/mm  (1 J/m² = 1e-3 N/mm)
        E_f_Nmm2 = common.E_f * 1_000.0           # GPa   → N/mm² (= MPa)
        tau0_Nmm2 = common.tau_0                   # MPa   = N/mm²  (no conversion needed)

        # FIX-2: corrected formula — all units resolve to mm² before sqrt
        # δ_d = G_d [N/mm] * E_f [N/mm²] * A_f [mm²] / (π * d_f [mm] * τ₀² [N/mm²]²)
        numerator = G_d_Nmm * E_f_Nmm2 * self._A_f
        denominator = math.pi * common.d_f * tau0_Nmm2 ** 2
        arg = numerator / max(denominator, 1e-30)
        self._delta_d: float = max(math.sqrt(arg), 1e-9)  # mm

    def _straight_pullout(self, delta: float, l: float) -> float:
        remaining_embed = l - delta
        if remaining_embed <= 0.0:
            return 0.0

        if delta < self._delta_d:
            # Quadratic ramp: P rises from 0 to P_peak_debond as crack opens
            fraction = delta / self._delta_d
            p_peak_debond = math.pi * self._c.d_f * self._c.tau_0 * remaining_embed
            return p_peak_debond * fraction ** 2
        else:
            # Frictional sliding with slip-hardening — same form as PE
            hardening = 1.0 + self._beta * delta / self._c.d_f
            return math.pi * self._c.d_f * self._c.tau_0 * remaining_embed * hardening


# ---------------------------------------------------------------------------
# Steel (hooked-end) fiber model
# ---------------------------------------------------------------------------


class SteelFiberModel(FiberPulloutModel):
    """
    Hooked-end steel fiber pullout model.

    Physical rationale: steel surface has moderate chemical bond but relies
    heavily on mechanical anchorage from the bent hook end.
    β = 0 (no slip-hardening in metallic interface).
    Hook straightening contributes a supplemental anchorage force that linearly
    decays to zero over δ_hook mm as the hook is pulled straight.

    NOTE: P_anchor_max defaults to 0 so the model degrades to plain-friction
    steel fiber if anchorage data is unavailable.
    """

    def __init__(
        self, common: CommonFiberParams, steel_params: SteelFiberParams
    ) -> None:
        super().__init__(common)
        self._P_anchor_max = steel_params.P_anchor_max  # N
        self._delta_hook = steel_params.delta_hook       # mm

    def _straight_pullout(self, delta: float, l: float) -> float:
        remaining_embed = l - delta
        if remaining_embed <= 0.0:
            return 0.0

        p_friction = math.pi * self._c.d_f * self._c.tau_0 * remaining_embed

        # Linear decay of hook anchorage over straightening slip distance
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
    Return a two-argument function integrand(l, theta) for scipy.dblquad.

    SciPy dblquad convention:
        dblquad(f, a, b, gfun, hfun)
        calls f(inner_var, outer_var)
        outer variable = theta ∈ [a, b] = [0, π/2]
        inner variable = l    ∈ [gfun, hfun] = [0, L_f/2]
        → f must be f(l, theta)  ✓

    FIX-1: Numba acceleration is ONLY applied for PEFiberModel.
    PVA and Steel use the pure-Python fallback path to preserve their
    model-specific physics (debonding ramp, hook anchorage).
    FIX-3: _jit_pe_straight is compiled once at module import, not here.
    """
    # FIX-1: gate Numba on fiber type, not just availability
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
        # Pure-Python path: used for PVA, Steel, and when Numba is absent.
        # Correctly delegates to each model's own _straight_pullout logic.
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
    Compute the macroscopic bridging stress σ(δ) curve via double integration.

    σ(δ) = (8 V_f) / (π d_f² L_f) ∫₀^(π/2) ∫₀^(L_f/2) P(δ,l,θ)·sin(θ) dl dθ

    Parameters
    ----------
    common : CommonFiberParams
        Shared fiber geometry and interface parameters.
    pullout_model : FiberPulloutModel
        Fiber-type-specific P(δ, l, θ) strategy.
    progress_callback : optional callable(current_idx, total)
        Called after each δ point; drives the UI progress bar in the worker.

    Returns
    -------
    pd.DataFrame with columns ["delta" (mm), "sigma" (MPa)].
    Column names match the CSV import format exactly for pipeline compatibility.

    Notes
    -----
    δ range starts at L_f / n_delta_points (not exactly 0) to avoid
    potential singularities in PVA debonding formula when δ → 0.
    For PE fibers σ(0⁺) is physically non-zero (friction starts immediately
    at first crack opening), so the curve not passing through the origin is
    correct physical behaviour, not a bug.
    """
    # δ range: (0, L_f/2].
    # Start slightly above 0 to avoid PVA singularity at δ=0.
    delta_arr = np.linspace(
        common.L_f / common.n_delta_points,
        common.L_f / 2.0,
        common.n_delta_points,
    )

    # Pre-factor outside the integral
    # Unit: V_f [–] / (d_f² [mm²] × L_f [mm]) → mm⁻³
    # × integral result [N·mm²] → N/mm² = MPa  ✓
    prefactor = (8.0 * common.V_f) / (math.pi * common.d_f ** 2 * common.L_f)

    sigma_values: list[float] = []
    total = len(delta_arr)

    for idx, delta in enumerate(delta_arr):
        # FIX-3: _make_integrand no longer compiles Numba kernel inside loop
        integrand = _make_integrand(delta, pullout_model)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", IntegrationWarning)

            # dblquad(f, a, b, gfun, hfun):
            #   outer integral: theta ∈ [0, π/2]
            #   inner integral: l    ∈ [0, L_f/2]
            #   f is called as f(l, theta)  ← inner var first
            result, _abserr = dblquad(
                integrand,
                0.0,                # theta lower (outer)
                math.pi / 2.0,      # theta upper (outer)
                0.0,                # l lower (inner)
                common.L_f / 2.0,   # l upper (inner)
                epsabs=1e-4,
                epsrel=1e-4,
            )

            if caught:
                # IntegrationWarning typically means the integrand has a sharp
                # feature (e.g. rupture boundary). Result is still usable.
                warnings.warn(
                    f"Integration warning at δ={delta:.4f} mm: {caught[0].message}",
                    stacklevel=2,
                )

        sigma_values.append(prefactor * result)

        if progress_callback is not None:
            progress_callback(idx + 1, total)

    return pd.DataFrame({"delta": delta_arr, "sigma": np.array(sigma_values)})


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
    """
    Instantiate the correct FiberPulloutModel subclass based on fiber_type.
    Raises ValueError if the corresponding params dataclass is missing.
    """
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

    # Unreachable at runtime — guards against future FiberType additions
    raise ValueError(f"Unsupported fiber type: {fiber_type!r}")
