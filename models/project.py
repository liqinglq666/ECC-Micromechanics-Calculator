"""Application-level project model for ECC Micromechanics Calculator.

The model is deliberately Qt-free.  Each series owns a stable UUID so
background workers and UI selections never depend on mutable list indices.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4

from core.engine import AnalysisResult, SeriesParams


def _new_series_id() -> str:
    return uuid4().hex


@dataclass
class SeriesEntry:
    """One mix-design series with a stable identity and optional result."""

    params: SeriesParams
    result: AnalysisResult | None = None
    series_id: str = field(default_factory=_new_series_id)


class ProjectModel:
    """Ordered collection of series plus project-level comparison metadata."""

    def __init__(self) -> None:
        self._entries: list[SeriesEntry] = []
        self.variable_name: str = "Variable"
        self._series_counter: int = 0

    # ------------------------------------------------------------------
    # Collection interface
    # ------------------------------------------------------------------

    def add_series(
        self,
        params: SeriesParams | None = None,
        *,
        series_id: str | None = None,
    ) -> SeriesEntry:
        """Append and return a new series.

        Auto-generated display names use a monotonic counter so deleting and
        re-adding series cannot create duplicate default names.
        """
        if params is None:
            self._series_counter += 1
            params = SeriesParams(name=f"Series {self._series_counter}")
        entry = SeriesEntry(params=params, series_id=series_id or _new_series_id())
        self._entries.append(entry)
        return entry

    def remove_series(self, index: int) -> None:
        """Compatibility index-based removal used by existing callers/tests."""
        if not (0 <= index < len(self._entries)):
            raise IndexError(
                f"Series index {index} is out of range (collection length = {len(self._entries)})."
            )
        self._entries.pop(index)

    def remove_series_by_id(self, series_id: str) -> None:
        index = self.index_of(series_id)
        if index < 0:
            raise KeyError(f"Unknown series_id: {series_id}")
        self._entries.pop(index)

    def get_entry(self, index: int) -> SeriesEntry:
        return self._entries[index]

    def get_entry_by_id(self, series_id: str) -> SeriesEntry:
        index = self.index_of(series_id)
        if index < 0:
            raise KeyError(f"Unknown series_id: {series_id}")
        return self._entries[index]

    def find_entry(self, series_id: str) -> SeriesEntry | None:
        index = self.index_of(series_id)
        return self._entries[index] if index >= 0 else None

    def index_of(self, series_id: str) -> int:
        for index, entry in enumerate(self._entries):
            if entry.series_id == series_id:
                return index
        return -1

    def set_result(self, index: int, result: AnalysisResult) -> None:
        """Compatibility index-based setter."""
        self._entries[index].result = result

    def set_result_by_id(self, series_id: str, result: AnalysisResult) -> None:
        self.get_entry_by_id(series_id).result = result

    def invalidate_result(self, series_id: str) -> None:
        self.get_entry_by_id(series_id).result = None

    def clear_curve(self, series_id: str) -> None:
        """Discard the active bridging curve while preserving the selected mode."""
        entry = self.get_entry_by_id(series_id)
        entry.result = None
        entry.params.sigma_delta_df = None
        entry.params.sigma_delta_path = None
        entry.params.sigma_delta_source = "none"

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[SeriesEntry]:
        return iter(self._entries)

    def __getitem__(self, index: int) -> SeriesEntry:
        return self._entries[index]

    # ------------------------------------------------------------------
    # Views used by the UI/export layer
    # ------------------------------------------------------------------

    def computed_results(self) -> list[AnalysisResult]:
        return [entry.result for entry in self._entries if entry.result is not None]

    def computed_entries(self) -> list[SeriesEntry]:
        return [entry for entry in self._entries if entry.result is not None]

    def x_labels(self) -> list[str]:
        analysed = self.computed_entries()
        if not analysed:
            return []

        values = [entry.params.variable_value for entry in analysed]
        if len(set(values)) == len(values):
            return [str(value) for value in values]
        return [entry.params.name for entry in analysed]

    def all_params(self) -> list[SeriesParams]:
        return [entry.params for entry in self._entries]

    def clear_results(self, also_clear_sigma_delta: bool = False) -> None:
        for entry in self._entries:
            entry.result = None
            if also_clear_sigma_delta:
                entry.params.sigma_delta_df = None
                entry.params.sigma_delta_path = None
                entry.params.sigma_delta_source = "none"

    def is_empty(self) -> bool:
        return not self._entries
