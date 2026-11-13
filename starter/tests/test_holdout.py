"""Guard tests use fixtures only; they never query the held-out benchmark."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.holdout import validate_frozen_selection

class HoldoutGuardTests(unittest.TestCase):
    def setUp(self):
        self.hashes = {
            "dev_metrics_sha256": "metric-hash",
            "dev_traces_sha256": "trace-hash",
            "coherence_positions_sha256": "position-hash"
        }
        self.inputs = {"questions": "question-hash", "strategies": "config-hash"}
        self.selection = {
            "selected_strategy": "B", "selected_on_split": "dev",
            "test_results_used_for_selection": False,
            "input_fingerprints": dict(self.inputs), **self.hashes
        }

    def test_valid_selection_is_preserved(self):
        self.assertEqual(validate_frozen_selection(self.selection, self.inputs, self.hashes), "B")

    def test_changed_question_or_config_cannot_use_old_freeze(self):
        current = {**self.inputs, "questions": "changed"}
        with self.assertRaisesRegex(ValueError, "changed"):
            validate_frozen_selection(self.selection, current, self.hashes)

    def test_changed_dev_result_cannot_use_old_freeze(self):
        hashes = {**self.hashes, "dev_metrics_sha256": "changed"}
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            validate_frozen_selection(self.selection, self.inputs, hashes)

    def test_invalidated_encoding_run_cannot_be_used(self):
        self.selection["dev_rerun_required"] = True
        with self.assertRaisesRegex(ValueError, "invalidated"):
            validate_frozen_selection(self.selection, self.inputs, self.hashes)

    def test_test_based_selection_is_rejected(self):
        self.selection["test_results_used_for_selection"] = True
        with self.assertRaisesRegex(ValueError, "exclusively on dev"):
            validate_frozen_selection(self.selection, self.inputs, self.hashes)

if __name__ == "__main__":
    unittest.main()
