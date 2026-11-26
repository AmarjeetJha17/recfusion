from __future__ import annotations

import ctypes

import pytest

import recfusion_ml.evaluation.two_tower_pilot as two_tower_pilot


def test_memory_status_returns_unknown_when_windows_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(two_tower_pilot.os, "name", "nt")
    monkeypatch.delattr(ctypes, "windll", raising=False)

    assert two_tower_pilot._memory_status() == {
        "total_bytes": None,
        "available_bytes": None,
    }
