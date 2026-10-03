import os
import tempfile
import unittest
from pathlib import Path

import assessment_service
import storage


class RemainingFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("MEDIA_DICTATION_DB")
        os.environ["MEDIA_DICTATION_DB"] = str(
            Path(self.tmp.name) / "remaining_features.db"
        )
        storage.init_db()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("MEDIA_DICTATION_DB", None)
        else:
            os.environ["MEDIA_DICTATION_DB"] = self.old_db
        self.tmp.cleanup()

    def test_media_job_and_transcript_persistence(self):
        learner = storage.create_learner("Media Jobs")
        source = storage.save_media_source(
            media_id="media-job-1",
            original_name="lesson.mp3",
            stored_filename="media-job-1.mp3",
            mime_type="audio/mpeg",
            size_bytes=2048,
            title="Lesson",
            learner_id=learner["id"],
        )
        self.assertEqual(source["transcription_status"], "pending")

        job = storage.create_transcription_job(
            "job-1",
            "media-job-1",
            learner["id"],
        )
        self.assertEqual(job["status"], "queued")

        storage.update_transcription_job(
            "job-1",
            status="running",
            progress=42,
            stage="transcribing",
        )
        self.assertEqual(
            storage.get_transcription_job("job-1")["progress"],
            42,
        )

        transcript = {
            "items": [
                {
                    "text": "Hello world.",
                    "start": 0.0,
                    "end": 1.0,
                    "duration": 1.0,
                }
            ],
            "language": "en",
            "duration": 1.0,
            "whisper_model": "small.en",
            "whisper_device": "cpu",
            "whisper_compute_type": "int8",
        }
        storage.update_media_transcription(
            "media-job-1",
            status="ready",
            transcript=transcript,
        )
        storage.update_transcription_job(
            "job-1",
            status="completed",
            progress=100,
            stage="completed",
            result={"items": transcript["items"]},
        )

        loaded = storage.get_media_transcription("media-job-1")
        self.assertEqual(loaded["items"][0]["text"], "Hello world.")
        library = storage.list_media_sources(learner["id"])
        self.assertEqual(library[0]["transcription_status"], "ready")
        self.assertEqual(library[0]["latest_job"]["status"], "completed")

    def test_export_import_round_trip_creates_new_learner(self):
        learner = storage.create_learner("Round Trip")
        session_id = storage.create_session(
            video_id="roundtrip1",
            source_url="https://youtu.be/roundtrip1",
            language="English",
            is_generated=False,
            total_items=1,
            learner_id=learner["id"],
            video_title="Round Trip Video",
            items=[
                {
                    "text": "Hello, world!",
                    "start": 0,
                    "end": 1,
                    "duration": 1,
                }
            ],
        )
        storage.record_attempt(
            session_id=session_id,
            sentence_index=0,
            sentence_text="Hello, world!",
            answer_before="hello world",
            event_type="correct",
        )
        storage.add_vocabulary_word(
            normalized_word="world",
            display_word="world",
            translation="世界",
            context_sentence="Hello, world!",
            learner_id=learner["id"],
        )

        exported = storage.export_learner_data(learner["id"])
        imported = storage.import_learner_data(exported)
        imported_id = imported["learner"]["id"]

        self.assertNotEqual(imported_id, learner["id"])
        self.assertEqual(imported["imported_sessions"], 1)
        self.assertEqual(
            storage.get_session_history(learner_id=imported_id)[0][
                "video_title"
            ],
            "Round Trip Video",
        )
        self.assertEqual(
            storage.get_vocabulary(learner_id=imported_id)[0]["translation"],
            "世界",
        )

    def test_assessment_storage_and_summary(self):
        learner = storage.create_learner("Assessment")
        run_id = "assessment-run-1"
        storage.start_assessment_run(
            run_id,
            learner["id"],
            assessment_service.ASSESSMENT_VERSION,
            12,
        )

        item = assessment_service.assessment_items()[0]
        scored = assessment_service.score_answer(
            item["id"],
            item["tts_text"],
            replays=0,
        )
        self.assertEqual(scored["token_accuracy"], 1.0)
        self.assertTrue(scored["exact_correct"])

        storage.record_assessment_response(
            run_id=run_id,
            item_id=scored["item_id"],
            level=scored["level"],
            expected_text=scored["expected_text"],
            answer_text=scored["expected_text"],
            token_accuracy=scored["token_accuracy"],
            exact_correct=True,
            replays=0,
        )
        result = assessment_service.summarize_responses(
            [{**scored, "adjusted_accuracy": 1.0}]
        )
        saved = storage.finish_assessment_run(
            run_id,
            score=result["score"],
            estimated_level=result["estimated_level"],
            confidence=result["confidence"],
        )
        self.assertEqual(saved["id"], run_id)
        self.assertEqual(
            len(storage.list_assessment_runs(learner["id"])),
            1,
        )

    def test_assessment_punctuation_is_ignored(self):
        expected = "Please call me when you arrive at the station."
        answer = "please call me when you arrive at the station"
        self.assertEqual(
            assessment_service.token_accuracy(expected, answer),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
