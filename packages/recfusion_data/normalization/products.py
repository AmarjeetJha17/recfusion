"""Conservative product metadata and electronics specification normalization."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from recfusion_core.contracts import JSONValue, ProductMetadata


class NormalizationStatus(StrEnum):
    NORMALIZED = "normalized"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class NormalizedField:
    raw_values: tuple[JSONValue, ...]
    value: JSONValue
    unit: str | None
    status: NormalizationStatus
    source_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedProductMetadata:
    product: ProductMetadata
    brand: NormalizedField
    category: NormalizedField
    specifications: Mapping[str, NormalizedField]
    price: NormalizedField

    def as_record(
        self,
        product_record: Mapping[str, object],
        *,
        conflict_retained: bool | None,
    ) -> dict[str, object]:
        return {
            "product": dict(product_record),
            "normalization": {
                "schema_version": "recfusion.product-normalization.v1",
                "brand": _field_record(self.brand),
                "category": _field_record(self.category),
                "specifications": {
                    name: _field_record(value)
                    for name, value in sorted(self.specifications.items())
                },
                "price": _field_record(self.price),
                "product_decision": (
                    "conflict_retained"
                    if conflict_retained is True
                    else "unique_retained"
                    if conflict_retained is False
                    else "pending_conflict_check"
                ),
                "source_record_fingerprint": self.product.source_record_fingerprint,
            },
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    raw: JSONValue


@dataclass(frozen=True, slots=True)
class _ParsedValue:
    value: JSONValue
    unit: str | None
    status: NormalizationStatus


_NUMBER_UNIT = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z]+|[\"″])(?:\s+(.*?))?\s*$"
)
_KEY_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)
_MEMORY_UNITS: dict[str, Decimal] = {
    "mb": Decimal(1_000_000),
    "mib": Decimal(1_048_576),
    "gb": Decimal(1_000_000_000),
    "gib": Decimal(1_073_741_824),
    "tb": Decimal(1_000_000_000_000),
    "tib": Decimal(1_099_511_627_776),
}
_STORAGE_TYPES = {
    "ssd": "ssd",
    "solid state drive": "ssd",
    "hdd": "hdd",
    "hard disk drive": "hdd",
    "nvme": "nvme",
    "nvme ssd": "nvme ssd",
    "emmc": "emmc",
    "ufs": "ufs",
}
_SPECS: dict[str, frozenset[str]] = {
    "ram_capacity_bytes": frozenset({"ram", "ram capacity", "system memory"}),
    "storage_capacity_bytes": frozenset(
        {"storage", "storage capacity", "internal storage"}
    ),
    "storage_type": frozenset({"storage type", "drive type"}),
    "display_size_mm": frozenset({"display size", "screen size", "display"}),
    "weight_g": frozenset({"weight", "item weight", "product weight"}),
    "battery_capacity": frozenset({"battery capacity", "battery"}),
    "processor_name": frozenset({"processor", "processor model", "cpu"}),
    "gpu_name": frozenset({"gpu", "graphics processor", "graphics"}),
}
_RAM_BOUNDS = (1_048_576, 4_398_046_511_104)
_STORAGE_BOUNDS = (1_000_000, 100_000_000_000_000)
_DISPLAY_BOUNDS = (Decimal("25"), Decimal("3000"))
_WEIGHT_BOUNDS = (Decimal("1"), Decimal("100000"))
_BATTERY_CHARGE_BOUNDS = (Decimal("1"), Decimal("1000000"))
_BATTERY_ENERGY_BOUNDS = (Decimal("0.001"), Decimal("10000"))
_DISPLAY_UNITS = frozenset(
    {
        "in",
        "inch",
        "inches",
        '"',
        "″",
        "cm",
        "centimeter",
        "centimeters",
        "mm",
        "millimeter",
        "millimeters",
    }
)
_WEIGHT_UNITS = frozenset({"g", "gram", "grams", "kg", "kilogram", "kilograms"})
_BATTERY_UNITS = frozenset(
    {
        "mah",
        "milliamperehours",
        "ah",
        "amperehours",
        "wh",
        "watthours",
        "mwh",
        "milliwatthours",
    }
)


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(_KEY_SEPARATORS.sub(" ", normalized).split())


def _raw_order(value: JSONValue) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _candidates(
    attributes: Mapping[str, JSONValue], aliases: frozenset[str]
) -> tuple[_Candidate, ...]:
    matches = [
        _Candidate(key, value)
        for key, value in attributes.items()
        if _key(key) in aliases
    ]
    return tuple(
        sorted(matches, key=lambda item: (item.key.casefold(), _raw_order(item.raw)))
    )


def _missing() -> _ParsedValue:
    return _ParsedValue(None, None, NormalizationStatus.MISSING)


def _is_missing_input(value: JSONValue) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _invalid(status: NormalizationStatus) -> _ParsedValue:
    return _ParsedValue(None, None, status)


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _numeric_unit(value: JSONValue) -> tuple[Decimal, str, str] | None:
    if not isinstance(value, str):
        return None
    match = _NUMBER_UNIT.fullmatch(value)
    if match is None:
        return None
    number = _decimal(match.group(1))
    if number is None:
        return None
    unit = match.group(2).casefold()
    suffix = " ".join((match.group(3) or "").casefold().split())
    return number, unit, suffix


def _numeric_parse_failure(
    value: JSONValue, known_units: Iterable[str]
) -> NormalizationStatus:
    if not isinstance(value, str):
        return NormalizationStatus.UNSUPPORTED
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if any(
        re.search(rf"(?<![a-z]){re.escape(unit)}(?![a-z])", normalized)
        for unit in known_units
    ):
        return NormalizationStatus.INVALID
    return NormalizationStatus.UNSUPPORTED


def _integer_bytes(number: Decimal, unit: str) -> _ParsedValue:
    factor = _MEMORY_UNITS.get(unit)
    if factor is None:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    if number <= 0:
        return _invalid(NormalizationStatus.INVALID)
    amount = number * factor
    if amount != amount.to_integral_value():
        return _invalid(NormalizationStatus.INVALID)
    normalized = int(amount)
    low, high = _RAM_BOUNDS
    if not low <= normalized <= high:
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(normalized, "B", NormalizationStatus.NORMALIZED)


def _parse_ram(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    parsed = _numeric_unit(value)
    if parsed is None:
        return _invalid(_numeric_parse_failure(value, _MEMORY_UNITS))
    number, unit, suffix = parsed
    if suffix:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    return _integer_bytes(number, unit)


def _parse_storage_capacity(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    parsed = _numeric_unit(value)
    if parsed is None:
        return _invalid(_numeric_parse_failure(value, _MEMORY_UNITS))
    number, unit, suffix = parsed
    storage_type = _STORAGE_TYPES.get(suffix) if suffix else None
    if suffix and storage_type is None:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    factor = _MEMORY_UNITS.get(unit)
    if factor is None:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    if number <= 0:
        return _invalid(NormalizationStatus.INVALID)
    amount = number * factor
    if amount != amount.to_integral_value():
        return _invalid(NormalizationStatus.INVALID)
    normalized = int(amount)
    low, high = _STORAGE_BOUNDS
    if not low <= normalized <= high:
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(normalized, "B", NormalizationStatus.NORMALIZED)


def _parse_storage_type(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    if not isinstance(value, str):
        return _invalid(NormalizationStatus.UNSUPPORTED)
    parsed = _numeric_unit(value)
    if parsed is not None:
        normalized = parsed[2]
        if not normalized:
            return _missing()
    else:
        normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized:
        return _missing()
    storage_type = _STORAGE_TYPES.get(normalized)
    if storage_type is None:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    return _ParsedValue(storage_type, None, NormalizationStatus.NORMALIZED)


def _parse_display(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    parsed = _numeric_unit(value)
    if parsed is None:
        return _invalid(_numeric_parse_failure(value, _DISPLAY_UNITS))
    number, unit, suffix = parsed
    if suffix:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    if unit in {"in", "inch", "inches", '"', "″"}:
        millimeters = number * Decimal("25.4")
    elif unit in {"cm", "centimeter", "centimeters"}:
        millimeters = number * Decimal("10")
    elif unit in {"mm", "millimeter", "millimeters"}:
        millimeters = number
    else:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    low, high = _DISPLAY_BOUNDS
    if not low <= millimeters <= high:
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(
        format(millimeters.normalize(), "f"), "mm", NormalizationStatus.NORMALIZED
    )


def _parse_weight(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    parsed = _numeric_unit(value)
    if parsed is None:
        return _invalid(_numeric_parse_failure(value, _WEIGHT_UNITS))
    number, unit, suffix = parsed
    if suffix:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    if unit in {"g", "gram", "grams"}:
        grams = number
    elif unit in {"kg", "kilogram", "kilograms"}:
        grams = number * Decimal("1000")
    else:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    low, high = _WEIGHT_BOUNDS
    if not low <= grams <= high:
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(
        format(grams.normalize(), "f"), "g", NormalizationStatus.NORMALIZED
    )


def _parse_battery(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    parsed = _numeric_unit(value)
    if parsed is None:
        return _invalid(_numeric_parse_failure(value, _BATTERY_UNITS))
    number, unit, suffix = parsed
    if suffix:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    if unit in {"mah", "milliamperehours"}:
        amount = number
        normalized_unit = "mAh"
    elif unit in {"ah", "amperehours"}:
        amount = number * Decimal("1000")
        normalized_unit = "mAh"
    elif unit in {"wh", "watthours"}:
        amount = number
        normalized_unit = "Wh"
    elif unit in {"mwh", "milliwatthours"}:
        amount = number / Decimal("1000")
        normalized_unit = "Wh"
    else:
        return _invalid(NormalizationStatus.UNSUPPORTED)
    low, high = (
        _BATTERY_CHARGE_BOUNDS if normalized_unit == "mAh" else _BATTERY_ENERGY_BOUNDS
    )
    if not low <= amount <= high:
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(
        format(amount.normalize(), "f"),
        normalized_unit,
        NormalizationStatus.NORMALIZED,
    )


def _parse_text(value: JSONValue) -> _ParsedValue:
    if _is_missing_input(value):
        return _missing()
    if not isinstance(value, str):
        return _invalid(NormalizationStatus.UNSUPPORTED)
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized:
        return _missing()
    return _ParsedValue(normalized, None, NormalizationStatus.NORMALIZED)


def _parse_normalized_text(value: JSONValue) -> _ParsedValue:
    parsed = _parse_text(value)
    if parsed.status is not NormalizationStatus.NORMALIZED:
        return parsed
    if not isinstance(parsed.value, str):
        return _invalid(NormalizationStatus.INVALID)
    return _ParsedValue(parsed.value.casefold(), None, parsed.status)


def _resolve(
    candidates: tuple[_Candidate, ...],
    parser: Callable[[JSONValue], _ParsedValue],
) -> NormalizedField:
    if not candidates:
        return NormalizedField((), None, None, NormalizationStatus.MISSING, ())
    parsed_values: list[_ParsedValue] = []
    for candidate in candidates:
        parsed_values.append(parser(candidate.raw))

    informative = [
        item for item in parsed_values if item.status is not NormalizationStatus.MISSING
    ]
    if not informative:
        status = NormalizationStatus.MISSING
        normalized_value = None
        unit = None
    elif len(informative) > 1:
        semantic_values = {
            (item.status, _raw_order(item.value), item.unit) for item in informative
        }
        if len(semantic_values) > 1:
            status = NormalizationStatus.AMBIGUOUS
            normalized_value = None
            unit = None
        else:
            status = informative[0].status
            normalized_value = informative[0].value
            unit = informative[0].unit
    else:
        status = informative[0].status
        normalized_value = informative[0].value
        unit = informative[0].unit

    return NormalizedField(
        raw_values=tuple(candidate.raw for candidate in candidates),
        value=normalized_value,
        unit=unit,
        status=status,
        source_keys=tuple(candidate.key for candidate in candidates),
    )


def _field_record(field: NormalizedField) -> dict[str, object]:
    return {
        "raw_values": field.raw_values,
        "value": field.value,
        "unit": field.unit,
        "status": field.status.value,
        "source_keys": field.source_keys,
    }


def _field(
    attributes: Mapping[str, JSONValue],
    aliases: frozenset[str],
    parser: Callable[[JSONValue], _ParsedValue],
) -> NormalizedField:
    return _resolve(_candidates(attributes, aliases), parser)


def _storage_type_from_capacity(
    attributes: Mapping[str, JSONValue],
) -> NormalizedField:
    capacities = _candidates(attributes, _SPECS["storage_capacity_bytes"])
    suffix_candidates = [
        candidate
        for candidate in capacities
        if (parsed := _numeric_unit(candidate.raw)) is not None and parsed[2]
    ]
    explicit = _candidates(attributes, _SPECS["storage_type"])
    candidates = tuple(suffix_candidates) + explicit
    candidates = tuple(
        sorted(candidates, key=lambda item: (item.key.casefold(), _raw_order(item.raw)))
    )
    return _resolve(candidates, _parse_storage_type)


def _as_json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_as_json_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _as_json_value(item) for key, item in value.items()}
    raise ValueError("Raw value is not JSON-compatible.")


def _price_field(
    product: ProductMetadata,
    raw_price: object,
    invalid_price: bool,
    raw_price_present: bool | None,
) -> NormalizedField:
    if product.price is not None:
        value: JSONValue = {
            "amount": str(product.price.amount),
            "currency": product.price.currency,
        }
        status = NormalizationStatus.NORMALIZED
    elif invalid_price:
        value = None
        status = NormalizationStatus.INVALID
    else:
        value = None
        status = NormalizationStatus.MISSING
    try:
        raw_value = _as_json_value(raw_price)
    except ValueError:
        raw_value = None
        status = NormalizationStatus.INVALID
        value = None
    present = raw_price is not None if raw_price_present is None else raw_price_present
    source_keys = ("price",) if present else ()
    raw_values = (raw_value,) if present else ()
    return NormalizedField(raw_values, value, None, status, source_keys)


def normalize_product_metadata(
    product: ProductMetadata,
    *,
    raw_price: object = None,
    invalid_price: bool = False,
    raw_price_present: bool | None = None,
) -> NormalizedProductMetadata:
    """Normalize known product fields while retaining raw canonical metadata."""
    brand_candidates = _candidates(
        product.attributes, frozenset({"brand", "brand name"})
    )
    brand = _resolve(brand_candidates, _parse_normalized_text)
    if product.category is None:
        category = NormalizedField((), None, None, NormalizationStatus.MISSING, ())
    else:
        category = _resolve(
            (_Candidate("category", product.category),), _parse_normalized_text
        )

    specifications = {
        "ram_capacity_bytes": _field(
            product.attributes, _SPECS["ram_capacity_bytes"], _parse_ram
        ),
        "storage_capacity_bytes": _field(
            product.attributes,
            _SPECS["storage_capacity_bytes"],
            _parse_storage_capacity,
        ),
        "storage_type": _storage_type_from_capacity(product.attributes),
        "display_size_mm": _field(
            product.attributes, _SPECS["display_size_mm"], _parse_display
        ),
        "weight_g": _field(product.attributes, _SPECS["weight_g"], _parse_weight),
        "battery_capacity": _field(
            product.attributes, _SPECS["battery_capacity"], _parse_battery
        ),
        "processor_name": _field(
            product.attributes, _SPECS["processor_name"], _parse_text
        ),
        "gpu_name": _field(product.attributes, _SPECS["gpu_name"], _parse_text),
    }
    return NormalizedProductMetadata(
        product=product,
        brand=brand,
        category=category,
        specifications=specifications,
        price=_price_field(product, raw_price, invalid_price, raw_price_present),
    )
