"""Regression tests for review forms: empty scores must not consume the next field."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.review_results import parse_fields

class ReviewParserTests(unittest.TestCase):
    def test_blank_score_does_not_consume_reason_line(self):
        with self.assertRaisesRegex(ValueError,"SCORE"):
            parse_fields("\nSCORE:\nREASON: some actual reason\nREVIEWER: fixture\n",2)

    def test_binary_metadata_score_cannot_be_two(self):
        with self.assertRaisesRegex(ValueError,"between"):
            parse_fields("SCORE: 2\nREASON: reason\nREVIEWER: fixture",1)

    def test_complete_label_preserves_reviewer_and_reason(self):
        self.assertEqual(parse_fields("SCORE: 1\nREASON: missing condition\nREVIEWER: Codex AI",2),
                         (1,"missing condition","Codex AI"))
if __name__=="__main__":
    unittest.main()
