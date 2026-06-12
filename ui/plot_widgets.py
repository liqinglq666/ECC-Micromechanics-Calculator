"""ui/plot_widgets.py

Matplotlib canvas widgets for embedding in Qt layouts.
All charts follow a Google Research / Nature-journal aesthetic:
  - Clean spines (top/right removed)
  - No-border legends
  - 12pt axis labels, 10pt ticks
  - tight_layout() always applied
  - Right-click context menu for high-res publication export
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

# --- 新增的 PySide6 导入，用于右键菜单和文件保存对话框 ---
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QFileDialog, QMessageBox

from core.engine import AnalysisResult, SeriesParams

# Colorblind-safe high-contrast palette (Tableau-10 extended)
_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B3", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]

# secondary visual dimension for series beyond palette length
_LINESTYLES = ["-", "--", "-.", ":"]


def _style_axes(ax: Axes, xlabel: str = "", ylabel: str = "") -> None:
    """Apply publication-quality spine and label styling to *ax*."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=10)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=12)


class _BaseCanvas(FigureCanvasQTAgg):
    """Shared boilerplate: figure creation and clear/redraw lifecycle."""

    def __init__(self, width: int = 6, height: int = 4, dpi: int = 100) -> None:
        self._fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self._fig)

        # --- 新增：启用右键菜单 ---
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        """生成并显示右键菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: white; border: 1px solid #ccc; font-weight: bold; padding: 4px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #2980b9; color: white; }"
        )
        save_action = menu.addAction("💾  Save Figure As...")

        # 捕捉用户点击
        action = menu.exec(self.mapToGlobal(pos))
        if action == save_action:
            self._save_image()

    def _save_image(self) -> None:
        """弹出对话框并保存出版级质量图片"""
        file_filter = (
            "PNG Image (*.png);;"
            "SVG Vector Graphics (*.svg);;"
            "PDF Document (*.pdf);;"
            "JPEG Image (*.jpg);;"
            "All Files (*)"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Publication Figure", "ecc_figure.png", file_filter
        )
        if path_str:
            try:
                # 默认使用 300 DPI (期刊标准) 并切除多余白边 (bbox_inches='tight')
                self._fig.savefig(path_str, dpi=300, bbox_inches="tight", facecolor="white")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save image:\n{str(e)}")

    def _clear(self) -> None:
        self._fig.clf()

    def _draw(self) -> None:
        self._fig.tight_layout()
        self.draw()

    def clear_plot(self) -> None:
        self._clear()
        self._draw()


# ---------------------------------------------------------------------------
# Tab 1 — Single series sigma-delta curve
# ---------------------------------------------------------------------------

class SingleSeriesCanvas(_BaseCanvas):
    def plot(
            self,
            result: AnalysisResult,
            df: pd.DataFrame,
    ) -> None:
        self._clear()
        ax: Axes = self._fig.add_subplot(111)

        ax.plot(
            df["delta"],
            df["sigma"],
            color=_PALETTE[0],
            linewidth=1.8,
            label=result.series_name,
        )
        ax.scatter(
            [result.delta0],
            [result.sigma0],
            color=_PALETTE[3],
            s=80,
            zorder=5,
            label=f"Peak ($\\delta_0$={result.delta0:.3f}, $\\sigma_0$={result.sigma0:.2f})",
        )

        _style_axes(ax, xlabel="Crack Opening Width $\\delta$ (mm)", ylabel="Bridging Stress $\\sigma$ (MPa)")
        ax.legend(frameon=False, fontsize=10)
        self._draw()


# ---------------------------------------------------------------------------
# Tab 3a — Interface properties dual-axis bar+line chart
# ---------------------------------------------------------------------------

class InterfaceComparisonCanvas(_BaseCanvas):
    def plot(
            self,
            results: list[AnalysisResult],
            params_list: list[SeriesParams],
            x_labels: list[str],
            variable_name: str,
    ) -> None:
        self._clear()
        if not results:
            self._draw()
            return

        ax1: Axes = self._fig.add_subplot(111)
        ax2: Axes = ax1.twinx()

        x = np.arange(len(x_labels))
        bar_width = 0.5

        p_peak_values = [
            np.pi * p.d_f * r.tau0 * (p.sim_L_f / 2.0)
            for r, p in zip(results, params_list)
        ]
        tau0_values = [r.tau0 for r in results]

        ax1.bar(
            x,
            p_peak_values,
            width=bar_width,
            color=_PALETTE[0],
            alpha=0.75,
            label="$P_{peak}$ (N) [bar]",
        )
        ax2.plot(
            x,
            tau0_values,
            color=_PALETTE[1],
            marker="o",
            linewidth=1.8,
            label="$\\tau_0$ (MPa) [line]",
        )

        ax1.set_xticks(x)
        ax1.set_xticklabels(x_labels, fontsize=10)
        _style_axes(ax1, xlabel=variable_name, ylabel="$P_{peak}$ (N)")
        ax2.set_ylabel("$\\tau_0$ (MPa)", fontsize=12)
        ax2.spines["top"].set_visible(False)
        ax2.tick_params(labelsize=10)

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=10)

        self._draw()


# ---------------------------------------------------------------------------
# Tab 3b — Matrix properties dual-axis line chart
# ---------------------------------------------------------------------------

class MatrixComparisonCanvas(_BaseCanvas):
    def plot(
            self,
            results: list[AnalysisResult],
            params_list: list[SeriesParams],
            x_labels: list[str],
            variable_name: str,
    ) -> None:
        self._clear()
        if not results:
            self._draw()
            return

        ax1: Axes = self._fig.add_subplot(111)
        ax2: Axes = ax1.twinx()

        x = np.arange(len(x_labels))
        em_values = [p.e_m for p in params_list]
        km_values = [r.km for r in results]

        ax1.plot(
            x, em_values,
            color=_PALETTE[2], marker="s", linewidth=1.8,
            label="$E_m$ (GPa)",
        )
        ax2.plot(
            x, km_values,
            color=_PALETTE[3], marker="^", linewidth=1.8,
            label="$K_m$ (MPa·m$^{0.5}$)",
        )

        ax1.set_xticks(x)
        ax1.set_xticklabels(x_labels, fontsize=10)
        _style_axes(ax1, xlabel=variable_name, ylabel="$E_m$ (GPa)")
        ax2.set_ylabel("$K_m$ (MPa·m$^{0.5}$)", fontsize=12)
        ax2.spines["top"].set_visible(False)
        ax2.tick_params(labelsize=10)

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=10)

        self._draw()


# ---------------------------------------------------------------------------
# Tab 3c — Overlaid sigma-delta curves for all series
# ---------------------------------------------------------------------------

class OverlayCanvas(_BaseCanvas):
    def plot(
            self,
            series_data: list[tuple[str, pd.DataFrame, Optional[float], Optional[float]]],
    ) -> None:
        self._clear()
        if not series_data:
            self._draw()
            return

        ax: Axes = self._fig.add_subplot(111)

        for i, (name, df, delta0, sigma0) in enumerate(series_data):
            color = _PALETTE[i % len(_PALETTE)]
            linestyle = _LINESTYLES[i // len(_PALETTE) % len(_LINESTYLES)]

            ax.plot(
                df["delta"],
                df["sigma"],
                color=color,
                linestyle=linestyle,
                linewidth=1.6,
                label=name,
            )
            if delta0 is not None and sigma0 is not None:
                ax.scatter([delta0], [sigma0], color=color, s=60, zorder=5)

        _style_axes(
            ax,
            xlabel="Crack Opening Width $\\delta$ (mm)",
            ylabel="Bridging Stress $\\sigma$ (MPa)",
        )
        ax.legend(frameon=False, fontsize=9)
        self._draw()