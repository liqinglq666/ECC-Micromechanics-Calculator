# ECC Micromechanics Calculator & Simulation Engine

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Proprietary-red)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![UI Framework](https://img.shields.io/badge/UI-PySide6-brightgreen)
![Acceleration](https://img.shields.io/badge/Optional-Numba%20JIT-orange)

本项目是一个用于 **工程水泥基复合材料 (ECC)** / **应变硬化水泥基复合材料 (SHCC)** 的微观力学计算与伪应变硬化判据评估工具。

软件实现了基于 ECC micromechanics framework 的工程化计算流程，支持两种 σ–δ 曲线来源：

1. **Imported CSV**：导入实验或外部数值模型得到的桥接应力–裂缝张开曲线，用于正式 PSH 评价。
2. **Theoretical Simulation**：使用简化单纤维拔出与双重积分模型生成理论 σ–δ 曲线，用于参数敏感性分析、教学演示和初步设计筛选。

> 注意：Simulation 模式是 simplified micromechanics model，不等同于完整单纤维拔出全过程本构复现。正式论文或工程结论建议优先采用经实验校准的 σ–δ 曲线。

---

## 🧮 Theoretical Background / 微观力学理论框架

### 1. Interfacial Properties / 界面摩擦应力

基于 single-fiber pullout test 获取平均界面滑动摩擦应力：

$$
\tau_0 = \frac{P_{\text{peak}}}{\pi d_f L_e}
$$

其中：

- $P_{\text{peak}}$：单纤维拔出峰值荷载，N
- $d_f$：纤维直径，mm
- $L_e$：有效埋入长度，mm
- $\tau_0$：界面摩擦应力，MPa

---

### 2. Matrix Fracture Mechanics / 基体断裂参数

单边缺口梁 (SENB) 三点弯曲试验用于估算基体应力强度因子：

$$
K_m = \frac{P_{\max} S}{b d^{1.5}} F\left(\frac{a_0}{d}\right)
$$

代码使用 Gross-Srawley 几何修正函数，并完成单位换算：

$$
\text{MPa}\cdot\sqrt{\text{mm}} \rightarrow \text{MPa}\cdot\sqrt{\text{m}}
$$

裂尖能量释放率支持两种断裂条件：

$$
J_{\text{tip}} = \frac{K_m^2}{E} \quad \text{plane stress}
$$

$$
J_{\text{tip}} = \frac{K_m^2}{E/(1-\nu^2)} \quad \text{plane strain}
$$

默认采用 `plane_stress`，泊松比默认 `ν = 0.20`。当前 GUI 仍采用默认值；导出文件会记录 fracture condition 和 Poisson ratio，便于后续扩展界面输入。

---

### 3. Fiber Bridging Complementary Energy / 纤维桥接互补能

根据 σ–δ 曲线峰值点 $(\delta_0, \sigma_0)$ 计算：

$$
J_b' = \sigma_0 \delta_0 - \int_0^{\delta_0} \sigma(\delta)\,d\delta
$$

实现细节：

- 使用 Simpson 法则进行数值积分；
- 若曲线不是从 `δ = 0` 开始，程序会补入原点，避免漏算初始面积而高估 $J_b'$；
- Simulation 模式生成的曲线现在从 `δ = 0` 开始。

---

### 4. PSH Criteria / 伪应变硬化双准则

ECC/SHCC 需要同时满足强度准则和能量准则：

$$
\text{PSH}_{\text{strength}} = \frac{\sigma_0}{\sigma_{fc}}
$$

$$
\text{PSH}_{\text{energy}} = \frac{J_b'}{J_{\text{tip}}}
$$

工程设计建议阈值：

| Criterion | Recommended threshold | Meaning |
|---|---:|---|
| PSH Strength | ≥ 1.3 | 桥接峰值强度需高于初裂强度，保证新裂缝可激活 |
| PSH Energy | ≥ 2.7 | 桥接互补能需高于裂尖能量需求，保证稳态裂纹扩展 |

---

## 🔒 Data Consistency Fixes / 数据一致性保护

当前版本加入了 σ–δ 曲线来源与参数指纹校验：

- CSV 导入曲线会被标记为 `csv`；
- Simulation 曲线会被标记为 `simulation`；
- Simulation 曲线会记录由 `P_peak, d_f, L_e, V_f, L_f, E_f, sigma_fu, G_d, beta, f_snubbing, n_delta_points, P_anchor_max, delta_hook, fiber_type` 生成的参数 fingerprint；
- 如果用户切换 CSV / Simulation 模式，或修改模拟参数后没有重新生成曲线，程序会拒绝分析并提示重新导入或重新模拟。

这可以避免“界面显示是 Simulation，但实际拿旧 CSV 曲线计算”这类静默错误。

---

## 🚀 Core Features

- **PSH dual-criterion evaluation**：强度准则 + 能量准则同时评估
- **SENB fracture calculation**：Gross-Srawley 几何修正与单位换算
- **σ–δ complementary energy integration**：自动识别峰值并积分到峰值点
- **Simplified theoretical simulation**：PE / PVA / Steel 三类纤维的简化桥接模型
- **Data provenance guard**：曲线来源与模拟参数 fingerprint 校验
- **Publication-ready visualization**：支持高分辨率图片导出
- **Traceable Excel export**：导出 Summary、曲线数据和输入参数日志

---

## 📋 Requirements

基础安装：

- Python 3.10+
- PySide6
- NumPy
- SciPy
- Pandas
- Matplotlib
- OpenPyXL

可选加速：

- Numba

---

## ⚙️ Installation

```bash
pip install -e .
```

如需启用 Numba JIT 加速：

```bash
pip install -e ".[accel]"
```

开发环境：

```bash
pip install -e ".[dev]"
pytest
```

---

## 📖 Usage

### Basic Workflow

1. **Add Series**：添加一个或多个配合比/变量序列；
2. **Input Material Parameters**：输入单纤维拔出、SENB、基体模量和初裂强度参数；
3. **Choose σ–δ Source**：导入 CSV 或运行理论模拟；
4. **Run Analysis**：计算 $\tau_0, K_m, J_{tip}, J_b', PSH$；
5. **Analyze Results**：查看单组曲线、对比图和表格；
6. **Export Data**：导出 CSV / Excel / 图片。

CSV 文件必须包含两列：

```csv
delta,sigma
0.0,0.0
0.1,2.3
0.2,4.1
```

单位：

- `delta`：mm
- `sigma`：MPa

---

## ✅ Recent Reliability Improvements

- 修复 CSV / Simulation 模式切换后可能复用旧曲线的问题；
- 修复模拟参数改变后旧 σ–δ 曲线仍可能被用于分析的问题；
- 修复 Simulation 曲线不从 `δ = 0` 开始导致 $J_b'$ 偏大的问题；
- 增加 `plane_stress / plane_strain` 的 $J_{tip}$ 计算接口；
- 增加关键输入正值校验；
- 修复 `README` 与 `pyproject.toml` 许可证信息不一致；
- 将 `numba` 改为 optional acceleration dependency，提升基础安装兼容性；
- 增加 package marker，保证 setuptools 能正确发现 `core / models / ui / utils` 包。

---

## ✉️ Contact

For technical inquiries or collaboration, please contact:

- **GitHub**: [@liqinglq666](https://github.com/liqinglq666)
- **Email**: liqinglq666@gmail.com
