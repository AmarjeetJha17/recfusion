"""Safe, structured ingestion errors."""

from __future__ import annotations

from dataclasses import dataclass


class IngestionError(Exception):
    """Fatal error that prevents publishing an ingestion output."""


class SourceReadError(IngestionError):
    """Source file or format could not be read."""


class AdapterError(Exception):
    """A source adapter could not map a row to the canonical shape."""

    def __init__(self, code: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str | None = None


class RecordValidationError(Exception):
    """One record failed one or more canonical contract checks."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__(",".join(issue.code for issue in issues))
