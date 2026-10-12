import os
import tempfile
import unittest
from pathlib import Path

import content_analysis
import storage


class ContentAnalysisTests(unittest.TestCase):
    def test_harder_transcript_scores_above_easy_transcript(self):
        easy = []
        for i in range(10):
            easy.append(
                {
                    "text": "We walk home after school.",
                    "start": i * 10.0,
                    "end": i * 10.0 + 4.0,
                    "duration": 4.0,
                }
            )

        hard_text = (
            "Although technological innovation accelerates productivity, "
            "organizations must nevertheless evaluate consequential tradeoffs "
            "whenever regulatory uncertainty affects international collaboration."
        )
        hard = []
        for i in range(10):
            hard.append(
                {
                    "text": hard_text,
                    "start": i * 3.0,
                    "end": i * 3.0 + 2.8,
                    "duration": 2.8,
                }
            )

        easy_result = content_analysis.analyze_transcript(easy)
        hard_result = content_analysis.analyze_transcript(hard)

        self.assertEqual(easy_result["cefr_level"], "A2")
        self.assertGreater(
            hard_result["difficulty_score"],
            easy_result["difficulty_score"],
        )
        self.assertIn(hard_result["cefr_level"], {"B2", "C1"})
        self.assertGreater(hard_result["wpm"], easy_result["wpm"])
        self.assertGreater(
            hard_result["complex_word_ratio"],
            easy_result["complex_word_ratio"],
        )

    def test_level_recommendation(self):
        self.assertEqual(
            content_analysis.level_recommendation("B2", "B2")["fit"],
            "good",
        )
        self.assertEqual(
            content_analysis.level_recommendation("C1", "B2")["fit"],
            "challenge",
        )
        self.assertEqual(
            content_analysis.level_recommendation("B2", None)["fit"],
            "unknown",
        )


class ContentResourceStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("MEDIA_DICTATION_DB")
        os.environ["MEDIA_DICTATION_DB"] = str(
            Path(self.tmp.name) / "content_resources.db"
        )
        storage.init_db()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("MEDIA_DICTATION_DB", None)
        else:
            os.environ["MEDIA_DICTATION_DB"] = self.old_db
        self.tmp.cleanup()

    def test_save_update_and_filter_resource(self):
        learner = storage.create_learner("Content Learner")
        analysis = {
            "analysis_version": content_analysis.ANALYSIS_VERSION,
            "cefr_level": "B2",
            "difficulty_score": 61.5,
            "confidence": "medium",
            "word_count": 520,
            "duration": 300,
            "wpm": 104,
            "avg_phrase_words": 10.2,
            "reasons": ["test"],
        }

        saved = storage.save_content_resource(
            learner_id=learner["id"],
            source_type="youtube",
            source_id="video123",
            source_url="https://youtu.be/video123",
            title="History of Flight",
            language="English",
            is_generated=False,
            analysis=analysis,
        )
        self.assertEqual(saved["analysis"]["cefr_level"], "B2")

        rows = storage.list_content_resources(
            learner["id"],
            level="B2",
            source_type="youtube",
            query="Flight",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], "video123")
        self.assertEqual(rows[0]["word_count"], 520)

        updated_analysis = {**analysis, "cefr_level": "B1", "difficulty_score": 44.0}
        storage.save_content_resource(
            learner_id=learner["id"],
            source_type="youtube",
            source_id="video123",
            source_url="https://youtu.be/video123",
            title="History of Flight",
            language="English",
            is_generated=False,
            analysis=updated_analysis,
        )
        rows = storage.list_content_resources(learner["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cefr_level"], "B1")


if __name__ == "__main__":
    unittest.main()
