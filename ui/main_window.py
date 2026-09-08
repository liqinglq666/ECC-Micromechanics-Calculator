"""Main Qt window for ECC Micromechanics Calculator.

The UI keeps the existing workflow while enforcing three invariants:
1. Form edits are persisted immediately to the selected series.
2. Background results are routed by stable series UUID, never list index.
3. Stale results/curves are invalidated as soon as their inputs change.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.engine import AnalysisResult, SeriesParams
from models.project import ProjectModel, SeriesEntry
from ui.plot_widgets import (
    InterfaceComparisonCanvas,
    MatrixComparisonCanvas,
    OverlayCanvas,
    SingleSeriesCanvas,
)
from ui.result_table_model import ResultTableModel
from ui.workers import BatchAnalysisWorker, CsvLoaderWorker, SimulationWorker
from utils.export import DataExportWorker
from utils.io import export_to_csv, results_to_dataframe

_PSH_STRENGTH_THRESHOLD = AnalysisResult.PSH_STRENGTH_THRESHOLD
_PSH_ENERGY_THRESHOLD = AnalysisResult.PSH_ENERGY_THRESHOLD

_PASS_CSS = "color: #155724; font-weight: bold;"
_FAIL_CSS = "color: #721c24; font-weight: bold;"
_NEUTRAL_CSS = "color: #333333;"

_CSV_PAGE = 0
_SIM_PAGE = 1
_TREE_ID_ROLE = Qt.ItemDataRole.UserRole


@dataclass
class _SimulationUiState:
    progress: int = 0
    status: str = ""


def _make_dsb(
    minimum: float = 0.0,
    maximum: float = 1_000_000.0,
    decimals: int = 4,
    suffix: str = "",
    step: float = 0.01,
) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setSingleStep(step)
    if suffix:
        widget.setSuffix(f"  {suffix}")
    return widget


def _result_label(key: str) -> str:
    labels = {
        "tau0": "τ₀",
        "km": "Kₘ",
        "j_tip": "J_tip",
        "sigma0": "σ₀",
        "delta0": "δ₀",
        "jb_prime": "J_b′",
        "psh_strength": "PSH_strength",
        "psh_energy": "PSH_energy",
    }
    return labels.get(key, key)


class MainWindow(QMainWindow):
    """Top-level application window and coordinator for background workers."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ECC Micromechanics Calculator")
        self.resize(1500, 860)

        self._model = ProjectModel()
        self._current_series_id: Optional[str] = None
        self._loading_form = False
        self._analysis_busy = False

        self._csv_workers: dict[str, CsvLoaderWorker] = {}
        self._sim_workers: dict[str, SimulationWorker] = {}
        self._sim_ui_state: dict[str, _SimulationUiState] = {}
        self._batch_worker: Optional[BatchAnalysisWorker] = None
        self._batch_errors: list[str] = []
        self._export_worker: Optional[DataExportWorker] = None

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

        self._left_scroll = QScrollArea()
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setWidget(self._build_left_panel())
        self._left_scroll.setMinimumWidth(360)
        splitter.addWidget(self._left_scroll)
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._main_progress = QProgressBar()
        self._main_progress.setVisible(False)
        self._main_progress.setMaximumWidth(220)
        self._status_bar.addPermanentWidget(self._main_progress)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        global_box = QGroupBox("Project Settings")
        global_form = QFormLayout(global_box)
        self._var_name_edit = QLineEdit("Variable")
        global_form.addRow("Variable Name:", self._var_name_edit)
        layout.addWidget(global_box)

        tree_box = QGroupBox("Series")
        tree_layout = QVBoxLayout(tree_box)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree_layout.addWidget(self._tree)
        button_row = QHBoxLayout()
        self._btn_add = QPushButton("+ Add Series")
        self._btn_remove = QPushButton("- Remove")
        button_row.addWidget(self._btn_add)
        button_row.addWidget(self._btn_remove)
        tree_layout.addLayout(button_row)
        layout.addWidget(tree_box)

        self._param_box = QGroupBox("Series Parameters")
        self._param_box.setEnabled(False)
        params_form = QFormLayout(self._param_box)
        self._sb_name = QLineEdit()
        self._sb_varval = _make_dsb()

        pullout_box = QGroupBox("① Pullout Test")
        pullout_form = QFormLayout(pullout_box)
        self._sb_p_peak = _make_dsb(suffix="N")
        self._sb_d_f = _make_dsb(0.0, 10.0, 4, "mm", 0.001)
        self._sb_l_e = _make_dsb(suffix="mm")
        pullout_form.addRow("P_peak (N):", self._sb_p_peak)
        pullout_form.addRow("d_f (mm):", self._sb_d_f)
        pullout_form.addRow("L_e (mm):", self._sb_l_e)

        matrix_box = QGroupBox("② Matrix 3-Point Bending")
        matrix_form = QFormLayout(matrix_box)
        self._sb_p_max = _make_dsb(suffix="N")
        self._sb_span = _make_dsb(suffix="mm")
        self._sb_b = _make_dsb(suffix="mm")
        self._sb_d = _make_dsb(suffix="mm")
        self._sb_a0 = _make_dsb(suffix="mm")
        matrix_form.addRow("P_max (N):", self._sb_p_max)
        matrix_form.addRow("Span S (mm):", self._sb_span)
        matrix_form.addRow("Width b (mm):", self._sb_b)
        matrix_form.addRow("Depth d (mm):", self._sb_d)
        matrix_form.addRow("Notch a0 (mm):", self._sb_a0)

        tensile_box = QGroupBox("③ Matrix / Tensile Properties")
        tensile_form = QFormLayout(tensile_box)
        self._sb_e_m = _make_dsb(suffix="GPa")
        self._sb_sigma_fc = _make_dsb(suffix="MPa")
        self._cmb_fracture_condition = QComboBox()
        self._cmb_fracture_condition.addItem("Plane stress", "plane_stress")
        self._cmb_fracture_condition.addItem("Plane strain", "plane_strain")
        self._sb_poisson = _make_dsb(0.0, 0.499, 3, "", 0.01)
        self._sb_poisson.setValue(0.20)
        tensile_form.addRow("E_m (GPa):", self._sb_e_m)
        tensile_form.addRow("σ_fc (MPa):", self._sb_sigma_fc)
        tensile_form.addRow("Fracture condition:", self._cmb_fracture_condition)
        tensile_form.addRow("Poisson ratio ν:", self._sb_poisson)

        params_form.addRow("Series Name:", self._sb_name)
        params_form.addRow("Variable Value:", self._sb_varval)
        for box in (pullout_box, matrix_box, tensile_box, self._build_sigma_delta_box()):
            params_form.addRow(box)
        layout.addWidget(self._param_box)

        self._btn_run = QPushButton("▶  Run Analysis")
        self._btn_run.setStyleSheet(
            "background:#27ae60;color:white;font-weight:bold;padding:6px;"
        )
        layout.addWidget(self._btn_run)
        layout.addStretch()
        return panel

    def _build_sigma_delta_box(self) -> QGroupBox:
        box = QGroupBox("④ σ–δ Bridging Curve")
        outer = QVBoxLayout(box)

        self._radio_csv = QRadioButton("Import from CSV")
        self._radio_sim = QRadioButton("Theoretical Simulation")
        self._radio_csv.setChecked(True)
        self._sd_mode_group = QButtonGroup(box)
        self._sd_mode_group.addButton(self._radio_csv, _CSV_PAGE)
        self._sd_mode_group.addButton(self._radio_sim, _SIM_PAGE)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._radio_csv)
        mode_row.addWidget(self._radio_sim)
        outer.addLayout(mode_row)

        self._sd_stack = QStackedWidget()

        csv_page = QWidget()
        csv_layout = QVBoxLayout(csv_page)
        self._lbl_csv_path = QLabel("No file loaded")
        self._lbl_csv_path.setWordWrap(True)
        self._btn_csv = QPushButton("Import σ–δ CSV…")
        csv_layout.addWidget(self._lbl_csv_path)
        csv_layout.addWidget(self._btn_csv)

        sim_page = QWidget()
        sim_layout = QVBoxLayout(sim_page)
        note = QLabel(
            "<i>d_f is always taken from Pullout Test. τ₀ can be derived from "
            "P_peak and L_e, or supplied directly with τ₀ override.</i>"
        )
        note.setWordWrap(True)
        sim_layout.addWidget(note)

        fiber_form = QFormLayout()
        self._cmb_fiber_type = QComboBox()
        self._cmb_fiber_type.addItem("PE / PP  (smooth)", "PE")
        self._cmb_fiber_type.addItem("PVA  (chemical debonding)", "PVA")
        self._cmb_fiber_type.addItem("Steel  (hooked-end)", "STEEL")
        fiber_form.addRow("Fiber type:", self._cmb_fiber_type)
        sim_layout.addLayout(fiber_form)

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
        self._sb_f_snubbing.setValue(0.20)
        self._sb_tau0_override = _make_dsb(0.0, 100.0, 4, "MPa", 0.01)
        self._sb_f_strength_reduction = _make_dsb(0.0, 5.0, 3, "", 0.01)
        self._cmb_orientation = QComboBox()
        self._cmb_orientation.addItem("3-D isotropic random", "3d")
        self._cmb_orientation.addItem("2-D planar random", "2d")
        self._sb_n_points = QSpinBox()
        self._sb_n_points.setRange(50, 2000)
        self._sb_n_points.setValue(300)
        self._sb_n_points.setSingleStep(50)
        shared_form.addRow("V_f (fiber volume fraction):", self._sb_V_f)
        shared_form.addRow("L_f (mm):", self._sb_L_f)
        shared_form.addRow("E_f (GPa):", self._sb_E_f)
        shared_form.addRow("σ_fu (MPa):", self._sb_sigma_fu)
        shared_form.addRow("f_snubbing:", self._sb_f_snubbing)
        shared_form.addRow("τ₀ override (MPa, 0=derive):", self._sb_tau0_override)
        shared_form.addRow("f′ strength reduction:", self._sb_f_strength_reduction)
        shared_form.addRow("Fiber orientation:", self._cmb_orientation)
        shared_form.addRow("Curve resolution (pts):", self._sb_n_points)
        sim_layout.addLayout(shared_form)

        self._fiber_extras_stack = QStackedWidget()
        self._pe_w = QWidget()
        pe_form = QFormLayout(self._pe_w)
        self._sb_beta = _make_dsb(-1.0, 5.0, 3, "", 0.01)
        self._sb_beta.setValue(0.0)
        pe_form.addRow("β (slip-hardening coeff):", self._sb_beta)

        self._pva_w = QWidget()
        pva_form = QFormLayout(self._pva_w)
        self._sb_G_d = _make_dsb(0.0, 100.0, 3, "J/m²", 0.1)
        self._sb_G_d.setValue(3.0)
        self._sb_beta_pva = _make_dsb(-1.0, 5.0, 3, "", 0.01)
        self._sb_beta_pva.setValue(0.5)
        pva_form.addRow("G_d (J/m²):", self._sb_G_d)
        pva_form.addRow("β (slip-hardening coeff):", self._sb_beta_pva)

        self._steel_w = QWidget()
        steel_form = QFormLayout(self._steel_w)
        self._sb_P_anchor = _make_dsb(0.0, 10000.0, 3, "N", 1.0)
        self._sb_delta_hook = _make_dsb(0.0, 10.0, 3, "mm", 0.01)
        self._sb_delta_hook.setValue(0.5)
        steel_form.addRow("P_anchor (N):", self._sb_P_anchor)
        steel_form.addRow("δ_hook (mm):", self._sb_delta_hook)

        for widget in (self._pe_w, self._pva_w, self._steel_w):
            self._fiber_extras_stack.addWidget(widget)
        sim_layout.addWidget(self._fiber_extras_stack)

        self._btn_run_sim = QPushButton("▶  Run Simulation")
        self._btn_run_sim.setStyleSheet(
            "background:#2980b9;color:white;font-weight:bold;padding:5px;"
        )
        self._sim_progress = QProgressBar()
        self._sim_progress.setVisible(False)
        self._lbl_sim_status = QLabel("")
        self._lbl_sim_status.setWordWrap(True)
        sim_layout.addWidget(self._btn_run_sim)
        sim_layout.addWidget(self._sim_progress)
        sim_layout.addWidget(self._lbl_sim_status)

        self._sd_stack.addWidget(csv_page)
        self._sd_stack.addWidget(sim_page)
        outer.addWidget(self._sd_stack)
        return box

    def _build_right_panel(self) -> QWidget:
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #d3d3d3; background:#fff; border-radius:4px; }"
            "QTabBar::tab { padding:8px 16px; font-weight:bold; color:#555; }"
            "QTabBar::tab:selected { color:#2c3e50; border-bottom:2px solid #2980b9; }"
        )

        single_tab = QWidget()
        single_layout = QVBoxLayout(single_tab)
        self._single_canvas = SingleSeriesCanvas(width=7, height=4)
        self._result_labels: dict[str, QLabel] = {}
        result_form = QFormLayout()
        for key in (
            "tau0", "km", "j_tip", "sigma0", "delta0", "jb_prime",
            "psh_strength", "psh_energy",
        ):
            label = QLabel("—")
            label.setStyleSheet("font-size:14px;")
            self._result_labels[key] = label
            result_form.addRow(f"{_result_label(key)}:", label)
        single_layout.addWidget(self._single_canvas, stretch=3)
        single_layout.addLayout(result_form, stretch=1)
        self._tabs.addTab(single_tab, "Single Series Details")

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        self._table_model = ResultTableModel()
        self._table_view = QTableView()
        self._table_view.setModel(self._table_model)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setStyleSheet("alternate-background-color:#f9f9f9;")
        export_row = QHBoxLayout()
        self._btn_export_csv = QPushButton("Export CSV")
        self._btn_export_xlsx = QPushButton("Export Excel")
        self._btn_export_xlsx.setStyleSheet(
            "background-color:#217346;color:white;font-weight:bold;padding:6px 12px;border-radius:4px;"
        )
        export_row.addStretch()
        export_row.addWidget(self._btn_export_csv)
        export_row.addWidget(self._btn_export_xlsx)
        summary_layout.addWidget(self._table_view)
        summary_layout.addLayout(export_row)
        self._tabs.addTab(summary_tab, "Data Summary")

        comparison_tab = QWidget()
        comparison_layout = QGridLayout(comparison_tab)
        comparison_layout.setContentsMargins(12, 12, 12, 12)
        comparison_layout.setSpacing(16)
        self._iface_canvas = InterfaceComparisonCanvas(width=5, height=3)
        self._matrix_canvas = MatrixComparisonCanvas(width=5, height=3)
        self._overlay_canvas = OverlayCanvas(width=10, height=3.5)
        group_style = (
            "QGroupBox { font-weight:bold; border:1px solid #e0e0e0; border-radius:6px; "
            "margin-top:10px; } QGroupBox::title { subcontrol-origin:margin; left:10px; "
            "padding:0 3px; color:#34495e; }"
        )
        iface_box = QGroupBox("Interface Properties: P_peak & τ₀")
        iface_box.setStyleSheet(group_style)
        iface_layout = QVBoxLayout(iface_box)
        iface_layout.addWidget(self._iface_canvas)
        matrix_box = QGroupBox("Matrix Properties: E_m & K_m")
        matrix_box.setStyleSheet(group_style)
        matrix_layout = QVBoxLayout(matrix_box)
        matrix_layout.addWidget(self._matrix_canvas)
        overlay_box = QGroupBox("σ–δ Overlay (All Series)")
        overlay_box.setStyleSheet(group_style)
        overlay_layout = QVBoxLayout(overlay_box)
        overlay_layout.addWidget(self._overlay_canvas)
        comparison_layout.addWidget(iface_box, 0, 0)
        comparison_layout.addWidget(matrix_box, 0, 1)
        comparison_layout.addWidget(overlay_box, 1, 0, 1, 2)
        comparison_layout.setRowStretch(0, 4)
        comparison_layout.setRowStretch(1, 5)
        self._tabs.addTab(comparison_tab, "Comparative Analytics")
        return self._tabs

    # ------------------------------------------------------------------
    # Signal wiring and form binding
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

        self._sb_name.textEdited.connect(self._on_form_edited)
        for widget in self._numeric_form_widgets():
            widget.valueChanged.connect(self._on_form_edited)
        for combo in (
            self._cmb_fracture_condition,
            self._cmb_fiber_type,
            self._cmb_orientation,
        ):
            combo.currentIndexChanged.connect(self._on_form_edited)

    def _numeric_form_widgets(self) -> tuple[QDoubleSpinBox | QSpinBox, ...]:
        return (
            self._sb_varval,
            self._sb_p_peak,
            self._sb_d_f,
            self._sb_l_e,
            self._sb_p_max,
            self._sb_span,
            self._sb_b,
            self._sb_d,
            self._sb_a0,
            self._sb_e_m,
            self._sb_sigma_fc,
            self._sb_poisson,
            self._sb_V_f,
            self._sb_L_f,
            self._sb_E_f,
            self._sb_sigma_fu,
            self._sb_f_snubbing,
            self._sb_tau0_override,
            self._sb_f_strength_reduction,
            self._sb_n_points,
            self._sb_beta,
            self._sb_G_d,
            self._sb_beta_pva,
            self._sb_P_anchor,
            self._sb_delta_hook,
        )

    # ------------------------------------------------------------------
    # Series identity helpers
    # ------------------------------------------------------------------

    def _item_series_id(self, item: Optional[QTreeWidgetItem]) -> Optional[str]:
        if item is None:
            return None
        value = item.data(0, _TREE_ID_ROLE)
        return str(value) if value else None

    def _current_entry(self) -> Optional[SeriesEntry]:
        if self._current_series_id is None:
            return None
        return self._model.find_entry(self._current_series_id)

    def _tree_item_for_id(self, series_id: str) -> Optional[QTreeWidgetItem]:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if self._item_series_id(item) == series_id:
                return item
        return None

    # ------------------------------------------------------------------
    # Form persistence and invalidation
    # ------------------------------------------------------------------

    @Slot()
    def _on_form_edited(self, *_args: object) -> None:
        if self._loading_form or self._analysis_busy:
            return
        entry = self._current_entry()
        if entry is None:
            return

        old_simulation_signature = entry.params.simulation_signature()
        had_result = entry.result is not None
        self._write_form_to_params(entry.params)
        new_simulation_signature = entry.params.simulation_signature()

        curve_cleared = False
        if (
            entry.params.sigma_delta_source == "simulation"
            and old_simulation_signature != new_simulation_signature
        ):
            self._model.clear_curve(entry.series_id)
            state = self._sim_ui_state.setdefault(entry.series_id, _SimulationUiState())
            state.status = "Simulation parameters changed — run simulation again."
            curve_cleared = True
        else:
            entry.result = None

        item = self._tree_item_for_id(entry.series_id)
        if item is not None:
            item.setText(0, entry.params.name)

        if had_result or curve_cleared:
            self._refresh_all_views()
        self._sync_simulation_ui()

    def _write_form_to_params(self, params: SeriesParams) -> None:
        params.name = self._sb_name.text().strip() or params.name
        params.variable_value = self._sb_varval.value()
        params.p_peak = self._sb_p_peak.value()
        params.d_f = self._sb_d_f.value()
        params.l_e = self._sb_l_e.value()
        params.p_max = self._sb_p_max.value()
        params.span = self._sb_span.value()
        params.b = self._sb_b.value()
        params.d = self._sb_d.value()
        params.a0 = self._sb_a0.value()
        params.e_m = self._sb_e_m.value()
        params.sigma_fc = self._sb_sigma_fc.value()
        params.fracture_condition = self._cmb_fracture_condition.currentData()
        params.poisson_ratio = self._sb_poisson.value()

        params.sim_fiber_type = self._cmb_fiber_type.currentData()
        params.sim_V_f = self._sb_V_f.value()
        params.sim_L_f = self._sb_L_f.value()
        params.sim_E_f = self._sb_E_f.value()
        params.sim_sigma_fu = self._sb_sigma_fu.value()
        params.sim_G_d = self._sb_G_d.value()
        params.sim_beta = (
            self._sb_beta_pva.value()
            if params.sim_fiber_type == "PVA"
            else self._sb_beta.value()
        )
        params.sim_f_snubbing = self._sb_f_snubbing.value()
        params.sim_tau0_override = self._sb_tau0_override.value()
        params.sim_f_strength_reduction = self._sb_f_strength_reduction.value()
        params.sim_orientation = self._cmb_orientation.currentData()
        params.sim_n_delta_points = self._sb_n_points.value()
        params.sim_P_anchor_max = self._sb_P_anchor.value()
        params.sim_delta_hook = self._sb_delta_hook.value()

    def _populate_form_by_id(self, series_id: str) -> None:
        entry = self._model.get_entry_by_id(series_id)
        params = entry.params
        self._loading_form = True
        try:
            self._sb_name.setText(params.name)
            self._sb_varval.setValue(params.variable_value)
            self._sb_p_peak.setValue(params.p_peak)
            self._sb_d_f.setValue(params.d_f)
            self._sb_l_e.setValue(params.l_e)
            self._sb_p_max.setValue(params.p_max)
            self._sb_span.setValue(params.span)
            self._sb_b.setValue(params.b)
            self._sb_d.setValue(params.d)
            self._sb_a0.setValue(params.a0)
            self._sb_e_m.setValue(params.e_m)
            self._sb_sigma_fc.setValue(params.sigma_fc)
            self._set_combo_by_data(self._cmb_fracture_condition, params.fracture_condition)
            self._sb_poisson.setValue(params.poisson_ratio)

            mode = params.sigma_delta_mode
            self._radio_sim.setChecked(mode == "simulation")
            self._radio_csv.setChecked(mode != "simulation")
            self._sd_stack.setCurrentIndex(_SIM_PAGE if mode == "simulation" else _CSV_PAGE)

            self._sb_V_f.setValue(params.sim_V_f)
            self._sb_L_f.setValue(params.sim_L_f)
            self._sb_E_f.setValue(params.sim_E_f)
            self._sb_sigma_fu.setValue(params.sim_sigma_fu)
            self._sb_G_d.setValue(params.sim_G_d)
            self._sb_beta.setValue(params.sim_beta)
            self._sb_beta_pva.setValue(params.sim_beta)
            self._sb_f_snubbing.setValue(params.sim_f_snubbing)
            self._sb_tau0_override.setValue(params.sim_tau0_override)
            self._sb_f_strength_reduction.setValue(params.sim_f_strength_reduction)
            self._set_combo_by_data(self._cmb_orientation, params.sim_orientation)
            self._sb_n_points.setValue(params.sim_n_delta_points)
            self._sb_P_anchor.setValue(params.sim_P_anchor_max)
            self._sb_delta_hook.setValue(params.sim_delta_hook)
            self._set_combo_by_data(self._cmb_fiber_type, params.sim_fiber_type)
            self._on_fiber_type_changed(self._cmb_fiber_type.currentIndex())

            if params.sigma_delta_source == "csv" and params.sigma_delta_path:
                self._lbl_csv_path.setText(params.sigma_delta_path.name)
            else:
                self._lbl_csv_path.setText("No file loaded")
        finally:
            self._loading_form = False
        self._sync_simulation_ui()

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    # Compatibility helpers used by the screenshot automation.
    def _write_form_to_model(self, index: int) -> None:
        entry = self._model.get_entry(index)
        self._write_form_to_params(entry.params)
        entry.result = None

    def _populate_form(self, index: int) -> None:
        self._populate_form_by_id(self._model.get_entry(index).series_id)

    # ------------------------------------------------------------------
    # Series slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_add_series(self) -> None:
        entry = self._model.add_series()
        item = QTreeWidgetItem([entry.params.name])
        item.setData(0, _TREE_ID_ROLE, entry.series_id)
        self._tree.addTopLevelItem(item)
        self._tree.setCurrentItem(item)
        self._status_bar.showMessage(f"Added: {entry.params.name}")

    @Slot()
    def _on_remove_series(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        if entry.series_id in self._csv_workers or entry.series_id in self._sim_workers:
            QMessageBox.information(
                self,
                "Series Busy",
                "This series has a background task running. Wait for it to finish before removing it.",
            )
            return
        if self._analysis_busy:
            return

        item = self._tree_item_for_id(entry.series_id)
        index = self._tree.indexOfTopLevelItem(item) if item is not None else -1
        self._model.remove_series_by_id(entry.series_id)
        if index >= 0:
            self._tree.takeTopLevelItem(index)

        self._current_series_id = None
        if self._tree.topLevelItemCount() > 0:
            next_index = min(max(index, 0), self._tree.topLevelItemCount() - 1)
            self._tree.setCurrentItem(self._tree.topLevelItem(next_index))
        else:
            self._param_box.setEnabled(False)
            self._clear_single_view()
        self._refresh_summary_tab()
        self._refresh_comparative_tab()
        self._status_bar.showMessage(f"Removed: {entry.params.name}")

    @Slot(object, object)
    def _on_tree_selection_changed(
        self,
        current: Optional[QTreeWidgetItem],
        _previous: Optional[QTreeWidgetItem],
    ) -> None:
        series_id = self._item_series_id(current)
        self._current_series_id = series_id
        self._param_box.setEnabled(series_id is not None and not self._analysis_busy)
        if series_id is None:
            self._clear_single_view()
            return
        self._populate_form_by_id(series_id)
        self._refresh_single_by_id(series_id)

    @Slot(str)
    def _on_var_name_changed(self, text: str) -> None:
        self._model.variable_name = text
        if self._model.computed_results():
            self._refresh_comparative_tab()

    @Slot(int)
    def _on_mode_switched(self, page_id: int) -> None:
        if self._loading_form:
            return
        entry = self._current_entry()
        if entry is None:
            return
        new_mode = "csv" if page_id == _CSV_PAGE else "simulation"
        self._sd_stack.setCurrentIndex(page_id)
        if entry.params.sigma_delta_mode == new_mode:
            return

        entry.params.sigma_delta_mode = new_mode
        if entry.params.sigma_delta_source not in {"none", new_mode}:
            self._model.clear_curve(entry.series_id)
        else:
            entry.result = None
        if new_mode == "simulation":
            self._sim_ui_state.setdefault(entry.series_id, _SimulationUiState()).status = (
                "Run simulation to generate the active σ–δ curve."
            )
        self._refresh_all_views()
        self._sync_simulation_ui()

    @Slot(int)
    def _on_fiber_type_changed(self, _index: int) -> None:
        key = self._cmb_fiber_type.currentData()
        self._fiber_extras_stack.setCurrentIndex({"PE": 0, "PVA": 1, "STEEL": 2}.get(key, 0))

    # ------------------------------------------------------------------
    # CSV loading
    # ------------------------------------------------------------------

    @Slot()
    def _on_import_csv(self) -> None:
        entry = self._current_entry()
        if entry is None or entry.series_id in self._csv_workers:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open σ–δ CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if not path_str:
            return

        worker = CsvLoaderWorker(entry.series_id, Path(path_str))
        worker.loaded.connect(self._on_csv_loaded)
        worker.failed.connect(self._on_csv_error)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            lambda sid=entry.series_id, w=worker: self._cleanup_csv_worker(sid, w)
        )
        self._csv_workers[entry.series_id] = worker
        worker.start()
        self._status_bar.showMessage(f"Loading {Path(path_str).name}…")

    @Slot(str, object, object)
    def _on_csv_loaded(self, series_id: str, df: pd.DataFrame, path: Path) -> None:
        entry = self._model.find_entry(series_id)
        if entry is None:
            return
        entry.params.sigma_delta_mode = "csv"
        entry.params.sigma_delta_df = df
        entry.params.sigma_delta_path = path
        entry.params.sigma_delta_source = "csv"
        entry.result = None
        if series_id == self._current_series_id:
            self._lbl_csv_path.setText(path.name)
        self._refresh_all_views()
        self._status_bar.showMessage(f"Loaded: {path.name} ({len(df)} rows)")

    @Slot(str, str)
    def _on_csv_error(self, series_id: str, message: str) -> None:
        if self._model.find_entry(series_id) is not None:
            QMessageBox.critical(self, "CSV Load Error", message)
        self._status_bar.showMessage("CSV load failed.")

    def _cleanup_csv_worker(self, series_id: str, worker: CsvLoaderWorker) -> None:
        if self._csv_workers.get(series_id) is worker:
            self._csv_workers.pop(series_id, None)

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    @Slot()
    def _on_run_simulation(self) -> None:
        entry = self._current_entry()
        if entry is None or entry.series_id in self._sim_workers:
            return
        self._write_form_to_params(entry.params)
        params = entry.params

        if params.d_f <= 0.0:
            QMessageBox.warning(self, "Missing Parameters", "d_f must be positive.")
            return
        if params.sim_tau0_override <= 0.0 and (params.p_peak <= 0.0 or params.l_e <= 0.0):
            QMessageBox.warning(
                self,
                "Missing Parameters",
                "Provide positive P_peak and L_e, or enter a positive τ₀ override.",
            )
            return

        try:
            worker = SimulationWorker(entry.series_id, params)
        except ValueError as exc:
            QMessageBox.warning(self, "Simulation Parameters", str(exc))
            return

        state = self._sim_ui_state.setdefault(entry.series_id, _SimulationUiState())
        state.progress = 0
        state.status = "Simulating…"
        worker.progress.connect(self._on_sim_progress)
        worker.result_ready.connect(self._on_sim_result)
        worker.failed.connect(self._on_sim_error)
        worker.cancelled.connect(self._on_sim_cancelled)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            lambda sid=entry.series_id, w=worker: self._cleanup_sim_worker(sid, w)
        )
        self._sim_workers[entry.series_id] = worker
        self._sync_simulation_ui()
        worker.start()

    @Slot(str, int, int)
    def _on_sim_progress(self, series_id: str, current: int, total: int) -> None:
        state = self._sim_ui_state.setdefault(series_id, _SimulationUiState())
        state.progress = int(current / total * 100) if total > 0 else 0
        state.status = f"Simulating point {current}/{total}…"
        if series_id == self._current_series_id:
            self._sync_simulation_ui()
        self._status_bar.showMessage(state.status)

    @Slot(str, object)
    def _on_sim_result(self, series_id: str, df: pd.DataFrame) -> None:
        entry = self._model.find_entry(series_id)
        if entry is None:
            return
        expected = entry.params.simulation_signature()
        actual = df.attrs.get("simulation_signature")
        state = self._sim_ui_state.setdefault(series_id, _SimulationUiState())
        if actual != expected:
            state.status = "Parameters changed during simulation — result discarded."
            if series_id == self._current_series_id:
                self._sync_simulation_ui()
            return

        entry.params.sigma_delta_mode = "simulation"
        entry.params.sigma_delta_df = df
        entry.params.sigma_delta_path = None
        entry.params.sigma_delta_source = "simulation"
        entry.result = None
        state.progress = 100
        state.status = f"✓ Simulated ({len(df)} points)"
        self._refresh_all_views()
        self._status_bar.showMessage(f"Simulation complete: {len(df)} points.")

    @Slot(str, str)
    def _on_sim_error(self, series_id: str, message: str) -> None:
        state = self._sim_ui_state.setdefault(series_id, _SimulationUiState())
        state.status = "Simulation failed."
        if series_id == self._current_series_id:
            self._sync_simulation_ui()
            QMessageBox.critical(self, "Simulation Error", message)
        self._status_bar.showMessage(f"Simulation failed: {message}")

    @Slot(str)
    def _on_sim_cancelled(self, series_id: str) -> None:
        self._sim_ui_state.setdefault(series_id, _SimulationUiState()).status = "Simulation cancelled."
        if series_id == self._current_series_id:
            self._sync_simulation_ui()

    def _cleanup_sim_worker(self, series_id: str, worker: SimulationWorker) -> None:
        if self._sim_workers.get(series_id) is worker:
            self._sim_workers.pop(series_id, None)
        self._sync_simulation_ui()

    def _sync_simulation_ui(self) -> None:
        series_id = self._current_series_id
        if series_id is None:
            self._btn_run_sim.setEnabled(False)
            self._sim_progress.setVisible(False)
            self._lbl_sim_status.setText("")
            return

        running = series_id in self._sim_workers
        state = self._sim_ui_state.get(series_id, _SimulationUiState())
        entry = self._model.find_entry(series_id)
        if entry is not None and not state.status:
            if entry.params.sigma_delta_source == "simulation" and entry.params.sigma_delta_df is not None:
                state.status = f"✓ Simulated ({len(entry.params.sigma_delta_df)} points)"
        self._btn_run_sim.setEnabled(not running and not self._analysis_busy)
        self._sim_progress.setVisible(running)
        self._sim_progress.setValue(state.progress)
        self._lbl_sim_status.setText(state.status)

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    @Slot()
    def _on_run_analysis(self) -> None:
        if self._model.is_empty():
            QMessageBox.information(self, "No Series", "Add at least one series before running.")
            return
        entry = self._current_entry()
        if entry is not None:
            self._write_form_to_params(entry.params)

        not_ready = self._analysis_preflight()
        if not_ready:
            QMessageBox.warning(
                self,
                "Series Not Ready",
                "Analysis was not started. Prepare σ–δ data for:\n\n" + "\n".join(not_ready),
            )
            return

        self._batch_errors = []
        self._set_analysis_busy(True)
        worker = BatchAnalysisWorker(self._model)
        self._batch_worker = worker
        worker.series_done.connect(self._on_series_done)
        worker.series_failed.connect(self._on_batch_error)
        worker.progress.connect(self._on_batch_progress)
        worker.completed.connect(self._on_batch_completed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self._cleanup_batch_worker(w))
        worker.start()

    def _analysis_preflight(self) -> list[str]:
        problems: list[str] = []
        for entry in self._model:
            params = entry.params
            df = params.sigma_delta_df
            if df is None or params.sigma_delta_source not in {"csv", "simulation"}:
                problems.append(f"• {params.name}: no active σ–δ curve")
                continue
            actual_source = df.attrs.get("source")
            if actual_source is not None and actual_source != params.sigma_delta_source:
                problems.append(f"• {params.name}: curve source mismatch")
                continue
            if (
                params.sigma_delta_source == "simulation"
                and df.attrs.get("simulation_signature") != params.simulation_signature()
            ):
                problems.append(f"• {params.name}: simulated curve is stale; rerun simulation")
        return problems

    @Slot(str, object)
    def _on_series_done(self, series_id: str, result: AnalysisResult) -> None:
        entry = self._model.find_entry(series_id)
        if entry is None:
            return
        entry.result = result
        if series_id == self._current_series_id:
            self._refresh_single_by_id(series_id)

    @Slot(str, str)
    def _on_batch_error(self, series_id: str, message: str) -> None:
        entry = self._model.find_entry(series_id)
        name = entry.params.name if entry is not None else series_id
        self._batch_errors.append(f"{name}: {message}")

    @Slot(int, int)
    def _on_batch_progress(self, current: int, total: int) -> None:
        self._main_progress.setValue(int(current / total * 100) if total else 0)
        self._status_bar.showMessage(f"Analysing {current}/{total}…")

    @Slot(int, int)
    def _on_batch_completed(self, succeeded: int, total: int) -> None:
        self._refresh_summary_tab()
        self._refresh_comparative_tab()
        if self._batch_errors:
            QMessageBox.warning(
                self,
                "Analysis Completed with Errors",
                "\n".join(self._batch_errors),
            )
            self._status_bar.showMessage(f"Analysis complete: {succeeded}/{total} succeeded.")
        else:
            self._status_bar.showMessage("Analysis complete.")

    def _cleanup_batch_worker(self, worker: BatchAnalysisWorker) -> None:
        if self._batch_worker is worker:
            self._batch_worker = None
        self._set_analysis_busy(False)

    def _set_analysis_busy(self, busy: bool) -> None:
        self._analysis_busy = busy
        self._btn_run.setEnabled(not busy)
        self._btn_add.setEnabled(not busy)
        self._btn_remove.setEnabled(not busy)
        self._param_box.setEnabled(not busy and self._current_series_id is not None)
        self._main_progress.setVisible(busy)
        if busy:
            self._main_progress.setValue(0)
        self._sync_simulation_ui()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_csv(self) -> None:
        entry = self._current_entry()
        if entry is not None and not self._analysis_busy:
            self._write_form_to_params(entry.params)
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
        if self._model.is_empty():
            QMessageBox.information(self, "No Data", "No series data to export.")
            return
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        entry = self._current_entry()
        if entry is not None and not self._analysis_busy:
            self._write_form_to_params(entry.params)

        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Excel", "ecc_project_export.xlsx", "Excel files (*.xlsx)"
        )
        if not path_str:
            return

        worker = DataExportWorker(self._model, Path(path_str))
        self._export_worker = worker
        worker.progress.connect(
            lambda pct, msg: self._status_bar.showMessage(f"{msg} ({pct}%)")
        )
        worker.succeeded.connect(
            lambda path: self._status_bar.showMessage(f"Exported project to: {path.name}")
        )
        worker.failed.connect(lambda msg: QMessageBox.critical(self, "Export Error", msg))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self._cleanup_export_worker(w))
        worker.start()

    def _cleanup_export_worker(self, worker: DataExportWorker) -> None:
        if self._export_worker is worker:
            self._export_worker = None

    # ------------------------------------------------------------------
    # View refresh
    # ------------------------------------------------------------------

    def _refresh_all_views(self) -> None:
        if self._current_series_id is not None:
            self._refresh_single_by_id(self._current_series_id)
        else:
            self._clear_single_view()
        self._refresh_summary_tab()
        self._refresh_comparative_tab()

    def _refresh_single_by_id(self, series_id: str) -> None:
        entry = self._model.find_entry(series_id)
        if entry is None or entry.result is None or entry.params.sigma_delta_df is None:
            self._clear_single_view()
            return
        self._single_canvas.plot(entry.result, entry.params.sigma_delta_df)
        self._update_result_labels(entry.result)

    def _refresh_single_tab(self, index: int) -> None:
        self._refresh_single_by_id(self._model.get_entry(index).series_id)

    def _clear_single_view(self) -> None:
        self._single_canvas.clear_plot()
        for label in self._result_labels.values():
            label.setText("—")
            label.setStyleSheet(_NEUTRAL_CSS)

    def _update_result_labels(self, result: AnalysisResult) -> None:
        self._result_labels["tau0"].setText(f"{result.tau0:.4f} MPa")
        self._result_labels["km"].setText(f"{result.km:.4f} MPa·m½")
        self._result_labels["j_tip"].setText(f"{result.j_tip:.4f} J/m²")
        self._result_labels["sigma0"].setText(f"{result.sigma0:.4f} MPa")
        self._result_labels["delta0"].setText(f"{result.delta0:.4f} mm")
        self._result_labels["jb_prime"].setText(f"{result.jb_prime:.4f} J/m²")
        self._result_labels["psh_strength"].setText(
            f"{result.psh_strength:.4f}  (≥{_PSH_STRENGTH_THRESHOLD} required)"
        )
        self._result_labels["psh_strength"].setStyleSheet(
            _PASS_CSS if result.psh_strength_pass else _FAIL_CSS
        )
        self._result_labels["psh_energy"].setText(
            f"{result.psh_energy:.4f}  (≥{_PSH_ENERGY_THRESHOLD} required)"
        )
        self._result_labels["psh_energy"].setStyleSheet(
            _PASS_CSS if result.psh_energy_pass else _FAIL_CSS
        )

    def _refresh_summary_tab(self) -> None:
        self._table_model.update_data(results_to_dataframe(self._model.computed_results()))
        self._table_view.resizeColumnsToContents()

    def _refresh_comparative_tab(self) -> None:
        results = self._model.computed_results()
        analysed_params = [entry.params for entry in self._model.computed_entries()]
        x_labels = self._model.x_labels()
        variable_name = self._model.variable_name
        self._iface_canvas.plot(results, analysed_params, x_labels, variable_name)
        self._matrix_canvas.plot(results, analysed_params, x_labels, variable_name)

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

    # ------------------------------------------------------------------
    # Safe shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        workers = [*self._csv_workers.values(), *self._sim_workers.values()]
        if self._batch_worker is not None:
            workers.append(self._batch_worker)
        if self._export_worker is not None:
            workers.append(self._export_worker)

        running = [worker for worker in workers if worker.isRunning()]
        for worker in running:
            worker.requestInterruption()
        for worker in running:
            worker.wait(5000)

        still_running = [worker for worker in running if worker.isRunning()]
        if still_running:
            QMessageBox.warning(
                self,
                "Background Task Running",
                "A background calculation or export is still finishing. "
                "Please wait a moment and close the application again.",
            )
            event.ignore()
            return
        event.accept()
