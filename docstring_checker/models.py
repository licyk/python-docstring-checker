"""Shared data models for docstring checker diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, order=True)
class Issue:
    """A single docstring checker diagnostic."""

    file: str
    line: int
    code: str
    object: str
    message: str
    confidence: str = "high"

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-serializable representation."""
        return asdict(self)
