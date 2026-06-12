# ECC Micromechanics Calculator & Simulation Engine

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Proprietary-red)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![UI Framework](https://img.shields.io/badge/UI-PySide6-brightgreen)
![Performance](https://img.shields.io/badge/Acceleration-Numba%20JIT-orange)

本项目是一个工程级桌面应用程序 (Engineering-grade desktop application)，专为 **工程水泥基复合材料 (ECC)** / **应变硬化水泥基复合材料 (SHCC)** 的微观力学设计 (Micro-mechanical design) 与理论模拟 (Theoretical simulation) 而开发。

---

## 🧮 Theoretical Background (微观力学理论模型)

本软件的计算引擎严格基于 **Victor C. Li** 教授提出的 ECC 微观力学与稳态裂纹扩展理论。

### 1. Interfacial Properties (界面特性解析)
基于 Single-fiber pullout test 获取库仑摩擦模型下的平均界面滑动摩擦应力 ($\tau_0$)：

$$\tau_0 = \frac{P_{peak}}{\pi \cdot d_f \cdot L_e} \quad [\text{MPa}]$$

### 2. Matrix Fracture Mechanics (基体断裂力学)
利用单边缺口梁 (SENB) 三点弯曲试验计算基体的应力强度因子 ($K_m$) 与裂尖能量释放率 ($J_{tip}$)：

$$K_m = \frac{P_{max} \cdot S}{b \cdot d^{1.5}} \cdot F\left(\frac{a_0}{d}\right) \quad [\text{MPa}\cdot\text{m}^{0.5}]$$

$$J_{tip} = \frac{K_m^2}{E_m} \quad [\text{J/m}^2]$$

*注：几何修正函数 $F(a_0/d)$ 基于 Gross-Srawley 方程进行无量纲化处理。*

### 3. Fiber Bridging Energy (纤维桥接互补能)
Complementary Energy ($J'_b$) 是决定多缝开裂 (Multiple Cracking) 的终极动力储备。通过对 $\sigma-\delta$ 曲线的峰值左侧区间应用 Simpson 法则进行数值积分获取：

$$J'_b = \sigma_0 \delta_0 - \int_{0}^{\delta_0} \sigma(\delta) \,d\delta \quad [\text{J/m}^2]$$

### 4. PSH Criteria (伪应变硬化双准则)
要实现稳态的应变硬化行为，材料必须同时满足强度 (Strength) 与能量 (Energy) 双重边界条件：

* **Strength Criterion (激活新裂缝)**: 
  $$PSH_{strength} = \frac{\sigma_0}{\sigma_{fc}} \ge 1.3$$

* **Energy Criterion (维持稳态扩展)**: 
  $$PSH_{energy} = \frac{J'_b}{J_{tip}} \ge 2.7$$

### 5. Theoretical Curve Simulation (纯理论 $\sigma-\delta$ 曲线预测)
宏观桥接应力 $\sigma(\delta)$ 由单根纤维的非线性拔出力 $P(\delta, L_e, \theta)$ 经过 Double-integral 叠加而成：

$$\sigma(\delta) = \frac{8 V_f}{\pi d_f^2 L_f} \int_{0}^{L_f/2} \int_{0}^{\pi/2} P(\delta, L_e, \theta) \sin(\theta) \,d\theta \,dL_e$$

单纤维本构方程 (包含滑移硬化与摩擦放大系数)：

$$P(\delta, L_e, \theta) = \pi d_f \tau_0 (L_e - \delta) \left(1 + \beta \frac{\delta}{d_f}\right) e^{f \theta}$$

*(引擎内部包含了严苛的 Fiber Rupture 截断校验：$P \le \frac{\pi d_f^2}{4}\sigma_{fu}$)*

### 6. Multi-Fiber Constitutive Extensions
* **PVA Fibers (化学键模型)**: 引入化学剥离位移界限 $\delta_d$：
  $$\delta_d = \sqrt{\frac{G_d E_f A_f}{\pi d_f \tau_0^2}}$$
* **Steel Fibers (端钩锚固模型)**: 
  $$P_{hook}(\delta) = P_{h0} \left(1 - \frac{\delta}{\delta_{hook}}\right) \quad (\text{if } \delta < \delta_{hook})$$

---

## 🚀 Core Features
* **Numba JIT Acceleration**: 核心积分运算实时编译，速度提升 10-50 倍。
* **Asynchronous Engine**: 纯异步计算流，确保 UI 零阻塞。
* **Publication-Ready Visualization**: 生成顶刊级的高对比度矢量图。
* **Traceable Data Export**: 支持多标签页的科研数据溯源导出。