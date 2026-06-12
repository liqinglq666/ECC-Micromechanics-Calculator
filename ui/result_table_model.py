"""ui/result_table_model.py

QAbstractTableModel backed by a pandas DataFrame.
Avoids the overhead of populating QTableWidget items cell-by-cell.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from core.engine import AnalysisResult

# PSH thresholds are ClassVar on AnalysisResult — safe to read at module
# import time without constructing an instance.
_PSH_STRENGTH_THRESHOLD: float = AnalysisResult.PSH_STRENGTH_THRESHOLD
_PSH_ENERGY_THRESHOLD:   float = AnalysisResult.PSH_ENERGY_THRESHOLD

_PASS_COLOR = QColor("#d4edda")   # soft green
_FAIL_COLOR = QColor("#f8d7da")   # soft red

# Column names that carry PSH traffic-light colouring.
# 已经与 utils.io 中新的格式化表头对齐
_PSH_COLUMNS: dict[str, float] = {
    "PSH Strength": _PSH_STRENGTH_THRESHOLD,
    "PSH Energy":   _PSH_ENERGY_THRESHOLD,
}


class ResultTableModel(QAbstractTableModel):
    """
    Read-only table model wrapping a results DataFrame.

    PSH Strength and PSH Energy cells receive green/red background
    based on the engineering thresholds to provide instant visual feedback.
    """

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._df: pd.DataFrame = pd.DataFrame()

    def update_data(self, df: pd.DataFrame) -> None:
        """Replace the backing DataFrame and notify all views."""
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()

    # ------------------------------------------------------------------
    # QAbstractTableModel required overrides
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self._df.columns)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        # Return type is Any: Qt may query other roles (font, alignment, etc.)
        # in future extensions — Optional[str] is too narrow.
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None

        col_name = self._df.columns[index.column()]
        value = self._df.iat[index.row(), index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, float):
                return f"{value:.4f}"
            return str(value)

        if role == Qt.ItemDataRole.BackgroundRole:
            if col_name in _PSH_COLUMNS:
                # Guard against NaN / None / non-numeric values (e.g. unanalysed rows).
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return None
                return (
                    _PASS_COLOR if v >= _PSH_COLUMNS[col_name] else _FAIL_COLOR
                )

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

        return None