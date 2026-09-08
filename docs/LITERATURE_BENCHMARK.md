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

## What was corrected for this benchmark

1. PVA debonding now follows the chemical-bond form of Yang et al. Eq. (12), rather than an artificial ramp forced through zero.
2. The complete-debond displacement follows Eq. (5)/(14).
3. Post-debond sliding follows the one-way pullout form of Eq. (13).
4. Inclination-dependent fiber strength is represented by `sigma_fu(theta) = sigma_fu(0) exp(-f' theta)` from Eq. (7).
5. Fiber orientation supports both:
   - 3-D isotropic randomness: `sin(theta) cos(theta)` after transforming centroid position to embedment length;
   - 2-D planar randomness: `(2/pi) cos(theta)`.
6. The 2 vol.% M45 benchmark test verifies that the predicted one-way peak remains close to the published 6.2 MPa / 93 um baseline.

## Important interpretation

A literature benchmark does **not** make every parameter combination publication-grade automatically. For final PSH claims, experimentally measured or independently calibrated sigma-delta curves remain preferable. In particular, PVA crack-opening prediction will remain biased low until two-way pullout is implemented, which is exactly the mechanism Yang et al. identified as the main correction from about 93 um toward about 130 um.
