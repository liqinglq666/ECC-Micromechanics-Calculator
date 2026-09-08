# Micromechanics model notes

This note documents the physics implemented by the theoretical bridging simulator.

## PE / PP path

The PE path is intended for smooth hydrophobic fibres where chemical bond energy is negligible. It uses two stages:

1. **Interfacial debonding**: pullout force grows from zero with crack opening according to a Lin/Gao-type energy-balance relation.
2. **Frictional sliding**: after full debonding,

\[
P=\pi d_f\tau_0\left[1+\beta\frac{\delta-\delta_0}{d_f}\right]
\left[L_e-(\delta-\delta_0)\right].
\]

The matrix/fibre stiffness ratio

\[
\eta=\frac{V_f E_f}{(1-V_f)E_m}
\]

is included in the complete-debond displacement when `E_m` is supplied.

For PE, `beta` defaults to **0.0**. Do not assume slip hardening unless it is supported by single-fibre pullout data.

## Random 3-D fibres

For isotropic 3-D orientation, the bridge contribution is weighted by

\[
\sin\theta\cos\theta,
\]

where `sin(theta)` is the orientation density and `cos(theta)` accounts for the probability that an inclined fibre intersects the crack plane. The previous implementation omitted the crossing-probability term and could overestimate bridging stress.

## Fibre rupture

Rupture is path dependent. The simulator now checks the maximum force attained from zero opening to the current opening. Once this historical maximum exceeds the fibre tensile capacity, the fibre contribution is permanently zero at all larger openings. A fibre therefore cannot numerically "rupture" and then reappear after the instantaneous pullout force falls.

## PVA and hooked steel

These branches remain simplified mechanistic models. In particular, PVA should ideally use separately measured post-debond friction load `P_b`, chemical debond energy `G_d`, and slip-hardening slope; hooked steel should separate frictional bond from mechanical anchorage. Do not interpret the PVA/steel simulation as a full Yang-Li two-way debonding/micro-spalling/Cook-Gordon model.

For publication-grade quantitative PSH analysis, importing an experimentally measured or independently calibrated sigma-delta curve remains the preferred route.

## Matrix fracture geometry

The implemented Gross-Srawley / ASTM-style SENB geometry function is tied to approximately `S/d = 4`. The engine now rejects incompatible span/depth ratios instead of silently applying the formula to a different geometry.

## References used for the correction

- Kanda, T.; Li, V. C. (2006). *Practical Design Criteria for Saturated Pseudo Strain Hardening Behavior in ECC*. Journal of Advanced Concrete Technology, 4(1), 59-72.
- Yang, E.-H.; Wang, S.; Yang, Y.; Li, V. C. (2008). *Fiber-Bridging Constitutive Law of Engineered Cementitious Composites*. Journal of Advanced Concrete Technology, 6(1), 181-193.
- Lin-type single-fibre debonding/pullout relations as summarized in subsequent fibre/matrix interface literature.
