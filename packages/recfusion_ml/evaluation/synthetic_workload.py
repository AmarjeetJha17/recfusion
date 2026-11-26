"""Bounded synthetic evaluation workloads and aggregate-only profiling."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
import tracemalloc
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from recfusion_ml.evaluation.metrics import (
    RankingEvaluation,
    ValidationCohort,
    build_validation_cohort,
    evaluate_rankings,
)
from recfusion_ml.types import RatingEvent

SCHEMA_VERSION = "recfusion.synthetic-evaluation.v1"
WORKLOAD_VERSION = "sparse-ranking-workload.v1"
DEFAULT_SEED = 51_001
DEFAULT_KS = (5, 10, 20)
_PROFILE_SIZES = {
    "small": (20, 100),
    "medium": (200, 5_000),
    "large": (1_000, 25_000),
}


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    profile: str
    user_count: int
    candidate_count: int
    seed: int
    batch_size: int
    source_depth: int
    ks: tuple[int, ...]
    max_k: int
    max_users: int
    max_candidates: int
    max_generated_records: int
    max_batch_size: int
    max_source_depth: int
    max_evaluation_cutoffs: int
    max_intermediate_batch_records: int
    max_report_bytes: int


@dataclass(frozen=True, slots=True)
class SyntheticWorkload:
    config: WorkloadConfig
    cohort: ValidationCohort
    candidate_items: frozenset[str]
    rankings: Mapping[str, tuple[str, ...]]
    input_counts: Mapping[str, int]
    output_counts: Mapping[str, int]
    workload_sha256: str
    output_sha256: str
    training_events_sha256: str
    validation_events_sha256: str


def get_workload_config(
    profile: str,
    *,
    seed: int = DEFAULT_SEED,
    allow_large: bool = False,
    max_users: int = 1_000,
    max_candidates: int = 25_000,
    max_generated_records: int = 100_000,
    batch_size: int = 64,
    max_batch_size: int = 500,
    source_depth: int = 20,
    max_source_depth: int = 100,
    ks: tuple[int, ...] = DEFAULT_KS,
    max_evaluation_cutoffs: int = 3,
    max_k: int = 20,
    max_intermediate_batch_records: int = 10_000,
    max_report_bytes: int = 1_000_000,
) -> WorkloadConfig:
    """Resolve a named profile and reject resource bounds before generation."""
    if profile not in _PROFILE_SIZES:
        raise ValueError(f"Unknown workload profile: {profile}.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if profile == "large" and not allow_large:
        raise ValueError("The large workload requires explicit opt-in.")
    user_count, candidate_count = _PROFILE_SIZES[profile]
    integer_limits = {
        "max_users": max_users,
        "max_candidates": max_candidates,
        "max_generated_records": max_generated_records,
        "batch_size": batch_size,
        "max_batch_size": max_batch_size,
        "source_depth": source_depth,
        "max_source_depth": max_source_depth,
        "max_evaluation_cutoffs": max_evaluation_cutoffs,
        "max_k": max_k,
        "max_intermediate_batch_records": max_intermediate_batch_records,
        "max_report_bytes": max_report_bytes,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in integer_limits.values()
    ):
        raise ValueError("Workload limits must be positive integers.")
    if (
        not ks
        or len(ks) > max_evaluation_cutoffs
        or any(
            isinstance(k, bool) or not isinstance(k, int) or k <= 0 or k > max_k
            for k in ks
        )
        or len(set(ks)) != len(ks)
    ):
        raise ValueError(
            "Evaluation cutoffs must be unique positive integers within max_k."
        )
    if max(ks) > max_source_depth:
        raise ValueError(
            "max_source_depth must be at least the largest evaluation cutoff."
        )
    if user_count > max_users:
        raise ValueError("Workload exceeds max_users.")
    if candidate_count > max_candidates:
        raise ValueError("Workload exceeds max_candidates.")
    if batch_size > max_batch_size:
        raise ValueError("Workload exceeds max_batch_size.")
    if batch_size * (source_depth + 2) > max_intermediate_batch_records:
        raise ValueError("Workload exceeds max_intermediate_batch_records.")
    if source_depth > max_source_depth or source_depth < max(ks):
        raise ValueError("source_depth must cover K and remain within its bound.")
    if candidate_count <= source_depth:
        raise ValueError("candidate_count must exceed source_depth.")
    cold_positive_count = max(1, user_count // 5)
    if (
        batch_size * (source_depth + 2) + cold_positive_count
        > max_intermediate_batch_records
    ):
        raise ValueError("Workload exceeds max_intermediate_batch_records.")
    generated_records = candidate_count + 2 * user_count + cold_positive_count
    if generated_records > max_generated_records:
        raise ValueError("Workload exceeds max_generated_records.")
    return WorkloadConfig(
        profile=profile,
        user_count=user_count,
        candidate_count=candidate_count,
        seed=seed,
        batch_size=batch_size,
        source_depth=source_depth,
        ks=tuple(ks),
        max_k=max_k,
        max_users=max_users,
        max_candidates=max_candidates,
        max_generated_records=max_generated_records,
        max_batch_size=max_batch_size,
        max_source_depth=max_source_depth,
        max_evaluation_cutoffs=max_evaluation_cutoffs,
        max_intermediate_batch_records=max_intermediate_batch_records,
        max_report_bytes=max_report_bytes,
    )


def build_synthetic_workload(config: WorkloadConfig) -> SyntheticWorkload:
    """Build a sparse, deterministic workload without a dense score matrix."""
    # Revalidate in case a caller constructed WorkloadConfig directly.
    checked = get_workload_config(
        config.profile,
        seed=config.seed,
        allow_large=config.profile == "large",
        max_users=config.max_users,
        max_candidates=config.max_candidates,
        max_generated_records=config.max_generated_records,
        batch_size=config.batch_size,
        max_batch_size=config.max_batch_size,
        source_depth=config.source_depth,
        max_source_depth=config.max_source_depth,
        ks=config.ks,
        max_evaluation_cutoffs=config.max_evaluation_cutoffs,
        max_k=config.max_k,
        max_intermediate_batch_records=config.max_intermediate_batch_records,
        max_report_bytes=config.max_report_bytes,
    )
    if config != checked:
        raise ValueError("WorkloadConfig does not match its validated profile.")

    users = tuple(f"synthetic-user-{index:05d}" for index in range(config.user_count))
    items = tuple(
        f"synthetic-item-{index:06d}" for index in range(config.candidate_count)
    )
    candidates = frozenset(items)
    training = [
        RatingEvent("catalog-user", item, Decimal("5"), "train") for item in items
    ]
    validation: list[RatingEvent] = []
    cold_items = tuple(
        f"synthetic-cold-item-{index:05d}"
        for index in range(max(1, config.user_count // 5))
    )
    seed_shift = config.seed % (len(items) - 1)
    for start in range(0, len(users), config.batch_size):
        batch_users = users[start : start + config.batch_size]
        training.extend(
            RatingEvent(user, items[0], Decimal("5"), "train") for user in batch_users
        )
        validation.extend(
            RatingEvent(
                user,
                items[
                    (
                        start
                        + offset
                        + seed_shift
                        + (start + offset) % config.source_depth
                        + 1
                    )
                    % (len(items) - 1)
                    + 1
                ],
                Decimal("5"),
                "validation",
            )
            for offset, user in enumerate(batch_users)
        )
    validation.extend(
        RatingEvent(users[index * 5], cold_items[index], Decimal("5"), "validation")
        for index in range(len(cold_items))
    )
    cohort = build_validation_cohort(training, validation, candidates)
    rankings = {
        user: tuple(
            items[(index + offset + seed_shift + 1) % (len(items) - 1) + 1]
            for offset in range(config.source_depth)
        )
        for index, user in enumerate(users)
    }
    input_counts = {
        "train_records": len(training),
        "validation_records": len(validation),
        "candidate_items": len(candidates),
        "evaluable_users": len(cohort.targets_by_user),
        "generated_records_total": len(training) + len(validation),
        "cold_positive_validation_records": len(cold_items),
        "rejected_records": 0,
    }
    output_counts = {
        "recommendation_users": len(rankings),
        "recommendation_rows": sum(
            len(items_for_user) for items_for_user in rankings.values()
        ),
        "eligible_targets": cohort.eligible_positive_target_count,
    }
    recommendation_digest = hashlib.sha256()
    for user in sorted(rankings):
        for item in rankings[user]:
            recommendation_digest.update(f"{user}\t{item}\n".encode())
    training_digest = _hash_events(training)
    validation_digest = _hash_events(validation)
    fingerprint = hashlib.sha256()
    fingerprint.update(
        _canonical_bytes(
            {
                "version": WORKLOAD_VERSION,
                "profile": config.profile,
                "seed": config.seed,
                "input_counts": input_counts,
                "output_counts": output_counts,
                "candidate_sha256": _hash_lines(items),
                "training_events_sha256": training_digest,
                "validation_events_sha256": validation_digest,
                "recommendation_sha256": recommendation_digest.hexdigest(),
            }
        )
    )
    return SyntheticWorkload(
        config=config,
        cohort=cohort,
        candidate_items=candidates,
        rankings=rankings,
        input_counts=input_counts,
        output_counts=output_counts,
        workload_sha256=fingerprint.hexdigest(),
        output_sha256=recommendation_digest.hexdigest(),
        training_events_sha256=training_digest,
        validation_events_sha256=validation_digest,
    )


def _process_peak_working_set_bytes() -> dict[str, object]:
    """Return this process' OS peak where the standard library exposes it."""
    operating_system = platform.system()
    if operating_system not in {"Linux", "Darwin"}:
        return {
            "value": None,
            "status": "unavailable",
            "reason": "OS process peak memory API is not supported here",
            "scope": "current process only",
        }
    if importlib.util.find_spec("resource") is None:
        return {
            "value": None,
            "status": "unavailable",
            "reason": "resource.getrusage is not available on this platform",
            "scope": "current process only",
        }
    resource = __import__("resource")
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if operating_system == "Linux":
        value *= 1024
    return {
        "value": value,
        "status": "available",
        "kind": "process_lifetime_peak_rss",
        "scope": "current process lifetime peak; excludes child processes",
    }


def _measure[T](
    function: Callable[[], T],
    *,
    memory_probe: Callable[[], dict[str, object]] | None = None,
) -> tuple[T, dict[str, object]]:
    process_memory = memory_probe or _process_peak_working_set_bytes
    traced_here = not tracemalloc.is_tracing()
    if traced_here:
        tracemalloc.start()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    try:
        result = function()
        wall_seconds = time.perf_counter() - started_wall
        cpu_seconds = time.process_time() - started_cpu
        if cpu_seconds <= 0 or cpu_seconds > wall_seconds + 1e-6:
            cpu_record: dict[str, object] = {
                "value": None,
                "status": "unavailable",
                "reason": ("process-time sample was below zero or exceeded wall time"),
            }
        else:
            cpu_record = {"value": cpu_seconds, "status": "available"}
        if traced_here:
            _, traced_peak = tracemalloc.get_traced_memory()
            traced_record: dict[str, object] = {
                "value": traced_peak,
                "status": "available",
            }
        else:
            traced_record = {
                "value": None,
                "status": "unavailable",
                "reason": (
                    "tracemalloc was already active; caller tracing was left untouched"
                ),
            }
        return result, {
            "wall_time_seconds": wall_seconds,
            "process_time_seconds": cpu_record,
            "python_traced_peak_bytes": traced_record,
            "process_peak_working_set_bytes": process_memory(),
        }
    finally:
        if traced_here and tracemalloc.is_tracing():
            tracemalloc.stop()


def _metric_payload(result: RankingEvaluation) -> dict[str, object]:
    return {
        "evaluated_user_count": result.evaluated_user_count,
        "eligible_positive_target_count": result.eligible_positive_target_count,
        "candidate_pool_item_count": result.candidate_pool_item_count,
        "by_k": {
            str(k): {
                "recall": metrics.recall,
                "ndcg": metrics.ndcg,
                "hit_rate": metrics.hit_rate,
                "mrr": metrics.mrr,
                "candidate_coverage": metrics.candidate_coverage,
                "unique_recommended_items": metrics.unique_recommended_items,
                "recommendation_count": metrics.recommendation_count,
            }
            for k, metrics in sorted(result.metrics_by_k.items())
        },
    }


def run_synthetic_evaluation(
    profile: str = "small",
    *,
    seed: int = DEFAULT_SEED,
    repetitions: int = 3,
    allow_large: bool = False,
    memory_probe: Callable[[], dict[str, object]] | None = None,
) -> dict[str, object]:
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions <= 0
        or repetitions > 10
    ):
        raise ValueError("repetitions must be between 1 and 10.")
    config = get_workload_config(profile, seed=seed, allow_large=allow_large)
    workload = build_synthetic_workload(config)
    metrics: dict[str, object] | None = None
    resource_runs: list[dict[str, object]] = []
    for _ in range(repetitions):
        evaluation, measurement = _measure(
            lambda: evaluate_rankings(
                workload.cohort,
                workload.rankings,
                candidate_items=workload.candidate_items,
                ks=config.ks,
            ),
            memory_probe=memory_probe,
        )
        current_metrics = _metric_payload(evaluation)
        if metrics is not None and current_metrics != metrics:
            raise RuntimeError("Repeated deterministic evaluations disagreed.")
        metrics = current_metrics
        measurement.update(
            {
                "input_counts": dict(workload.input_counts),
                "candidate_pool_size": len(workload.candidate_items),
                "batch_size": config.batch_size,
                "source_depth": config.source_depth,
                "max_k": config.max_k,
                "artifact_bytes": len(_canonical_bytes(_metric_payload(evaluation))),
            }
        )
        resource_runs.append(measurement)
    wall_samples = [
        cast(float, record["wall_time_seconds"]) for record in resource_runs
    ]
    stable_payload = {
        "schema_version": SCHEMA_VERSION,
        "workload_version": WORKLOAD_VERSION,
        "experiment_id": f"synthetic-eval-{profile}-seed-{seed}-v1",
        "profile": profile,
        "seed": seed,
        "config": {
            "users": config.user_count,
            "candidate_items": config.candidate_count,
            "batch_size": config.batch_size,
            "source_depth": config.source_depth,
            "max_k": config.max_k,
            "k_values": list(config.ks),
            "evaluation_contract_version": "warm-start-ranking.v1",
            "candidate_policy": (
                "exact train-known pool; per-user train-seen items excluded"
            ),
            "positive_target_distribution": (
                "one warm unseen positive per train-eligible user; one cold positive "
                "per five users is audited and excluded from the warm-only "
                "candidate pool"
            ),
            "history_length_distribution": {"one interaction": config.user_count},
            "warm_item_count": config.candidate_count,
            "cold_item_count": max(1, config.user_count // 5),
        },
        "input_counts": dict(workload.input_counts),
        "output_counts": dict(workload.output_counts),
        "cohort_audit": {
            "validation_user_count": workload.cohort.validation_user_count,
            "positive_observation_count": (workload.cohort.positive_observation_count),
            "positive_target_pair_count": workload.cohort.positive_target_pair_count,
            "eligible_positive_target_count": (
                workload.cohort.eligible_positive_target_count
            ),
            "cold_item_positive_observation_count": (
                workload.cohort.cold_item_positive_observation_count
            ),
            "cold_user_positive_observation_count": (
                workload.cohort.cold_user_positive_observation_count
            ),
            "seen_positive_observation_count": (
                workload.cohort.seen_positive_observation_count
            ),
            "duplicate_positive_observation_count": (
                workload.cohort.duplicate_positive_observation_count
            ),
            "excluded_target_counts": dict(workload.cohort.excluded_target_counts),
        },
        "workload_sha256": workload.workload_sha256,
        "training_events_sha256": workload.training_events_sha256,
        "validation_events_sha256": workload.validation_events_sha256,
        "output_sha256": workload.output_sha256,
        "evaluation_code_sha256": _evaluation_code_sha256(),
        "synthetic_only": True,
        "rating_distribution": {"5": workload.input_counts["generated_records_total"]},
        "timestamp_range": None,
        "metadata_availability": "unavailable; no product metadata generated",
        "measurement_methods": {
            "wall_time": "time.perf_counter (monotonic)",
            "process_time": (
                "time.process_time; sub-resolution samples reported unavailable"
            ),
            "process_time_clock_resolution_seconds": time.get_clock_info(
                "process_time"
            ).resolution,
            "python_allocations": "tracemalloc peak; Python allocations only",
            "process_memory": (
                "OS process lifetime peak RSS when resource.getrusage is available"
            ),
            "process_memory_scope": (
                "current process lifetime peak only; child processes excluded"
            ),
        },
        "metrics": metrics,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "recfusion_version": _package_version("recfusion"),
            "packages": {
                name: _package_version(name)
                for name in ("numpy", "scipy", "scikit-learn", "torch")
            },
            "git_revision": _git_revision(),
            "git_worktree_dirty": _git_worktree_dirty(),
        },
    }
    process_samples = [
        cast(float, cast(dict[str, object], record["process_time_seconds"])["value"])
        for record in resource_runs
        if cast(dict[str, object], record["process_time_seconds"])["value"] is not None
    ]
    traced_samples = [
        cast(int, cast(dict[str, object], record["python_traced_peak_bytes"])["value"])
        for record in resource_runs
        if cast(dict[str, object], record["python_traced_peak_bytes"])["value"]
        is not None
    ]
    return {
        **stable_payload,
        "stable_sha256": hashlib.sha256(_canonical_bytes(stable_payload)).hexdigest(),
        "resources": resource_runs,
        "resource_summary": {
            "wall_time_seconds_mean": statistics.fmean(wall_samples),
            "wall_time_seconds_population_stdev": statistics.pstdev(wall_samples),
            "process_time_seconds_mean": (
                statistics.fmean(process_samples) if process_samples else None
            ),
            "process_time_seconds_population_stdev": (
                statistics.pstdev(process_samples) if process_samples else None
            ),
            "python_traced_peak_bytes_mean": (
                statistics.fmean(traced_samples) if traced_samples else None
            ),
            "python_traced_peak_bytes_population_stdev": (
                statistics.pstdev(traced_samples) if traced_samples else None
            ),
            "repetitions": repetitions,
            "process_scope": "current process only; child processes are not measured",
        },
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_revision() -> str | None:
    repository_root = Path(__file__).resolve().parents[3]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _git_worktree_dirty() -> bool | None:
    repository_root = Path(__file__).resolve().parents[3]
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def _evaluation_code_sha256() -> str:
    metrics_path = Path(__file__).with_name("metrics.py")
    digest = hashlib.sha256()
    for source_path in (Path(__file__), metrics_path):
        digest.update(source_path.name.encode())
        digest.update(source_path.read_bytes())
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _hash_lines(values: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _hash_events(events: list[RatingEvent]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(
            f"{event.split}\t{event.user_key}\t{event.item_key}\t{event.rating}\n".encode()
        )
    return digest.hexdigest()


def publish_report(
    report: Mapping[str, object],
    target: Path,
    *,
    max_report_bytes: int = 1_000_000,
    temp_dir: Path | None = None,
) -> Path:
    """Atomically publish a bounded JSON report without replacing an existing run."""
    if (
        isinstance(max_report_bytes, bool)
        or not isinstance(max_report_bytes, int)
        or max_report_bytes <= 0
    ):
        raise ValueError("max_report_bytes must be positive.")
    if not target.parent.is_dir():
        raise ValueError("Report parent directory must already exist.")
    temporary_directory = target.parent if temp_dir is None else temp_dir
    if not temporary_directory.is_dir():
        raise ValueError("Temporary directory must already exist.")
    if os.stat(temporary_directory).st_dev != os.stat(target.parent).st_dev:
        raise ValueError("Temporary and output directories must share a filesystem.")
    payload = _canonical_bytes(dict(report)) + b"\n"
    if len(payload) > max_report_bytes:
        raise ValueError("Serialized report exceeds max_report_bytes.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".recfusion-report-", suffix=".tmp", dir=temporary_directory
    )
    claimed_target = False
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            target_descriptor = os.open(
                target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            raise
        else:
            os.close(target_descriptor)
            claimed_target = True
        os.replace(temporary_name, target)
        claimed_target = False
        return target
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        if claimed_target and target.exists():
            target.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(_PROFILE_SIZES), default="small")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temp-dir", type=Path)
    args = parser.parse_args()
    report = run_synthetic_evaluation(
        args.profile,
        seed=args.seed,
        repetitions=args.repetitions,
        allow_large=args.allow_large,
    )
    report["artifact_path"] = args.output.as_posix()
    publish_report(report, args.output, temp_dir=args.temp_dir)
    output_sha256 = hashlib.sha256(args.output.read_bytes()).hexdigest()
    report_bytes = args.output.stat().st_size
    print(
        json.dumps(
            {
                "output": str(args.output),
                "stable_sha256": report["stable_sha256"],
                "output_sha256": output_sha256,
                "report_bytes": report_bytes,
                "profile": report["profile"],
                "input_counts": report["input_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
