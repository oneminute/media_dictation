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

    def test_local_media_session_metadata(self):
        learner = storage.create_learner("Local Media")
        source = storage.save_media_source(
            media_id="media123",
            original_name="lesson.mp3",
            stored_filename="media123.mp3",
            mime_type="audio/mpeg",
            size_bytes=1234,
            title="Lesson",
            learner_id=learner["id"],
        )
        self.assertEqual(source["title"], "Lesson")

        session_id = storage.create_session(
            video_id="media123",
            source_url="/media/media123",
            language="en",
            is_generated=True,
            total_items=1,
            learner_id=learner["id"],
            video_title="Lesson",
            items=[{"text": "hello", "start": 0, "end": 1, "duration": 1}],
            segmentation_version="whisper-test",
            source_type="local",
            media_id="media123",
        )
        detail = storage.get_session_detail(session_id)
        self.assertEqual(detail["source_type"], "local")
        self.assertEqual(detail["media_id"], "media123")
        self.assertEqual(detail["source_url"], "/media/media123")

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

    def test_duplicate_correct_is_not_recorded_twice(self):
        learner = storage.create_learner("No duplicate correct")
        session_id = storage.create_session(
            video_id="dedupe01",
            source_url="https://youtu.be/dedupe01",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=learner["id"],
            items=[{"text": "hello", "start": 0, "end": 1, "duration": 1}],
        )
        for _ in range(2):
            storage.record_attempt(
                session_id=session_id,
                sentence_index=0,
                sentence_text="hello",
                answer_before="hello",
                event_type="correct",
            )
        with storage.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM attempts
                WHERE session_id = ?
                  AND sentence_index = 0
                  AND event_type = 'correct'
                """,
                (session_id,),
            ).fetchone()
        self.assertEqual(int(row["n"]), 1)

    def test_cross_day_completion_does_not_become_first_pass_today(self):
        learner = storage.create_learner("Cross day")
        session_id = storage.create_session(
            video_id="crossday",
            source_url="https://youtu.be/crossday",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=learner["id"],
            items=[{"text": "hello", "start": 0, "end": 1, "duration": 1}],
        )
        storage.record_attempt(
            session_id=session_id,
            sentence_index=0,
            sentence_text="hello",
            answer_before="helo",
            event_type="replace",
            wrong_word="helo",
            correct_word="hello",
        )
        with storage.connect() as conn:
            conn.execute(
                """
                UPDATE attempts
                SET created_at = datetime('now', '-1 day')
                WHERE session_id = ?
                """,
                (session_id,),
            )

        storage.record_attempt(
            session_id=session_id,
            sentence_index=0,
            sentence_text="hello",
            answer_before="hello",
            event_type="correct",
        )
        today = storage.get_learning_report(learner["id"])["today"]
        self.assertEqual(today["completed_sentences"], 1)
        self.assertEqual(today["attempted_sentences"], 0)
        self.assertIsNone(today["first_pass_accuracy"])

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

    def test_sentence_review_and_export(self):
        learner = storage.create_learner("Exporter")
        session_id = storage.create_session(
            video_id="export01",
            source_url="https://youtu.be/export01",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=learner["id"],
            video_title="Export Video",
            items=[{"text": "review me", "start": 0, "end": 1, "duration": 1}],
        )
        storage.record_sentence_review(
            learner_id=learner["id"],
            original_session_id=session_id,
            sentence_index=0,
            sentence_text="review me",
            answer_before="review me",
            is_correct=True,
        )
        stats = storage.get_sentence_review_stats(learner["id"], 30)
        self.assertEqual(stats["attempts"], 1)
        self.assertEqual(stats["accuracy"], 100.0)

        exported = storage.export_learner_data(learner["id"])
        self.assertEqual(exported["learner"]["name"], "Exporter")
        self.assertEqual(len(exported["sessions"]), 1)
        self.assertEqual(len(exported["practice_items"]), 1)
        self.assertEqual(len(exported["sentence_reviews"]), 1)
        self.assertEqual(exported["export_version"], 1)

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
        self.assertEqual(reviewed["scheduler"], "FSRS-6")

        from datetime import datetime, timezone
        due = datetime.strptime(reviewed["due_at"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        delta_minutes = (
            due - datetime.now(timezone.utc)
        ).total_seconds() / 60
        # py-fsrs default learning steps schedule a new Good card
        # about ten minutes into the future.
        self.assertGreater(delta_minutes, 8)
        self.assertLess(delta_minutes, 12)


if __name__ == "__main__":
    unittest.main()
