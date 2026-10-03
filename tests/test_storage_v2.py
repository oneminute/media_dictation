import os
import tempfile
import unittest
from pathlib import Path

import storage


class StorageV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("MEDIA_DICTATION_DB")
        os.environ["MEDIA_DICTATION_DB"] = str(
            Path(self.tmp.name) / "media_dictation_test.db"
        )
        storage.init_db()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("MEDIA_DICTATION_DB", None)
        else:
            os.environ["MEDIA_DICTATION_DB"] = self.old_db
        self.tmp.cleanup()

    def test_schema_and_default_learner(self):
        self.assertEqual(storage.get_schema_version(), storage.SCHEMA_VERSION)
        learners = storage.list_learners()
        self.assertTrue(learners)
        self.assertTrue(any(item["is_default"] for item in learners))

    def test_snapshot_resume_survives_segmentation_changes(self):
        learner = storage.create_learner("Student")
        items = [
            {"text": "First saved sentence.", "start": 1.0, "end": 2.5, "duration": 1.5},
            {"text": "Second saved sentence.", "start": 2.5, "end": 4.0, "duration": 1.5},
        ]
        session_id = storage.create_session(
            video_id="abc123XYZ",
            source_url="https://youtu.be/abc123XYZ",
            language="English",
            is_generated=False,
            total_items=2,
            learner_id=learner["id"],
            video_title="Saved title",
            items=items,
            segmentation_version="test-v1",
        )

        storage.record_attempt(
            session_id=session_id,
            sentence_index=0,
            sentence_text=items[0]["text"],
            answer_before=items[0]["text"],
            event_type="correct",
        )

        detail = storage.get_session_detail(session_id)
        self.assertEqual(detail["resume_index"], 1)
        self.assertEqual(detail["video_title"], "Saved title")
        self.assertEqual(detail["items"][0]["text"], "First saved sentence.")
        self.assertEqual(detail["segmentation_version"], "test-v1")

    def test_learners_are_isolated_in_history_and_reports(self):
        a = storage.create_learner("A")
        b = storage.create_learner("B")

        sa = storage.create_session(
            video_id="videoAAA",
            source_url="https://youtu.be/videoAAA",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=a["id"],
            items=[{"text": "hello", "start": 0, "end": 1, "duration": 1}],
        )
        sb = storage.create_session(
            video_id="videoBBB",
            source_url="https://youtu.be/videoBBB",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=b["id"],
            items=[{"text": "world", "start": 0, "end": 1, "duration": 1}],
        )

        storage.record_attempt(
            session_id=sa,
            sentence_index=0,
            sentence_text="hello",
            answer_before="helo",
            event_type="replace",
            wrong_word="helo",
            correct_word="hello",
        )
        storage.record_attempt(
            session_id=sa,
            sentence_index=0,
            sentence_text="hello",
            answer_before="hello",
            event_type="correct",
        )
        storage.record_attempt(
            session_id=sb,
            sentence_index=0,
            sentence_text="world",
            answer_before="world",
            event_type="correct",
        )

        self.assertEqual(len(storage.get_session_history(learner_id=a["id"])), 1)
        self.assertEqual(len(storage.get_session_history(learner_id=b["id"])), 1)
        self.assertEqual(
            storage.get_learning_report(a["id"])["overall"]["errors"],
            1,
        )
        self.assertEqual(
            storage.get_learning_report(b["id"])["overall"]["errors"],
            0,
        )

    def test_learning_events_feed_metrics(self):
        learner = storage.create_learner("Metrics")
        session_id = storage.create_session(
            video_id="metric01",
            source_url="https://youtu.be/metric01",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=learner["id"],
            items=[{"text": "test sentence", "start": 0, "end": 1, "duration": 1}],
        )
        storage.record_attempt(
            session_id=session_id,
            sentence_index=0,
            sentence_text="test sentence",
            answer_before="test sentence",
            event_type="correct",
        )
        for event in ("play", "play", "reveal", "translation", "word_lookup"):
            storage.record_practice_event(
                session_id=session_id,
                sentence_index=0,
                event_type=event,
            )
        storage.record_practice_event(
            session_id=session_id,
            sentence_index=0,
            event_type="time_spent",
            value_ms=90000,
        )

        report = storage.get_learning_report(learner["id"])["overall"]
        self.assertEqual(report["plays"], 2)
        self.assertEqual(report["reveals"], 1)
        self.assertEqual(report["translations_used"], 1)
        self.assertEqual(report["word_lookups"], 1)
        self.assertEqual(report["time_spent_minutes"], 1.5)

    def test_translation_cache_is_model_scoped(self):
        storage.save_translation(
            source_text="hello",
            translation="你好",
            provider="ollama",
            model="local-model",
            service_tier="local",
            prompt_version="sentence-v2",
        )
        self.assertIsNotNone(
            storage.get_translation(
                "hello",
                provider="ollama",
                model="local-model",
                prompt_version="sentence-v2",
            )
        )
        self.assertIsNone(
            storage.get_translation(
                "hello",
                provider="openai",
                model="gpt-model",
                prompt_version="sentence-v2",
            )
        )

    def test_vocabulary_supports_multiple_meanings_and_review(self):
        learner = storage.create_learner("Vocabulary")
        first = storage.add_vocabulary_word(
            normalized_word="run",
            display_word="run",
            translation="经营",
            context_sentence="I run a small business.",
            learner_id=learner["id"],
        )
        second = storage.add_vocabulary_word(
            normalized_word="run",
            display_word="run",
            translation="跑",
            context_sentence="I run every morning.",
            learner_id=learner["id"],
        )
        self.assertNotEqual(first["id"], second["id"])
        words = storage.get_vocabulary(learner_id=learner["id"])
        self.assertEqual(len(words), 2)

        reviewed = storage.review_vocabulary(first["id"], "good")
        self.assertEqual(reviewed["review_count"], 1)
        self.assertGreaterEqual(reviewed["review_stage"], 1)


if __name__ == "__main__":
    unittest.main()
