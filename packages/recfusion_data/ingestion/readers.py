"""Streaming readers that parse files without applying domain schemas."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from recfusion_data.ingestion.errors import SourceReadError


class InputFormat(StrEnum):
    JSONL = "jsonl"
    CSV = "csv"


@dataclass(frozen=True, slots=True)
class SourceRow:
    row_number: int
    values: Mapping[str, object] | None
    error_code: str | None = None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def read_jsonl(path: Path) -> Iterator[SourceRow]:
    try:
        source = path.open("rb")
    except OSError as error:
        raise SourceReadError("Cannot open JSONL source file.") from error

    with source:
        for row_number, raw_line in enumerate(source, start=1):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                yield SourceRow(row_number, None, "invalid_utf8")
                continue
            if not line.strip():
                yield SourceRow(row_number, None, "empty_record")
                continue
            try:
                value = json.loads(line, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError):
                yield SourceRow(row_number, None, "malformed_json")
                continue
            if not isinstance(value, dict):
                yield SourceRow(row_number, None, "record_not_object")
                continue
            yield SourceRow(row_number, value)


def read_csv(
    path: Path, *, expected_headers: tuple[str, ...] | None = None
) -> Iterator[SourceRow]:
    try:
        source = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise SourceReadError("Cannot open CSV source file.") from error

    with source:
        reader = csv.reader(source, strict=True)
        try:
            headers = next(reader, None)
        except csv.Error as error:
            raise SourceReadError("Cannot parse CSV header.") from error
        except UnicodeDecodeError as error:
            raise SourceReadError("CSV source is not valid UTF-8.") from error
        if headers is None or not headers:
            raise SourceReadError("CSV source has no header.")
        if any(not header.strip() for header in headers) or len(set(headers)) != len(
            headers
        ):
            raise SourceReadError("CSV header contains blank or duplicate names.")
        if expected_headers is not None and set(headers) != set(expected_headers):
            raise SourceReadError("CSV header does not match the selected adapter.")

        while True:
            try:
                values = next(reader)
            except StopIteration:
                break
            except csv.Error:
                yield SourceRow(reader.line_num, None, "malformed_csv")
                continue
            except UnicodeDecodeError as error:
                raise SourceReadError("CSV source is not valid UTF-8.") from error

            if len(values) != len(headers):
                yield SourceRow(reader.line_num, None, "malformed_csv_row")
                continue
            yield SourceRow(reader.line_num, dict(zip(headers, values, strict=True)))


def read_records(
    path: Path,
    input_format: InputFormat,
    *,
    expected_csv_headers: tuple[str, ...] | None = None,
) -> Iterator[SourceRow]:
    if input_format is InputFormat.JSONL:
        yield from read_jsonl(path)
    elif input_format is InputFormat.CSV:
        yield from read_csv(path, expected_headers=expected_csv_headers)
    else:
        raise SourceReadError("Unsupported input format.")
