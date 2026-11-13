"""Unit fixtures verify metric semantics; they are not experiment results."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.benchmarking import retrieve_one, select_on_dev
from src.evaluation import evidence_hit, evaluate_query, summarize

def question():
    return {
        "id": "fixture", "split": "dev", "question": "A fixture question",
        "expected_answer": "reference only", "gold_source_id": "source-a",
        "gold_page": 2, "evidence_quote": "the complete evidence", "filter": {"module": 1}
    }

def hit(source="source-a", page=2, text="Prefix the complete evidence suffix"):
    return {
        "chunk_id": "fixture-chunk", "document_id": source, "source": "fixture.pdf",
        "page": page, "text": text, "score": 0.8, "metadata": {"module": 1}
    }

class MetricsTests(unittest.TestCase):
    def test_correct_source_page_and_complete_evidence_are_all_required(self):
        q = question()
        self.assertTrue(evidence_hit(q, hit()))
        self.assertFalse(evidence_hit(q, hit(source="other-source")))
        self.assertFalse(evidence_hit(q, hit(page=3)))
        self.assertFalse(evidence_hit(q, hit(text="only the complete")))

    def test_rank_two_and_documented_alternative_gold_count(self):
        q = question()
        q["alternative_gold"] = [{"source_id": "source-b", "page": 4, "evidence_quote": "valid alternative"}]
        trace = evaluate_query(q, [hit(page=9), hit("source-b", 4, "A valid alternative here")])
        self.assertFalse(trace["hit1"])
        self.assertTrue(trace["evidence_hit3"])

    def test_search_never_receives_reference_answer_or_gold_location(self):
        class RecordingStore:
            def search(self, strategy, vector, top_k, filters):
                self.received = (strategy, vector, top_k, filters)
                return [hit()]
        store = RecordingStore()
        trace = retrieve_one(question(), "C", [0.2, 0.8], store, True)
        self.assertEqual(store.received, ("C", [0.2, 0.8], 3, {"module": 1}))
        self.assertTrue(trace["hit1"])
        self.assertFalse(trace["gold_fields_used_for_search"])
        retrieve_one(question(), "A", [0.2, 0.8], store, False)
        self.assertEqual(store.received[-1], {})

    def test_selection_priorities_and_deterministic_tie_break(self):
        rows = [
            {"strategy": "A", "split": "dev", "evidence_hit3": 0.5, "hit1": 0.5},
            {"strategy": "B", "split": "dev", "evidence_hit3": 0.5, "hit1": 0.5},
            {"strategy": "C", "split": "dev", "evidence_hit3": 0.5, "hit1": 0.5}
        ]
        self.assertEqual(select_on_dev(rows, {"A": 299, "B": 273, "C": 273}), "B")
        rows[0]["evidence_hit3"] = 0.6
        rows[0]["hit1"] = 0.0
        self.assertEqual(select_on_dev(rows, {"A": 299, "B": 273, "C": 273}), "A")

    def test_test_metrics_cannot_select_a_strategy(self):
        with self.assertRaises(ValueError):
            select_on_dev([{"strategy":"A", "split":"test", "hit1":1, "evidence_hit3":1}], {"A":1})

    def test_summary_keeps_split_denominators_and_na_filters(self):
        q = question()
        q["filter"] = {}
        dev = {**evaluate_query(q, [hit()]), "strategy":"A", "latency_ms":1}
        q["split"] = "test"
        test = {**evaluate_query(q, [hit(page=9)]), "strategy":"A", "latency_ms":1}
        rows = summarize([dev, test])
        by_split = {r["split"]:r for r in rows}
        self.assertEqual(by_split["dev"]["questions"], 1)
        self.assertEqual(by_split["dev"]["hit1_n"], 1)
        self.assertEqual(by_split["test"]["hit1_n"], 0)
        self.assertIsNone(by_split["test"]["filter_compliance"])

    def test_corrupted_question_encoding_is_rejected(self):
        from src.models import DocumentPage
        from src.evaluation import validate_benchmark
        rows = []
        for i in range(20):
            q = question()
            q["id"] = f"fixture-{i}"
            q["split"] = "dev" if i < 15 else "test"
            rows.append(q)
        rows[0]["question"] = "A h?u word caused by encoding loss?"
        page = DocumentPage("source-a", "fixture.pdf", 2, "the complete evidence", {"module":1})
        with self.assertRaisesRegex(ValueError, "encoding corruption"):
            validate_benchmark(rows, [page])

    def test_real_benchmark_keeps_vietnamese_accents(self):
        import json
        path = Path(__file__).resolve().parents[2] / "benchmark/questions.json"
        questions = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(questions), 20)
        self.assertIn("\u0111i\u1ec1u khi\u1ec3n", questions[0]["question"])
        for q in questions:
            self.assertEqual(q["question"].count("?"), 1)
            self.assertNotIn("?", q["expected_answer"])
            self.assertTrue(any(ord(c) > 127 for c in q["question"]))

if __name__ == "__main__":
    unittest.main()
