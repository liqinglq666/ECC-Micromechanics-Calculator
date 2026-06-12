# ECC Micromechanics Calculator & Simulation Engine

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Proprietary%20(All%20Rights%20Reserved)-red)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![UI Framework](https://img.shields.io/badge/UI-PySide6-brightgreen)
![Performance](https://img.shields.io/badge/Acceleration-Numba%20JIT-orange)

本项目是一个工程级桌面应用程序 (Engineering-grade desktop application)，专为 **工程水泥基复合材料 (ECC)** / **应变硬化水泥基复合材料 (SHCC)** 的微观力学设计 (Micro-mechanical design) 与理论模拟 (Theoretical simulation) 而开发。

This tool bridges the gap between microscopic fiber-matrix interactions and macroscopic tensile ductility. 它为评估复杂服役环境下的 Pseudo Strain-Hardening (PSH) 准则提供了一套高度自动化、防死锁的 Robust analytical framework。

本引擎底层采用**策略模式 (Strategy Pattern)** 架构，深度集成并支持 **PE/PP、PVA 以及钢纤维 (Hooked-end Steel Fibers)** 三种截然不同的物理本构模型。

---

## ✨ Core Features (核心特性)

* **Multi-Fiber Modeling (多纤维物理本构)**: 内置 PE/PP (疏水摩擦)、PVA (亲水化学键) 与钢纤维 (机械锚固) 的定制化物理模型。精确捕获 Elastic Debonding, Slip-hardening, 和 Hook straightening 效应。
* **Numba JIT Acceleration (实时编译加速)**: 针对计算极其密集的 PE 纤维双重数值积分，底层自动应用 `@numba.jit(nopython=True)` 预编译核函数，将运算速度提升 10~50 倍。
* **Asynchronous Engine (纯异步计算流)**: 无论是大规模的 CSV 矩阵清洗、解析积分计算，还是多 Sheet Excel I/O 写入，所有阻塞型任务均由独立的 `QThread` (Worker 类) 接管，实现真正的 Zero UI-blocking。
* **Publication-Ready Visualization (顶刊级可视化)**: 深度集成 `Matplotlib`，采用 Google Research 极简美学规范，自动处理数据平滑与高对比度着色，一键渲染多组 $\sigma-\delta$ 重叠对比图。
* **Traceable Data Export (科研数据溯源)**: 内置 Pandas `ExcelWriter` 引擎，一键导出包含 `Summary_Results` (结果汇总)、`Sigma_Delta_Curves` (宽表矩阵曲线) 和 `Project_Settings_Log` (原始输入快照) 的多标签页工程表。

---

## 🧮 Theoretical Background (微观力学理论模型)

本软件的计算引擎严格基于 **Victor C. Li** 教授提出的 ECC 微观力学与稳态裂纹扩展理论 (Steady-state flat crack propagation)。核心物理量的计算流水线 (Calculation Pipeline) 如下：

### 1. Interfacial Properties (界面特性解析)
基于 Single-fiber pullout test 获取库仑摩擦模型下的平均界面滑动摩擦应力 (Interfacial Frictional Stress)：
$$\tau_0 = \frac{P_{peak}}{\pi \cdot d_f \cdot L_e} \quad [\text{MPa}]$$

### 2. Matrix Fracture Mechanics (基体断裂力学)
利用单边缺口梁 (SENB) 三点弯曲试验计算基体的应力强度因子 (Stress Intensity Factor) 与裂尖能量释放率 (Crack Tip Toughness)：
$$K_m = \frac{P_{max} \cdot S}{b \cdot d^{1.5}} \cdot F\left(\frac{a_0}{d}\right) \quad [\text{MPa}\cdot\text{m}^{0.5}]$$
$$J_{tip} = \frac{K_m^2}{E_m} \quad [\text{J/m}^2]$$
*注：几何修正函数 $F(a_0/d)$ 基于 Gross-Srawley 方程进行无量纲化处理。*

### 3. Fiber Bridging Energy (纤维桥接互补能)
Complementary Energy ($J'_b$) 是决定多缝开裂 (Multiple Cracking) 的终极动力储备。通过对 $\sigma-\delta$ 曲线的峰值左侧区间应用 Simpson 法则进行数值积分获取：
$$J'_b = \sigma_0 \delta_0 - \int_{0}^{\delta_0} \sigma(\delta) d\delta \quad [\text{J/m}^2]$$

### 4. PSH Criteria (伪应变硬化双准则)
要实现稳态的应变硬化行为，材料必须同时满足强度 (Strength) 与能量 (Energy) 双重边界条件：
* **Strength Criterion (激活新裂缝)**: $\quad PSH_{strength} = \frac{\sigma_0}{\sigma_{fc}} \ge 1.3$
* **Energy Criterion (维持稳态扩展)**: $\quad PSH_{energy} = \frac{J'_b}{J_{tip}} \ge 2.7$

### 5. Theoretical Curve Simulation (纯理论 $\sigma-\delta$ 曲线预测)
对于特定的疏水性高分子纤维 (如 PE / PP fibers)，本软件内置了基于三维概率密度函数 (3D PDF) 的数值积分引擎。宏观桥接应力 $\sigma(\delta)$ 由单根纤维的非线性拔出力 $P(\delta, L_e, \theta)$ 经过 Double-integral 叠加而成：
$$\sigma(\delta) = \frac{8 V_f}{\pi d_f^2 L_f} \int_{0}^{L_f/2} \int_{0}^{\pi/2} P(\delta, L_e, \theta) \sin(\theta) \,d\theta \,dL_e$$
引入 Slip-hardening effect (滑移硬化系数 $\beta$) 与 Snubbing effect (摩擦放大系数 $f$) 后的单纤维本构方程：
$$P(\delta, L_e, \theta) = \pi d_f \tau_0 (L_e - \delta) \left(1 + \beta \frac{\delta}{d_f}\right) e^{f \theta}$$
*(引擎内部包含了严苛的 Fiber Rupture 截断校验：$P \le \frac{\pi d_f^2}{4}\sigma_{fu}$)*

### 6. Multi-Fiber Constitutive Extensions (多纤维本构拓展)
在 PE/PP 纤维的基础上，本引擎通过策略模式额外支持：
* **PVA Fibers (亲水性聚乙烯醇纤维)**: 引入强化学胶结能 ($G_d$)，纤维在滑动前必须先经历弹性剥离阶段。其特征剥离位移界限为：
  $$\delta_d = \sqrt{\frac{G_d E_f A_f}{\pi d_f \tau_0^2}}$$
* **Hooked-End Steel Fibers (端钩型钢纤维)**: 无滑移硬化 ($\beta=0$)，但在裂缝张开初期提供额外的端钩机械锚固力 ($P_{anchor}$)，呈线性衰减：
  $$P_{hook}(\delta) = P_{h0} \left(1 - \frac{\delta}{\delta_{hook}}\right) \quad (\text{if } \delta < \delta_{hook})$$

---

*liqinglq666 · 学术交流用途*
