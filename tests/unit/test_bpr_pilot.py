import ctypes
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import recfusion_ml.evaluation.bpr_pilot as bpr_pilot
from recfusion_ml.evaluation.bpr_pilot import (
    _METRIC_FIELDS,
    _peak_working_set_bytes,
    _temporal_audit_counts,
    _timestamp_conversion_errors,
    _validate_baseline_reports,
)
from recfusion_ml.evaluation.pilot import TrustedPilotData


def test_temporal_audit_counts_are_read_from_manifest_counts_object() -> None:
    counts = {
        "split_counts": {"train": {"records": 3}},
        "integrity": {"blocking_issue_count": 0},
        "rejected_by_input": {"train": 1},
    }

    assert _temporal_audit_counts({"counts": counts}) == counts


def test_windows_peak_memory_probe_uses_a_typed_process_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ApiFunction:
        argtypes: object = None
        restype: object = None

        def __init__(self, result: int) -> None:
            self.result = result

        def __call__(self, *_args: object) -> int:
            return self.result

    process_info = ApiFunction(0)
    libraries = {
        "Psapi.dll": SimpleNamespace(GetProcessMemoryInfo=process_info),
        "Kernel32.dll": SimpleNamespace(GetCurrentProcess=ApiFunction(1234)),
    }
    monkeypatch.setattr(bpr_pilot.sys, "platform", "win32")
    monkeypatch.setattr(
        bpr_pilot.ctypes,
        "WinDLL",
        lambda name, **_kwargs: libraries[name],
        raising=False,
    )

    assert _peak_working_set_bytes() is None
    assert process_info.argtypes[0] is ctypes.c_void_p
    assert process_info.argtypes[2] is ctypes.c_ulong


def test_timestamp_validation_requires_utc_milliseconds() -> None:
    assert (
        _timestamp_conversion_errors(
            [
                {
                    "interaction": {
                        "event_time_ms": 1_000,
                        "event_time_utc": "1970-01-01T00:00:01Z",
                    }
                }
            ]
        )
        == 0
    )
    assert (
        _timestamp_conversion_errors(
            [
                {
                    "interaction": {
                        "event_time_ms": 1_000,
                        "event_time_utc": "1970-01-01T00:00:02Z",
                    }
                }
            ]
        )
        == 1
    )


def test_baseline_report_validation_rejects_provenance_mismatch(
    tmp_path: Path,
) -> None:
    processed = tmp_path / "data" / "processed"
    temporal_dir = processed / "temporal"
    preprocessing_dir = processed / "preprocessing"
    temporal_dir.mkdir(parents=True)
    preprocessing_dir.mkdir(parents=True)
    temporal_manifest = temporal_dir / "manifest.json"
    preprocessing_manifest = preprocessing_dir / "manifest.json"
    temporal_manifest.write_text("{}", encoding="utf-8")
    preprocessing_manifest.write_text("{}", encoding="utf-8")
    train_hash, validation_hash, test_hash = ("a" * 64, "b" * 64, "c" * 64)
    source = {"source_id": "synthetic", "source_version": "fixture-v1"}
    data = TrustedPilotData(
        preprocessing_dir=preprocessing_dir,
        temporal_dir=temporal_dir,
        preprocessing={},
        temporal={"source": source},
        temporal_outputs={
            "interactions.train.jsonl": {"sha256": train_hash},
            "interactions.validation.jsonl": {"sha256": validation_hash},
            "interactions.test.jsonl": {"sha256": test_hash},
        },
        train_records=[],
        validation_records=[],
        train_events=(),
        validation_events=(),
        candidate_items=frozenset({"a", "b", "c"}),
    )
    popularity_path = processed / "popularity.json"
    item_cf_path = processed / "item-cf.json"
    metric = {
        field: (0.1 if field in {"recall", "ndcg", "hit_rate", "mrr"} else 3)
        for field in _METRIC_FIELDS
    }
    provenance = {
        "temporal_manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
        "train_sha256": train_hash,
        "validation_sha256": validation_hash,
        "test_sha256_verified_without_parsing": test_hash,
    }
    counts = {
        "candidate_pool_items": 3,
        "evaluated_users": 1,
        "eligible_positive_target_pairs": 1,
        "parsed_records": {"train": 0, "validation": 0},
    }
    protocol = {
        "evaluation_split": "validation only",
        "test_rows_parsed_or_evaluated": False,
        "positive_min_rating": "4",
        "ks": [5, 10, 20],
    }
    popularity_path.write_text(
        json.dumps(
            {
                "source": source,
                "protocol": protocol,
                "provenance": {
                    **provenance,
                    "preprocessing_manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
                },
                "counts": counts,
                "metrics": {str(k): metric for k in (5, 10, 20)},
            }
        ),
        encoding="utf-8",
    )
    popularity_hash = hashlib.sha256(popularity_path.read_bytes()).hexdigest()
    item_cf_path.write_text(
        json.dumps(
            {
                "source": source,
                "protocol": {
                    **protocol,
                    "candidate_pool": "exact Step 2.5 train-known item pool",
                    "seen_item_policy": "exclude every train-observed user-item pair",
                },
                "provenance": {
                    **provenance,
                    "popularity_report_sha256": popularity_hash,
                },
                "counts": counts,
                "comparison": {
                    str(k): {"popularity": metric, "item_cf": metric}
                    for k in (5, 10, 20)
                },
            }
        ),
        encoding="utf-8",
    )

    baseline_metrics, _, _ = _validate_baseline_reports(
        data=data,
        cohort_users=1,
        eligible_targets=1,
        popularity_report_path=popularity_path,
        item_cf_report_path=item_cf_path,
        repository_root=tmp_path,
    )
    assert baseline_metrics["10"]["popularity"] == metric

    report = json.loads(item_cf_path.read_text(encoding="utf-8"))
    report["provenance"]["test_sha256_verified_without_parsing"] = "d" * 64
    item_cf_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprints"):
        _validate_baseline_reports(
            data=data,
            cohort_users=1,
            eligible_targets=1,
            popularity_report_path=popularity_path,
            item_cf_report_path=item_cf_path,
            repository_root=tmp_path,
        )
