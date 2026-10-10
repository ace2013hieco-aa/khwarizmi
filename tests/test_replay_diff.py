"""FIX-DET-EXPRESS + FIX-HIGH04: differential replay harness + detector
fan-out cap with per-group round-robin fairness.

Wraps scripts/replay_diff.py so the harness runs under the suite.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    DETECTOR_TRUNCATED,
    detect_classification_conflicts,
)

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "replay_diff.py"


@pytest.fixture(scope="module")
def rd():
    spec = importlib.util.spec_from_file_location("replay_diff", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestReplayDiffHarness:
    def test_run_twice_equal_after_declared_strip(self, rd, tmp_path):
        assert rd.run_twice_equal(5, tmp_path) == []

    def test_strip_is_load_bearing(self, rd, tmp_path):
        # Without the declared strip the two runs must differ (the
        # uuid4 correlation_id), proving the strip is what makes them equal.
        raws = []
        for lab in ("a", "b"):
            conn = rd.build_scenario(tmp_path / f"{lab}.db", 3)
            try:
                rd.run_detector(conn)
                raws.append([tuple(r)[0] for r in conn.execute(
                    "SELECT correlation_id FROM events "
                    "WHERE event_type = 'ResearchCreated'")])
            finally:
                conn.close()
        assert raws[0] != raws[1]
        assert rd.PROVENANCE_STRIP == (("events", "correlation_id"),)

    def test_journal_reproduces_derived_state(self, rd, tmp_path):
        assert rd.replay_over_recorded_journal(5, tmp_path) == []

    def test_fan_out_bounded_and_reports_truncation(self, rd, tmp_path):
        failures, info = rd.fan_out_bounded(100, tmp_path)
        assert failures == [], info
        assert info["emitted"] <= rd.FAN_OUT_BOUND
        assert info["truncated"] is not None


class TestPairCap:
    def _rows(self, n):
        return [{"artifact_id": f"fc-{i:03d}", "project_id": "p",
                 "program_ref": "rp", "hypothesis_ref": "h",
                 "failure_class": "A" if i % 2 else "B",
                 "evidence": ["ev1"], "invalidated": False}
                for i in range(n)]

    def test_under_cap_no_diagnostic(self):
        diag: dict = {}
        out = detect_classification_conflicts(
            self._rows(6), diagnostics=diag)
        assert len(out) == 9  # 3 x 3 cross-class pairs
        assert DETECTOR_TRUNCATED not in diag

    def test_over_cap_truncates_with_diagnostic(self):
        diag: dict = {}
        out = detect_classification_conflicts(
            self._rows(100), max_pairs=50, diagnostics=diag)
        assert len(out) == 50
        trunc = diag[DETECTOR_TRUNCATED]
        assert trunc["max_pairs"] == 50
        assert trunc["emitted"] == 50
        # HIGH04: per-group accounting present, never silent.
        assert trunc["groups"] == 1
        assert len(trunc["truncated_groups"]) == 1
        assert list(trunc["per_group"].values())[0]["emitted"] == 50

    def test_cap_is_order_independent(self):
        rows = self._rows(40)
        a = detect_classification_conflicts(rows, max_pairs=30)
        b = detect_classification_conflicts(list(reversed(rows)),
                                            max_pairs=30)
        assert a == b

    def test_rejects_non_positive_cap(self):
        from hermes.research.contradictions import ContradictionError
        with pytest.raises(ContradictionError):
            detect_classification_conflicts(self._rows(4), max_pairs=0)

    def test_detector_version_bumped_for_selection_change(self):
        # v3: pair selection changed to round-robin fairness (v2 was the
        # global sequential cap). Identity (cx_ pair hash) is unchanged.
        assert CONTRADICTION_DETECTOR_VERSION == "cx-detect-v3"


class TestFairness:
    """FIX-HIGH04: per-group budget + round-robin (no silent starvation)."""

    def _grouped(self, sizes: dict[str, int]):
        rows = []
        for hyp, n in sizes.items():
            for i in range(n):
                rows.append({
                    "artifact_id": f"fc-{hyp}-{i:03d}",
                    "project_id": "p", "program_ref": "rp",
                    "hypothesis_ref": hyp,
                    "failure_class": "A" if i % 2 else "B",
                    "evidence": ["ev1"], "invalidated": False})
        return rows

    @staticmethod
    def _dist(out: list[dict]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for c in out:
            # Intra-group pairs: both parties share the middle segment.
            grp = str(c["party_a"]).split("-")[1]
            dist[grp] = dist.get(grp, 0) + 1
        return dist

    def test_round_robin_late_groups_get_pairs(self):
        # h0 is dense (20x20=400 eligible); h1/h2 are small (3x3=9 each).
        # Sequential global cap would starve h1/h2; round-robin must not.
        rows = self._grouped({"h0": 40, "h1": 6, "h2": 6})
        diag: dict = {}
        out = detect_classification_conflicts(
            rows, max_pairs=30, diagnostics=diag)
        assert len(out) == 30
        dist = self._dist(out)
        assert dist.get("h1", 0) > 0
        assert dist.get("h2", 0) > 0
        # Small groups fully emitted (9 each), remainder goes to h0.
        assert dist["h1"] == 9
        assert dist["h2"] == 9
        assert dist["h0"] == 12

    def test_per_group_truncation_recorded(self):
        rows = self._grouped({"h0": 40, "h1": 6, "h2": 6})
        diag: dict = {}
        detect_classification_conflicts(rows, max_pairs=30,
                                        diagnostics=diag)
        trunc = diag[DETECTOR_TRUNCATED]
        assert trunc["max_pairs"] == 30
        assert trunc["emitted"] == 30
        assert trunc["groups"] == 3
        # Only the dense group still has remainder beyond the cap.
        assert trunc["truncated_groups"] == ["p/rp/h0"]
        assert trunc["per_group"]["p/rp/h0"] == {
            "emitted": 12, "truncated": True}
        assert trunc["per_group"]["p/rp/h1"] == {
            "emitted": 9, "truncated": False}

    def test_exact_fit_reports_no_truncation(self):
        # 2 groups x 4 eligible each = 8 eligible == cap: nothing cut,
        # so no TRUNCATED key (peek phase proves remainder, no false +).
        rows = self._grouped({"h0": 4, "h1": 4})
        diag: dict = {}
        out = detect_classification_conflicts(
            rows, max_pairs=8, diagnostics=diag)
        assert len(out) == 8  # 2x2 + 2x2 cross-class pairs
        assert DETECTOR_TRUNCATED not in diag

    def test_multigroup_cap_is_order_independent(self):
        rows = self._grouped({"h0": 20, "h1": 8, "h2": 8})
        a = detect_classification_conflicts(rows, max_pairs=25)
        b = detect_classification_conflicts(list(reversed(rows)),
                                            max_pairs=25)
        assert a == b

    def test_uncapped_multigroup_emits_full_set(self):
        # Under the cap, round-robin emits the same full set as the
        # sequential pass (selection change only bites when capped).
        rows = self._grouped({"h0": 6, "h1": 6})
        out = detect_classification_conflicts(rows, max_pairs=500)
        assert len(out) == 18  # 3x3 + 3x3
