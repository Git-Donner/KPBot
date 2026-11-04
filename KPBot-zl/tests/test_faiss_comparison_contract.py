"""Check the comparison helper shipped with the Faiss skill bundle."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "Plugins/code-optimizer/skills/vector-experiment-methodology/scripts/compare_results.py"
SPEC = importlib.util.spec_from_file_location("faiss_result_comparison", SCRIPT)
COMPARISON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARISON)


def fixture():
    return {"performance_field": "qps", "correctness_fields": ["recall"], "datasets": {
        "fixture": {"baseline": [{"qps": 10, "recall": 0.9}],
                    "candidate": [{"qps": 20, "recall": 0.9}]}}}


class FaissComparisonContractTests(unittest.TestCase):
    def test_dispersion_retains_outliers_and_uses_unscaled_mad(self):
        data = fixture()
        data["datasets"]["fixture"]["baseline"] = [
            {"qps": x, "recall": 0.9} for x in (10, 12, 14, 1000, 16)]
        result = COMPARISON.compare(data)["datasets"]["fixture"]
        self.assertEqual(result["baseline_median"], 14)
        self.assertEqual(result["baseline_samples"], 5)
        self.assertEqual(result["baseline_statistics"], {
            "min": 10, "max": 1000, "mad": 2,
            "sample_count_below_three": False})

    def test_small_samples_are_marked_without_claiming_significance(self):
        for values, median, mad in (([10], 10, 0), ([10, 14], 12, 2),
                                    ([10, 10, 10], 10, 0)):
            with self.subTest(values=values):
                data = fixture()
                data["datasets"]["fixture"]["candidate"] = [{"qps": x} for x in values]
                result = COMPARISON.compare(data)["datasets"]["fixture"]
                self.assertEqual(result["candidate_median"], median)
                self.assertEqual(result["candidate_statistics"]["mad"], mad)
                self.assertEqual(result["candidate_statistics"]["sample_count_below_three"], len(values) < 3)

    def test_nonpositive_sample_cannot_hide_behind_positive_median(self):
        for value in (0, -1):
            data = fixture()
            data["datasets"]["fixture"]["baseline"] = [{"qps": x} for x in (value, 10, 20)]
            with self.assertRaises(ValueError):
                COMPARISON.compare(data)

    def test_zero_correctness_is_still_valid(self):
        data = fixture()
        for side in ("baseline", "candidate"):
            data["datasets"]["fixture"][side][0]["recall"] = 0
        result = COMPARISON.compare(data)["datasets"]["fixture"]
        self.assertTrue(result["correctness"]["recall"]["available"])

    def test_latency_speedup_keeps_existing_percentage_semantics(self):
        data = fixture()
        data["higher_is_better"] = False
        data["datasets"]["fixture"]["baseline"][0]["qps"] = 20
        data["datasets"]["fixture"]["candidate"][0]["qps"] = 10
        result = COMPARISON.compare(data)["datasets"]["fixture"]
        self.assertEqual(result["speedup"], 2)
        self.assertEqual(result["improvement_percent"], 100)

    def test_cli_emits_statistics_for_valid_data(self):
        with tempfile.TemporaryDirectory(prefix="faiss-compare-") as folder:
            source = Path(folder) / "input.json"
            output = Path(folder) / "output.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--output", str(output)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["datasets"]["fixture"]["candidate_statistics"]["mad"], 0)

    def test_throughput_and_latency_keep_the_declared_direction(self):
        result = COMPARISON.compare(fixture())
        self.assertEqual(result["geomean_speedup"], 2)
        data = fixture()
        data["higher_is_better"] = False
        self.assertEqual(COMPARISON.compare(data)["geomean_speedup"], 0.5)

    def test_boolean_or_nonfinite_performance_is_rejected(self):
        for value in (True, False, None, "20", float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                data = fixture()
                data["datasets"]["fixture"]["candidate"][0]["qps"] = value
                with self.assertRaises(ValueError):
                    COMPARISON.compare(data)

    def test_a_missing_sample_is_not_silently_omitted(self):
        data = fixture()
        data["datasets"]["fixture"]["candidate"].append({"recall": 0.9})
        with self.assertRaises(ValueError):
            COMPARISON.compare(data)

    def test_incomplete_correctness_is_reported_unavailable(self):
        data = fixture()
        data["datasets"]["fixture"]["candidate"].append({"qps": 20})
        result = COMPARISON.compare(data)
        self.assertEqual(result["datasets"]["fixture"]["correctness"]["recall"], {"available": False})

    def test_nonpositive_medians_are_rejected(self):
        for value in (0, -1):
            data = fixture()
            data["datasets"]["fixture"]["candidate"][0]["qps"] = value
            with self.assertRaises(ValueError):
                COMPARISON.compare(data)

    def test_overflow_cannot_be_reported_as_a_speedup(self):
        data = fixture()
        data["datasets"]["fixture"]["baseline"][0]["qps"] = 1e-300
        data["datasets"]["fixture"]["candidate"][0]["qps"] = 1e300
        with self.assertRaises(ValueError):
            COMPARISON.compare(data)

    def test_cli_rejects_invalid_data_without_a_report_or_traceback(self):
        invalid = fixture()
        invalid["datasets"]["fixture"]["candidate"][0]["qps"] = float("nan")
        overflow = fixture()
        overflow["datasets"]["fixture"]["baseline"][0]["qps"] = 1
        overflow["datasets"]["fixture"]["candidate"][0]["qps"] = 1e308
        for data in ([], invalid, overflow):
            with self.subTest(data=data), tempfile.TemporaryDirectory(prefix="faiss-compare-") as folder:
                source = Path(folder) / "input.json"
                output = Path(folder) / "output.json"
                source.write_text(json.dumps(data), encoding="utf-8")
                result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--output", str(output)],
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
