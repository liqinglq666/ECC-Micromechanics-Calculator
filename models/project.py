"""models/project.py

Application-level data model. Single source of truth for all series data.
Zero Qt dependencies — keeps the domain layer independently testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from core.engine import AnalysisResult, SeriesParams
from core.simulation import FiberType


@dataclass
class SeriesEntry:
    """One mix-design series: params + optional computed result."""

    params: SeriesParams
    result: Optional[AnalysisResult] = field(default=None)


class ProjectModel:
    """
    Ordered collection of SeriesEntry objects plus project-level metadata.

    All mutation goes through explicit methods so the UI layer can call them
    and then refresh itself — no implicit state sharing.
    """

    def __init__(self) -> None:
        self._entries: list[SeriesEntry] = []
        self.variable_name: str = "Variable"

        # Monotonically increasing counter for series naming.
        # Never decremented on removal, so names stay unique even after
        # delete-then-add sequences (avoids "Series 3 / Series 3" collisions).
        self._series_counter: int = 0

    # ------------------------------------------------------------------
    # Collection interface
    # ------------------------------------------------------------------

    def add_series(self, params: Optional[SeriesParams] = None) -> SeriesEntry:
        """Append a new series (empty by default) and return it."""
        if params is None:
            self._series_counter += 1
            params = SeriesParams(name=f"Series {self._series_counter}")
        entry = SeriesEntry(params=params)
        self._entries.append(entry)
        return entry

    def remove_series(self, index: int) -> None:
        """
        Remove series at *index*.

        Raises IndexError for out-of-range indices so that bugs in the UI
        layer are surfaced immediately rather than silently swallowed.
        """
        if not (0 <= index < len(self._entries)):
            raise IndexError(
                f"Series index {index} is out of range "
                f"(collection length = {len(self._entries)})."
            )
        self._entries.pop(index)

    def get_entry(self, index: int) -> SeriesEntry:
        return self._entries[index]

    def set_result(self, index: int, result: AnalysisResult) -> None:
        self._entries[index].result = result

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[SeriesEntry]:
        return iter(self._entries)

    def __getitem__(self, index: int) -> SeriesEntry:
        return self._entries[index]

    # ------------------------------------------------------------------
    # Convenience views used by plot and table layers
    # ------------------------------------------------------------------

    def computed_results(self) -> list[AnalysisResult]:
        """Return only results for series that have been analysed."""
        return [
            entry.result
            for entry in self._entries
            if entry.result is not None
        ]

    def x_labels(self) -> list[str]:
        """
        Build X-axis tick labels for comparative charts.

        Uses variable_value when all analysed series have unique values;
        falls back to series names to avoid ambiguous duplicate labels.
        """
        analysed = [
            entry for entry in self._entries if entry.result is not None
        ]
        if not analysed:
            return []

        values = [e.params.variable_value for e in analysed]
        if len(set(values)) == len(values):
            return [str(v) for v in values]

        # NOTE: duplicate variable values — fall back to series names so
        # charts remain readable without silent data collisions.
        return [e.params.name for e in analysed]

    def all_params(self) -> list[SeriesParams]:
        return [entry.params for entry in self._entries]

    def clear_results(self, also_clear_sigma_delta: bool = False) -> None:
        """
        Invalidate all computed results (e.g. after a global param edit).

        Parameters
        ----------
        also_clear_sigma_delta : bool, default False
            When True, also discards the cached σ-δ DataFrame and resets
            sigma_delta_source to "none".  Pass True whenever the user has
            changed simulation parameters so that the next run re-simulates
            from scratch rather than reusing a stale curve.
        """
        for entry in self._entries:
            entry.result = None
            if also_clear_sigma_delta:
                entry.params.sigma_delta_df = None
                entry.params.sigma_delta_source = "none"

    def is_empty(self) -> bool:
        return len(self._entries) == 0
