# Micromechanics roadmap

## Current validated baseline

- PE/PP: one-way debonding -> frictional sliding, 2-D/3-D orientation, snubbing, inclination-dependent rupture, irreversible rupture.
- PVA: Yang/Lin one-way chemical-debond + slip-hardening baseline with the same orientation/rupture treatment.
- Matrix: SENB K_m with S/d ~= 4 geometry guard; J_tip and PSH post-processing retained.
- Numerical integration: deterministic 64-point Gauss-Legendre quadrature.
- Literature regression: Yang et al. (2008) M45 PVA-ECC one-way benchmark.

## Next physics milestone

### PVA two-way pullout

Implement Yang et al. (2008) Eq. (8)-(16):

1. Track short and long embedment lengths on both sides of the crack.
2. Split total crack opening into `delta_S + delta_L`.
3. Enforce load equilibrium during short-side pullout / long-side debonding.
4. Enforce load equilibrium after both sides enter pullout.
5. Preserve irreversible angle-dependent rupture.

Expected benchmark progression for M45 2 vol.% PVA:

- current/previous one-way baseline: about 6.2 MPa at 93 um in Yang et al.;
- two-way-only target: about 6.3 MPa at 130 um.

### Matrix micro-spalling

After two-way pullout is stable, implement Yang et al. Eq. (17)-(20) using matrix tensile strength and calibrated spalling coefficient `k`. Literature target: approximately 6.7 MPa at 131 um for M45.

### Cook-Gordon effect

Add premature interface debond length `alpha` as the final PVA refinement. Literature full-model target: approximately 6.7 MPa at 133 um.

## Publication-use rule

Until these later PVA mechanisms are implemented and independently benchmarked, imported experimental/calibrated sigma-delta curves remain the preferred basis for final quantitative PSH claims. The theoretical simulator is appropriate for mechanistic sensitivity analysis and for PE systems where the one-way assumption is much better justified.
