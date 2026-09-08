# Literature benchmark: Yang et al. (2008) M45 PVA-ECC

This benchmark anchors the theoretical bridging simulator to a published ECC micromechanics case instead of validating only against self-generated numbers.

## Reference

Yang, E.-H.; Wang, S.; Yang, Y.; Li, V. C. (2008). *Fiber-Bridging Constitutive Law of Engineered Cementitious Composites*. Journal of Advanced Concrete Technology, 6(1), 181-193. https://doi.org/10.3151/jact.6.181

## Published M45 parameters

For the 2 vol.% PVA case, Yang et al. report:

| Parameter | Value |
|---|---:|
| Fiber diameter `d_f` | 39 um |
| Fiber length `L_f` | 12 mm |
| Fiber modulus `E_f` | 22 GPa |
| Fiber strength `sigma_fu` | 1060 MPa |
| Snubbing coefficient `f` | 0.20 |
| Inclination strength-reduction coefficient `f'` | 0.33 |
| Matrix modulus `E_m` | 20 GPa |
| Fiber volume fraction `V_f` | 2 vol.% |
| Frictional bond `tau_0` | 1.31 MPa |
| Chemical debond energy `G_d` | 1.08 J/m^2 |
| Slip-hardening coefficient `beta` | 0.58 |

The coupon was treated as a **2-D random fiber distribution** because its thickness (13 mm) was close to the 12 mm fiber length.

## Model hierarchy reported in the paper

Yang et al. explicitly compare four levels of PVA bridging physics:

| Model | Peak bridging stress | Crack opening at peak |
|---|---:|---:|
| Previous simplified **one-way pullout** | 6.2 MPa | 93 um |
| Two-way pullout only | 6.3 MPa | 130 um |
| Two-way + matrix spalling | 6.7 MPa | 131 um |
| Full model incl. Cook-Gordon | 6.7 MPa | 133 um |

The present `one-way-yang2008-v3` implementation targets the **first row** as its literature baseline. It should not be presented as reproducing the 6.7 MPa / 133 um full model.

## Current benchmark result

Using the published 2 vol.% M45 inputs and 64-point Gauss-Legendre integration, the present one-way implementation gives a peak of approximately **5.97 MPa at 72 um** in a fine local sweep.

Relative to Yang et al.'s previous one-way result (6.2 MPa at 93 um):

- peak stress error is about **-3.8%**;
- peak crack opening is about **23% lower**.

The stress level is therefore reproduced closely, while crack-opening prediction remains the weaker part of the one-way implementation. This discrepancy must not be hidden: Yang et al. specifically identified two-way pullout as the dominant mechanism that moves the PVA peak opening toward roughly 130 um.

## What was corrected for this benchmark

1. PVA debonding now follows the chemical-bond form of Yang et al. Eq. (12), rather than an artificial ramp forced through zero.
2. The complete-debond displacement follows Eq. (5)/(14).
3. Post-debond sliding follows the one-way pullout form of Eq. (13).
4. Inclination-dependent fiber strength is represented by `sigma_fu(theta) = sigma_fu(0) exp(-f' theta)` from Eq. (7).
5. Fiber orientation supports both:
   - 3-D isotropic randomness: `sin(theta) cos(theta)` after transforming centroid position to embedment length;
   - 2-D planar randomness: `(2/pi) cos(theta)`.
6. `sim_tau0_override` allows a directly calibrated frictional bond stress to be used instead of estimating `tau_0` from a peak pullout load that may already include chemical bond or mechanical anchorage.
7. The double integral uses deterministic 64-point Gauss-Legendre quadrature, which is much faster than evaluating an adaptive double integral for every crack-opening point.
8. The automated M45 benchmark checks that the one-way peak remains within a stated tolerance of the published 6.2 MPa / 93 um baseline.

## Important interpretation

A literature benchmark does **not** make every parameter combination publication-grade automatically. For final PSH claims, experimentally measured or independently calibrated sigma-delta curves remain preferable. In particular, PVA crack-opening prediction will remain biased low until two-way pullout is implemented. Hooked steel also remains a simplified friction-plus-anchorage model and requires independent calibration.
