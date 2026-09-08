"""Matplotlib canvas widgets embedded in the Qt application.

Charts use a publication-oriented style with compact spines, clear labels,
colorblind-safe series colors, and 300-DPI/vector export from a context menu.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

from core.engine import AnalysisResult, SeriesParams

_PALETTE = [
    "#4C72B0",
    "#DD8452",
    "#55A868",
    "#C44E52",
    "#8172B3",
    "#937860",
    "#DA8BC3",
    "#8C8C8C",
    "#CCB974",
    "#64B5CD",
]
_LINESTYLES = ["-", "--", "-.", ":"]


def _style_axes(ax: Axes, xlabel: str = "", ylabel: str = "") -> None:
    """Apply the shared publication-style axis formatting."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=10)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=12)


class _BaseCanvas(FigureCanvasQTAgg):
    """Shared figure lifecycle and export behavior for all canvases."""

    def __init__(self, width: int = 6, height: int = 4, dpi: int = 100) -> None:
        self._fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self._fig)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: white; border: 1px solid #ccc; font-weight: bold; padding: 4px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #2980b9; color: white; }"
        )
        save_action = menu.addAction("💾  Save Figure As...")
        if menu.exec(self.mapToGlobal(pos)) == save_action:
            self._save_image()

    def _save_image(self) -> None:
        file_filter = (
            "PNG Image (*.png);;"
            "SVG Vector Graphics (*.svg);;"
            "PDF Document (*.pdf);;"
            "JPEG Image (*.jpg);;"
            "All Files (*)"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Publication Figure",
            "ecc_figure.png",
            file_filter,
        )
        if not path_str:
            return
        try:
            self._fig.savefig(
                path_str,
                dpi=300,
                bbox_inches="tight",
                facecolor="white",
            )
        except Exception as exc:  # Matplotlib can surface backend/format errors here.
            QMessageBox.critical(self, "Save Error", f"Failed to save image:\n{exc}")

    def _clear(self) -> None:
        self._fig.clf()

    def _draw(self) -> None:
        self._fig.tight_layout()
        self.draw()

    def clear_plot(self) -> None:
        self._clear()
        self._draw()


class SingleSeriesCanvas(_BaseCanvas):
    def plot(self, result: AnalysisResult, df: pd.DataFrame) -> None:
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
        _style_axes(
            ax,
            xlabel="Crack Opening Width $\\delta$ (mm)",
            ylabel="Bridging Stress $\\sigma$ (MPa)",
        )
        ax.legend(frameon=False, fontsize=10)
        self._draw()


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

        ax1.bar(
            x,
            [params.p_peak for params in params_list],
            width=0.5,
            color=_PALETTE[0],
            alpha=0.75,
            label="$P_{peak}$ (N) [bar]",
        )
        ax2.plot(
            x,
            [result.tau0 for result in results],
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

        ax1.plot(
            x,
            [params.e_m for params in params_list],
            color=_PALETTE[2],
            marker="s",
            linewidth=1.8,
            label="$E_m$ (GPa)",
        )
        ax2.plot(
            x,
            [result.km for result in results],
            color=_PALETTE[3],
            marker="^",
            linewidth=1.8,
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


class OverlayCanvas(_BaseCanvas):
    def plot(
        self,
        series_data: list[tuple[str, pd.DataFrame, float | None, float | None]],
    ) -> None:
        self._clear()
        if not series_data:
            self._draw()
            return

        ax: Axes = self._fig.add_subplot(111)
        for index, (name, df, delta0, sigma0) in enumerate(series_data):
            color = _PALETTE[index % len(_PALETTE)]
            linestyle = _LINESTYLES[index // len(_PALETTE) % len(_LINESTYLES)]
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
