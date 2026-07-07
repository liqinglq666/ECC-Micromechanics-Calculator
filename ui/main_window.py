"""ui/main_window.py"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QStatusBar, QTabWidget, QTableView, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from core.engine import AnalysisResult, SeriesParams
from models.project import ProjectModel, SeriesEntry
from ui.plot_widgets import (
    InterfaceComparisonCanvas, MatrixComparisonCanvas,
    OverlayCanvas, SingleSeriesCanvas,
)
from ui.result_table_model import ResultTableModel
from ui.workers import BatchAnalysisWorker, CsvLoaderWorker, SimulationWorker
from utils.io import export_to_csv, results_to_dataframe
from utils.export import DataExportWorker  # 启用高级导出引擎

_PSH_STRENGTH_THRESHOLD = AnalysisResult.PSH_STRENGTH_THRESHOLD
_PSH_ENERGY_THRESHOLD = AnalysisResult.PSH_ENERGY_THRESHOLD

_PASS_CSS = "color: #155724; font-weight: bold;"
_FAIL_CSS = "color: #721c24; font-weight: bold;"
_NEUTRAL_CSS = "color: #333333;"

_CSV_PAGE = 0
_SIM_PAGE = 1


def _make_dsb(
        minimum: float = 0.0,
        maximum: float = 1_000_000.0,
        decimals: int = 4,
        suffix: str = "",
        step: float = 0.01,
) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    if suffix:
        sb.setSuffix(f"  {suffix}")
    return sb


def _result_label(key: str) -> str:
    _MAP = {
        "tau0": "\u03c4\u2080",
        "km": "K\u2098",
        "j_tip": "J_tip",
        "sigma0": "\u03c3\u2080",
        "delta0": "\u03b4\u2080",
        "jb_prime": "J_b\u2032",
        "psh_strength": "PSH_strength",
        "psh_energy": "PSH_energy",
    }
    return _MAP.get(key, key)


class MainWindow(QMainWindow):
    """Top-level window. Owns the ProjectModel and all worker threads."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ECC Micromechanics Calculator")
        self.resize(1500, 860)

        self._model = ProjectModel()
        self._csv_workers: list[CsvLoaderWorker] = []
        self._sim_workers: list[SimulationWorker] = []
        self._batch_worker: Optional[BatchAnalysisWorker] = None
        self._export_worker: Optional[DataExportWorker] = None  # 添加导出 Worker 引用
        self._current_index: int = -1

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(self._build_left_panel())
        left_scroll.setMinimumWidth(360)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._main_progress = QProgressBar()
        self._main_progress.setVisible(False)
        self._main_progress.setMaximumWidth(200)
        self._status_bar.addPermanentWidget(self._main_progress)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        global_box = QGroupBox("Project Settings")
        gform = QFormLayout(global_box)
        self._var_name_edit = QLineEdit("Variable")
        gform.addRow("Variable Name:", self._var_name_edit)
        layout.addWidget(global_box)

        tree_box = QGroupBox("Series")
        tl = QVBoxLayout(tree_box)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tl.addWidget(self._tree)
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("+ Add Series")
        self._btn_remove = QPushButton("- Remove")
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        tl.addLayout(btn_row)
        layout.addWidget(tree_box)

        self._param_box = QGroupBox("Series Parameters")
        self._param_box.setEnabled(False)
        pf = QFormLayout(self._param_box)

        self._sb_name = QLineEdit()
        self._sb_varval = _make_dsb(suffix="")

        pullout_box = QGroupBox("\u2460 Pullout Test")
        po_form = QFormLayout(pullout_box)
        self._sb_p_peak = _make_dsb(suffix="N")
        self._sb_d_f = _make_dsb(0.0, 10.0, 4, "mm", 0.001)
        self._sb_l_e = _make_dsb(suffix="mm")
        po_form.addRow("P_peak (N):", self._sb_p_peak)
        po_form.addRow("d_f (mm):", self._sb_d_f)
        po_form.addRow("L_e (mm):", self._sb_l_e)

        matrix_box = QGroupBox("\u2461 Matrix 3-Point Bending")
        mb_form = QFormLayout(matrix_box)
        self._sb_p_max = _make_dsb(suffix="N")
        self._sb_span = _make_dsb(suffix="mm")
        self._sb_b = _make_dsb(suffix="mm")
        self._sb_d = _make_dsb(suffix="mm")
        self._sb_a0 = _make_dsb(suffix="mm")
        mb_form.addRow("P_max (N):", self._sb_p_max)
        mb_form.addRow("Span S (mm):", self._sb_span)
        mb_form.addRow("Width b (mm):", self._sb_b)
        mb_form.addRow("Depth d (mm):", self._sb_d)
        mb_form.addRow("Notch a0 (mm):", self._sb_a0)

        tensile_box = QGroupBox("\u2462 Tensile / Matrix Properties")
        tb_form = QFormLayout(tensile_box)
        self._sb_e_m = _make_dsb(suffix="GPa")
        self._sb_sigma_fc = _make_dsb(suffix="MPa")
        tb_form.addRow("E_m (GPa):", self._sb_e_m)
        tb_form.addRow("\u03c3_fc (MPa):", self._sb_sigma_fc)

        sd_box = self._build_sigma_delta_box()

        pf.addRow("Series Name:", self._sb_name)
        pf.addRow("Variable Value:", self._sb_varval)
        for sub_box in [pullout_box, matrix_box, tensile_box, sd_box]:
            pf.addRow(sub_box)

        layout.addWidget(self._param_box)

        self._btn_run = QPushButton("\u25b6  Run Analysis")
        self._btn_run.setStyleSheet(
            "background:#27ae60;color:white;font-weight:bold;padding:6px;"
        )
        layout.addWidget(self._btn_run)
        layout.addStretch()
        return panel

    def _build_sigma_delta_box(self) -> QGroupBox:
        sd_box = QGroupBox("\u2463 \u03c3\u2013\u03b4 Bridging Curve")
        outer = QVBoxLayout(sd_box)

        self._radio_csv = QRadioButton("Import from CSV")
        self._radio_sim = QRadioButton("Theoretical Simulation")
        self._radio_csv.setChecked(True)
        self._sd_mode_group = QButtonGroup(sd_box)
        self._sd_mode_group.addButton(self._radio_csv, _CSV_PAGE)
        self._sd_mode_group.addButton(self._radio_sim, _SIM_PAGE)
        radio_row = QHBoxLayout()
        radio_row.addWidget(self._radio_csv)
        radio_row.addWidget(self._radio_sim)
        outer.addLayout(radio_row)

        self._sd_stack = QStackedWidget()

        # Page 0: CSV
        csv_page = QWidget()
        csv_layout = QVBoxLayout(csv_page)
        self._lbl_csv_path = QLabel("No file loaded")
        self._lbl_csv_path.setWordWrap(True)
        self._btn_csv = QPushButton("Import \u03c3\u2013\u03b4 CSV\u2026")
        csv_layout.addWidget(self._lbl_csv_path)
        csv_layout.addWidget(self._btn_csv)

        # Page 1: Simulation
        sim_page = QWidget()
        sim_layout = QVBoxLayout(sim_page)

        note = QLabel(
            "<i>\u03c4\u2080 and d_f are derived from the Pullout Test section above "
            "and are not repeated here.</i>"
        )
        note.setWordWrap(True)
        sim_layout.addWidget(note)

        fiber_row = QFormLayout()
        self._cmb_fiber_type = QComboBox()
        self._cmb_fiber_type.addItem("PE / PP  (smooth, slip-hardening)", "PE")
        self._cmb_fiber_type.addItem("PVA  (bonded, chemical debonding)", "PVA")
        self._cmb_fiber_type.addItem("Steel  (hooked-end, friction)", "STEEL")
        fiber_row.addRow("Fiber type:", self._cmb_fiber_type)
        sim_layout.addLayout(fiber_row)

        shared_form = QFormLayout()
        self._sb_V_f = _make_dsb(0.0, 1.0, 4, "", 0.001)
        self._sb_V_f.setValue(0.02)
        self._sb_L_f = _make_dsb(0.0, 200.0, 3, "mm", 0.1)
        self._sb_L_f.setValue(12.0)
        self._sb_E_f = _make_dsb(0.0, 1000.0, 1, "GPa", 1.0)
        self._sb_E_f.setValue(116.0)
        self._sb_sigma_fu = _make_dsb(0.0, 10000.0, 1, "MPa", 10.0)
        self._sb_sigma_fu.setValue(2600.0)
        self._sb_f_snubbing = _make_dsb(0.0, 5.0, 3, "", 0.01)
        self._sb_f_snubbing.setValue(0.2)
        self._sb_n_points = QSpinBox()
        self._sb_n_points.setRange(50, 2000)
        self._sb_n_points.setValue(300)
        self._sb_n_points.setSingleStep(50)
        shared_form.addRow("V_f (fiber volume fraction):", self._sb_V_f)
        shared_form.addRow("L_f (mm):", self._sb_L_f)
        shared_form.addRow("E_f (GPa):", self._sb_E_f)
        shared_form.addRow("\u03c3_fu (MPa):", self._sb_sigma_fu)
        shared_form.addRow("f_snubbing:", self._sb_f_snubbing)
        shared_form.addRow("Curve resolution (pts):", self._sb_n_points)
        sim_layout.addLayout(shared_form)

        self._fiber_extras_stack = QStackedWidget()

        self._pe_w = QWidget()
        pe_form = QFormLayout(self._pe_w)
        self._sb_beta = _make_dsb(0.0, 5.0, 3, "", 0.01)
        self._sb_beta.setValue(0.15)
        pe_form.addRow("\u03b2 (slip-hardening coeff):", self._sb_beta)

        self._pva_w = QWidget()
        pva_form = QFormLayout(self._pva_w)
        self._sb_G_d = _make_dsb(0.0, 100.0, 3, "J/m\u00b2", 0.1)
        self._sb_G_d.setValue(3.0)
        self._sb_beta_pva = _make_dsb(0.0, 5.0, 3, "", 0.01)
        self._sb_beta_pva.setValue(0.5)
        pva_form.addRow("G_d (J/m\u00b2):", self._sb_G_d)
        pva_form.addRow("\u03b2 (slip-hardening coeff):", self._sb_beta_pva)

        self._steel_w = QWidget()
        steel_form = QFormLayout(self._steel_w)
        self._sb_P_anchor = _make_dsb(0.0, 10000.0, 3, "N", 1.0)
        self._sb_P_anchor.setValue(0.5)
        self._sb_delta_hook = _make_dsb(0.0, 10.0, 3, "mm", 0.01)
        self._sb_delta_hook.setValue(0.5)
        steel_form.addRow("P_anchor (N):", self._sb_P_anchor)
        steel_form.addRow("\u03b4_hook (mm):", self._sb_delta_hook)

        for w in [self._pe_w, self._pva_w, self._steel_w]:
            self._fiber_extras_stack.addWidget(w)
        self._fiber_extras_stack.setCurrentIndex(0)
        sim_layout.addWidget(self._fiber_extras_stack)

        self._btn_run_sim = QPushButton("\u25b6  Run Simulation")
        self._btn_run_sim.setStyleSheet(
            "background:#2980b9;color:white;font-weight:bold;padding:5px;"
        )
        self._sim_progress = QProgressBar()
        self._sim_progress.setVisible(False)
        self._lbl_sim_status = QLabel("")
        sim_layout.addWidget(self._btn_run_sim)
        sim_layout.addWidget(self._sim_progress)
        sim_layout.addWidget(self._lbl_sim_status)

        self._sd_stack.addWidget(csv_page)
        self._sd_stack.addWidget(sim_page)
        outer.addWidget(self._sd_stack)
        return sd_box

    def _build_right_panel(self) -> QWidget:
        self._tabs = QTabWidget()
        # 轻微美化 Tab 外观，提升质感
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #d3d3d3; background: #ffffff; border-radius: 4px; }"
            "QTabBar::tab { padding: 8px 16px; font-weight: bold; color: #555; }"
            "QTabBar::tab:selected { color: #2c3e50; border-bottom: 2px solid #2980b9; }"
        )

        # ------------------------------------------------------------------
        # Tab 1: Single Series Details
        # ------------------------------------------------------------------
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        self._single_canvas = SingleSeriesCanvas(width=7, height=4)
        self._result_labels: dict[str, QLabel] = {}
        rform = QFormLayout()
        for key in ["tau0", "km", "j_tip", "sigma0", "delta0", "jb_prime",
                    "psh_strength", "psh_energy"]:
            lbl = QLabel("\u2014")
            lbl.setStyleSheet("font-size: 14px;")  # 稍微放大单组结果的字体
            self._result_labels[key] = lbl
            rform.addRow(f"{_result_label(key)}:", lbl)
        t1.addWidget(self._single_canvas, stretch=3)
        t1.addLayout(rform, stretch=1)
        self._tabs.addTab(tab1, "Single Series Details")

        # ------------------------------------------------------------------
        # Tab 2: Data Summary
        # ------------------------------------------------------------------
        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        self._table_model = ResultTableModel()
        self._table_view = QTableView()
        self._table_view.setModel(self._table_model)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.setAlternatingRowColors(True)  # 开启斑马纹，增强数据可读性
        self._table_view.setStyleSheet("alternate-background-color: #f9f9f9;")

        exp_row = QHBoxLayout()
        self._btn_export_csv = QPushButton("Export CSV")
        self._btn_export_xlsx = QPushButton("Export Excel")
        self._btn_export_xlsx.setStyleSheet(
            "background-color: #217346; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )  # 给 Excel 按钮加上标志性的暗绿色
        exp_row.addStretch()
        exp_row.addWidget(self._btn_export_csv)
        exp_row.addWidget(self._btn_export_xlsx)

        t2.addWidget(self._table_view)
        t2.addLayout(exp_row)
        self._tabs.addTab(tab2, "Data Summary")

        # ------------------------------------------------------------------
        # Tab 3: Comparative Analytics (🔥 全新优化的看板布局)
        # ------------------------------------------------------------------
        tab3 = QWidget()
        t3_layout = QGridLayout(tab3)
        t3_layout.setContentsMargins(12, 12, 12, 12)
        t3_layout.setSpacing(16)

        # 调整默认的高宽比，适应网格尺寸
        self._iface_canvas = InterfaceComparisonCanvas(width=5, height=3)
        self._matrix_canvas = MatrixComparisonCanvas(width=5, height=3)
        self._overlay_canvas = OverlayCanvas(width=10, height=3.5)

        # 统一设置 GroupBox 样式，去边框化，融入现代极简设计
        gb_style = "QGroupBox { font-weight: bold; border: 1px solid #e0e0e0; border-radius: 6px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: #34495e; }"

        box1 = QGroupBox("Interface Properties: P_peak & \u03c4\u2080")
        box1.setStyleSheet(gb_style)
        l1 = QVBoxLayout(box1)
        l1.addWidget(self._iface_canvas)

        box2 = QGroupBox("Matrix Properties: E_m & K_m")
        box2.setStyleSheet(gb_style)
        l2 = QVBoxLayout(box2)
        l2.addWidget(self._matrix_canvas)

        box3 = QGroupBox("\u03c3\u2013\u03b4 Overlay (All Series)")
        box3.setStyleSheet(gb_style)
        l3 = QVBoxLayout(box3)
        l3.addWidget(self._overlay_canvas)

        # 将模块填入网格 (Widget, row, column, rowSpan, columnSpan)
        t3_layout.addWidget(box1, 0, 0, 1, 1)  # 第一行左侧
        t3_layout.addWidget(box2, 0, 1, 1, 1)  # 第一行右侧
        t3_layout.addWidget(box3, 1, 0, 1, 2)  # 第二行满宽 (跨两列)

        # 设置拉伸因子，让下半部分的曲线图占据稍微多一点的垂直空间
        t3_layout.setRowStretch(0, 4)
        t3_layout.setRowStretch(1, 5)

        self._tabs.addTab(tab3, "Comparative Analytics")

        return self._tabs

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._btn_add.clicked.connect(self._on_add_series)
        self._btn_remove.clicked.connect(self._on_remove_series)
        self._tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self._sd_mode_group.idClicked.connect(self._on_mode_switched)
        self._cmb_fiber_type.currentIndexChanged.connect(self._on_fiber_type_changed)
        self._btn_csv.clicked.connect(self._on_import_csv)
        self._btn_run_sim.clicked.connect(self._on_run_simulation)
        self._btn_run.clicked.connect(self._on_run_analysis)
        self._btn_export_csv.clicked.connect(self._on_export_csv)
        self._btn_export_xlsx.clicked.connect(self._on_export_xlsx)
        self._var_name_edit.textChanged.connect(self._on_var_name_changed)
        self._sb_name.editingFinished.connect(self._on_param_changed)

    # ------------------------------------------------------------------
    # Left-panel slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_add_series(self) -> None:
        entry = self._model.add_series()
        item = QTreeWidgetItem([entry.params.name])
        self._tree.addTopLevelItem(item)
        self._tree.setCurrentItem(item)
        self._status_bar.showMessage(f"Added: {entry.params.name}")

    @Slot()
    def _on_remove_series(self) -> None:
        index = self._current_tree_index()
        if index < 0:
            return
        name = self._model.get_entry(index).params.name
        self._model.remove_series(index)
        self._tree.takeTopLevelItem(index)
        self._current_index = -1
        self._param_box.setEnabled(False)
        self._status_bar.showMessage(f"Removed: {name}")

    @Slot(object, object)
    def _on_tree_selection_changed(
            self,
            current: Optional[QTreeWidgetItem],
            _previous: Optional[QTreeWidgetItem],
    ) -> None:
        if current is None:
            self._param_box.setEnabled(False)
            self._current_index = -1
            return
        index = self._tree.indexOfTopLevelItem(current)
        self._current_index = index
        self._param_box.setEnabled(True)
        self._populate_form(index)
        self._refresh_single_tab(index)

    @Slot()
    def _on_param_changed(self) -> None:
        if self._current_index < 0:
            return
        self._write_form_to_model(self._current_index)
        self._tree.topLevelItem(self._current_index).setText(
            0, self._model.get_entry(self._current_index).params.name
        )

    @Slot(str)
    def _on_var_name_changed(self, text: str) -> None:
        self._model.variable_name = text

    @Slot(int)
    def _on_mode_switched(self, page_id: int) -> None:
        self._sd_stack.setCurrentIndex(page_id)
        if self._current_index >= 0:
            source = "csv" if page_id == _CSV_PAGE else "simulation"
            self._model.get_entry(self._current_index).params.sigma_delta_source = source

    @Slot(int)
    def _on_fiber_type_changed(self, _combo_index: int) -> None:
        key = self._cmb_fiber_type.currentData()
        page = {"PE": 0, "PVA": 1, "STEEL": 2}.get(key, 0)
        self._fiber_extras_stack.setCurrentIndex(page)

    # ------------------------------------------------------------------
    # CSV import slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_import_csv(self) -> None:
        if self._current_index < 0:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open \u03c3\u2013\u03b4 CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path_str:
            return
        path = Path(path_str)
        worker = CsvLoaderWorker(self._current_index, path)
        worker.loaded.connect(self._on_csv_loaded)
        worker.error.connect(self._on_csv_error)

        # 修复：确保 QThread 执行完毕后自我销毁并在列表中清除
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda *_, w=worker: self._csv_workers.remove(w) if w in self._csv_workers else None)

        self._csv_workers.append(worker)
        worker.start()
        self._status_bar.showMessage(f"Loading {path.name}\u2026")

    @Slot(int, object, object)
    def _on_csv_loaded(self, series_index: int, df: pd.DataFrame, path: Path) -> None:
        entry = self._model.get_entry(series_index)
        entry.params.sigma_delta_df = df
        entry.params.sigma_delta_path = path
        entry.params.sigma_delta_source = "csv"
        entry.result = None
        if series_index == self._current_index:
            self._lbl_csv_path.setText(path.name)
        self._status_bar.showMessage(f"Loaded: {path.name} ({len(df)} rows)")

    @Slot(int, str)
    def _on_csv_error(self, _series_index: int, message: str) -> None:
        QMessageBox.critical(self, "CSV Load Error", message)
        self._status_bar.showMessage("CSV load failed.")

    # ------------------------------------------------------------------
    # Simulation slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_run_simulation(self) -> None:
        if self._current_index < 0:
            return
        self._write_form_to_model(self._current_index)
        p = self._model.get_entry(self._current_index).params

        if p.d_f <= 0.0 or p.l_e <= 0.0 or p.p_peak <= 0.0:
            QMessageBox.warning(
                self,
                "Missing Parameters",
                "Please fill in P_peak, d_f and L_e in the Pullout Test section.\n"
                "\u03c4\u2080 is derived from those values and is required for simulation.",
            )
            return

        self._btn_run_sim.setEnabled(False)
        self._sim_progress.setVisible(True)
        self._sim_progress.setValue(0)
        self._lbl_sim_status.setText("Simulating\u2026")

        worker = SimulationWorker(series_index=self._current_index, params=p)
        worker.progress.connect(self._on_sim_progress)
        worker.finished.connect(self._on_sim_finished)
        worker.error.connect(self._on_sim_error)

        # 修复：防止模拟线程的内存泄漏
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda *_, w=worker: self._sim_workers.remove(w) if w in self._sim_workers else None)

        self._sim_workers.append(worker)
        worker.start()

    @Slot(int, int)
    def _on_sim_progress(self, current: int, total: int) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._sim_progress.setValue(pct)
        self._status_bar.showMessage(f"Simulating point {current}/{total}\u2026")

    @Slot(int, object)
    def _on_sim_finished(self, series_index: int, df: pd.DataFrame) -> None:
        entry = self._model.get_entry(series_index)
        entry.params.sigma_delta_df = df
        entry.params.sigma_delta_path = None
        entry.params.sigma_delta_source = "simulation"
        entry.result = None
        n = len(df)
        if series_index == self._current_index:
            self._lbl_sim_status.setText(f"\u2713 Simulated ({n} points)")
            self._sim_progress.setVisible(False)
            self._btn_run_sim.setEnabled(True)
        self._status_bar.showMessage(f"Simulation complete: {n} points.")

    @Slot(int, str)
    def _on_sim_error(self, series_index: int, message: str) -> None:
        if series_index == self._current_index:
            self._sim_progress.setVisible(False)
            self._btn_run_sim.setEnabled(True)
            self._lbl_sim_status.setText("Simulation failed.")
        QMessageBox.critical(self, "Simulation Error", message)
        self._status_bar.showMessage("Simulation failed.")

    # ------------------------------------------------------------------
    # Analysis slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_run_analysis(self) -> None:
        if self._model.is_empty():
            QMessageBox.information(
                self, "No Series", "Add at least one series before running."
            )
            return
        if self._current_index >= 0:
            self._write_form_to_model(self._current_index)

        self._btn_run.setEnabled(False)
        self._main_progress.setVisible(True)
        self._main_progress.setValue(0)

        self._batch_worker = BatchAnalysisWorker(self._model)
        self._batch_worker.series_done.connect(self._on_series_done)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.error.connect(self._on_batch_error)

        # 修复：防止内存泄露
        self._batch_worker.finished.connect(self._batch_worker.deleteLater)
        self._batch_worker.start()

    @Slot(int, object)
    def _on_series_done(self, index: int, result: AnalysisResult) -> None:
        self._model.set_result(index, result)
        if index == self._current_index:
            self._refresh_single_tab(index)

    @Slot(int, int)
    def _on_batch_progress(self, current: int, total: int) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._main_progress.setValue(pct)
        self._status_bar.showMessage(f"Analysing {current}/{total}\u2026")

    @Slot()
    def _on_batch_finished(self) -> None:
        self._btn_run.setEnabled(True)
        self._main_progress.setVisible(False)
        self._status_bar.showMessage("Analysis complete.")
        self._refresh_summary_tab()
        self._refresh_comparative_tab()

    @Slot(int, str)
    def _on_batch_error(self, index: int, message: str) -> None:
        name = self._model.get_entry(index).params.name
        QMessageBox.warning(self, "Analysis Error", f"Series '{name}': {message}")

    # ------------------------------------------------------------------
    # Export slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_csv(self) -> None:
        results = self._model.computed_results()
        if not results:
            QMessageBox.information(self, "No Results", "Run analysis first.")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "ecc_results.csv", "CSV files (*.csv)"
        )
        if not path_str:
            return
        try:
            export_to_csv(results, Path(path_str))
            self._status_bar.showMessage(f"Exported: {Path(path_str).name}")
        except OSError as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    @Slot()
    def _on_export_xlsx(self) -> None:
        # 修复：改用 export.py 中的高级多表导出 Worker
        if self._model.is_empty():
            QMessageBox.information(self, "No Data", "No series data to export.")
            return

        # 防止重复启动导出任务，同时捕获 C++ 对象已删除的 RuntimeError
        try:
            if self._export_worker is not None and self._export_worker.isRunning():
                return
        except RuntimeError:
            self._export_worker = None

        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Excel", "ecc_project_export.xlsx", "Excel files (*.xlsx)"
        )
        if not path_str:
            return

        self._export_worker = DataExportWorker(self._model, Path(path_str))
        self._export_worker.progress.connect(
            lambda pct, msg: self._status_bar.showMessage(f"{msg} ({pct}%)")
        )
        self._export_worker.finished.connect(
            lambda path: self._status_bar.showMessage(f"Exported project to: {path.name}")
        )
        self._export_worker.failed.connect(
            lambda msg: QMessageBox.critical(self, "Export Error", msg)
        )

        # 核心修复：定义清理函数，在结束时安全切断引用
        def cleanup_worker(*_args: object) -> None:
            if self._export_worker is not None:
                self._export_worker.deleteLater()
                self._export_worker = None

        self._export_worker.finished.connect(cleanup_worker)
        self._export_worker.failed.connect(cleanup_worker)

        self._export_worker.start()

    # ------------------------------------------------------------------
    # UI refresh helpers
    # ------------------------------------------------------------------

    def _populate_form(self, index: int) -> None:
        p = self._model.get_entry(index).params

        self._sb_name.setText(p.name)
        self._sb_varval.setValue(p.variable_value)
        self._sb_p_peak.setValue(p.p_peak)
        self._sb_d_f.setValue(p.d_f)
        self._sb_l_e.setValue(p.l_e)
        self._sb_p_max.setValue(p.p_max)
        self._sb_span.setValue(p.span)
        self._sb_b.setValue(p.b)
        self._sb_d.setValue(p.d)
        self._sb_a0.setValue(p.a0)
        self._sb_e_m.setValue(p.e_m)
        self._sb_sigma_fc.setValue(p.sigma_fc)

        source = p.sigma_delta_source
        if source == "csv":
            self._radio_csv.setChecked(True)
            self._sd_stack.setCurrentIndex(_CSV_PAGE)
            path = p.sigma_delta_path
            self._lbl_csv_path.setText(path.name if path else "No file loaded")
        elif source == "simulation":
            self._radio_sim.setChecked(True)
            self._sd_stack.setCurrentIndex(_SIM_PAGE)
            n = len(p.sigma_delta_df) if p.sigma_delta_df is not None else 0
            self._lbl_sim_status.setText(f"\u2713 Simulated ({n} points)" if n else "")
        else:
            self._radio_csv.setChecked(True)
            self._sd_stack.setCurrentIndex(_CSV_PAGE)
            self._lbl_csv_path.setText("No file loaded")

        self._sb_V_f.setValue(p.sim_V_f)
        self._sb_L_f.setValue(p.sim_L_f)
        self._sb_E_f.setValue(p.sim_E_f)
        self._sb_sigma_fu.setValue(p.sim_sigma_fu)
        self._sb_G_d.setValue(p.sim_G_d)
        self._sb_beta.setValue(p.sim_beta)
        self._sb_beta_pva.setValue(p.sim_beta)
        self._sb_f_snubbing.setValue(p.sim_f_snubbing)
        self._sb_n_points.setValue(p.sim_n_delta_points)
        self._sb_P_anchor.setValue(p.sim_P_anchor_max)
        self._sb_delta_hook.setValue(p.sim_delta_hook)

        for i in range(self._cmb_fiber_type.count()):
            if self._cmb_fiber_type.itemData(i) == p.sim_fiber_type:
                self._cmb_fiber_type.setCurrentIndex(i)
                break

    def _write_form_to_model(self, index: int) -> None:
        p = self._model.get_entry(index).params
        old_name = p.name
        p.name = self._sb_name.text().strip() or old_name
        p.variable_value = self._sb_varval.value()
        p.p_peak = self._sb_p_peak.value()
        p.d_f = self._sb_d_f.value()
        p.l_e = self._sb_l_e.value()
        p.p_max = self._sb_p_max.value()
        p.span = self._sb_span.value()
        p.b = self._sb_b.value()
        p.d = self._sb_d.value()
        p.a0 = self._sb_a0.value()
        p.e_m = self._sb_e_m.value()
        p.sigma_fc = self._sb_sigma_fc.value()

        p.sim_fiber_type = self._cmb_fiber_type.currentData()
        p.sim_V_f = self._sb_V_f.value()
        p.sim_L_f = self._sb_L_f.value()
        p.sim_E_f = self._sb_E_f.value()
        p.sim_sigma_fu = self._sb_sigma_fu.value()
        p.sim_G_d = self._sb_G_d.value()
        p.sim_beta = (
            self._sb_beta_pva.value()
            if p.sim_fiber_type == "PVA"
            else self._sb_beta.value()
        )
        p.sim_f_snubbing = self._sb_f_snubbing.value()
        p.sim_n_delta_points = self._sb_n_points.value()
        p.sim_P_anchor_max = self._sb_P_anchor.value()
        p.sim_delta_hook = self._sb_delta_hook.value()

        self._model.get_entry(index).result = None

    def _refresh_single_tab(self, index: int) -> None:
        entry = self._model.get_entry(index)
        if entry.result is None or entry.params.sigma_delta_df is None:
            self._single_canvas.clear_plot()
            for lbl in self._result_labels.values():
                lbl.setText("\u2014")
                lbl.setStyleSheet(_NEUTRAL_CSS)
            return
        self._single_canvas.plot(entry.result, entry.params.sigma_delta_df)
        self._update_result_labels(entry.result)

    def _update_result_labels(self, r: AnalysisResult) -> None:
        self._result_labels["tau0"].setText(f"{r.tau0:.4f} MPa")
        self._result_labels["km"].setText(f"{r.km:.4f} MPa\u00b7m\u00bd")
        self._result_labels["j_tip"].setText(f"{r.j_tip:.4f} J/m\u00b2")
        self._result_labels["sigma0"].setText(f"{r.sigma0:.4f} MPa")
        self._result_labels["delta0"].setText(f"{r.delta0:.4f} mm")
        self._result_labels["jb_prime"].setText(f"{r.jb_prime:.4f} J/m\u00b2")
        self._result_labels["psh_strength"].setText(
            f"{r.psh_strength:.4f}  (\u2265{_PSH_STRENGTH_THRESHOLD} required)"
        )
        self._result_labels["psh_strength"].setStyleSheet(
            _PASS_CSS if r.psh_strength_pass else _FAIL_CSS
        )
        self._result_labels["psh_energy"].setText(
            f"{r.psh_energy:.4f}  (\u2265{_PSH_ENERGY_THRESHOLD} required)"
        )
        self._result_labels["psh_energy"].setStyleSheet(
            _PASS_CSS if r.psh_energy_pass else _FAIL_CSS
        )

    def _refresh_summary_tab(self) -> None:
        results = self._model.computed_results()
        df = results_to_dataframe(results)
        self._table_model.update_data(df)
        self._table_view.resizeColumnsToContents()

    def _refresh_comparative_tab(self) -> None:
        results = self._model.computed_results()
        x_labels = self._model.x_labels()
        var_name = self._model.variable_name

        analysed_params = [
            entry.params
            for entry in self._model
            if entry.result is not None
        ]

        self._iface_canvas.plot(results, analysed_params, x_labels, var_name)
        self._matrix_canvas.plot(results, analysed_params, x_labels, var_name)

        overlay_data = [
            (
                entry.params.name,
                entry.params.sigma_delta_df,
                entry.result.delta0 if entry.result else None,
                entry.result.sigma0 if entry.result else None,
            )
            for entry in self._model
            if entry.params.sigma_delta_df is not None
        ]
        self._overlay_canvas.plot(overlay_data)

    def _current_tree_index(self) -> int:
        item = self._tree.currentItem()
        if item is None:
            return -1
        return self._tree.indexOfTopLevelItem(item)
