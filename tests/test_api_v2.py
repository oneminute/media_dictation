import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ["MEDIA_DICTATION_DB"] = str(Path(_tmp.name) / "api_test.db")

import app
import llm_service
import storage


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.init_db()
        app.app.config.update(TESTING=True)
        cls.client = app.app.test_client()

    def test_health_exposes_schema_and_provider(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["schema_version"], 5)
        self.assertIn(data["llm_provider"], {"auto", "ollama", "openai"})

    def test_create_learner_session_snapshot_and_resume(self):
        learner = self.client.post(
            "/api/learners",
            json={"name": "API Student"},
        ).get_json()["learner"]

        session_response = self.client.post(
            "/api/session",
            json={
                "video_id": "apiVideo1",
                "source_url": "https://youtu.be/apiVideo1",
                "language": "English",
                "learner_id": learner["id"],
                "video_title": "API Video",
                "segmentation_version": "api-test",
                "items": [
                    {"text": "one sentence", "start": 0, "end": 1, "duration": 1},
                    {"text": "two sentence", "start": 1, "end": 2, "duration": 1},
                ],
            },
        )
        self.assertEqual(session_response.status_code, 200)
        session_id = session_response.get_json()["session_id"]

        self.client.post(
            "/api/attempt",
            json={
                "session_id": session_id,
                "sentence_index": 0,
                "sentence_text": "one sentence",
                "answer_before": "one sentence",
                "event_type": "correct",
            },
        )

        detail = self.client.get(f"/api/session/{session_id}").get_json()["session"]
        self.assertEqual(detail["resume_index"], 1)
        self.assertEqual(len(detail["items"]), 2)
        self.assertEqual(detail["video_title"], "API Video")

    def test_export_endpoint(self):
        learner = self.client.post(
            "/api/learners",
            json={"name": "Export API Student"},
        ).get_json()["learner"]
        response = self.client.get(
            "/api/export?learner_id=" + str(learner["id"])
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["learner"]["name"], "Export API Student")
        self.assertIn("sessions", data)
        self.assertIn("vocabulary", data)

    def test_local_media_transcription_endpoint(self):
        learner = self.client.post(
            "/api/learners",
            json={"name": "Media API Student"},
        ).get_json()["learner"]

        fake_path = Path(_tmp.name) / "fake.mp3"
        fake_path.write_bytes(b"fake")

        with patch.object(
            app,
            "persist_uploaded_media",
            return_value={
                "id": "media-api-1",
                "original_name": "fake.mp3",
                "stored_filename": "fake.mp3",
                "path": fake_path,
                "mime_type": "audio/mpeg",
                "size_bytes": 4,
                "title": "fake",
            },
        ), patch.object(
            app,
            "transcribe_media",
            return_value={
                "items": [
                    {
                        "text": "hello world",
                        "start": 0.0,
                        "end": 1.0,
                        "duration": 1.0,
                    }
                ],
                "language": "en",
                "duration": 1.0,
                "whisper_model": "test-whisper",
                "whisper_device": "cpu",
                "whisper_compute_type": "int8",
            },
        ):
            response = self.client.post(
                "/api/media/transcribe",
                data={
                    "learner_id": str(learner["id"]),
                    "file": (io.BytesIO(b"fake"), "fake.mp3"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["source_type"], "local")
        self.assertEqual(data["media_id"], "media-api-1")
        self.assertEqual(data["items"][0]["text"], "hello world")

    def test_translate_honors_provider_override(self):
        with patch.object(app, "cache_candidates", return_value=[]), patch.object(
            app,
            "translate_to_chinese",
            return_value=("本地指定结果", "ollama:test-model", "local"),
        ) as translate_mock:
            response = self.client.post(
                "/api/translate",
                json={"text": "provider override unique", "provider": "ollama"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["provider"], "ollama")
        translate_mock.assert_called_once_with(
            "provider override unique",
            provider_override="ollama",
        )

    def test_auto_router_falls_back_to_openai(self):
        with patch.object(
            llm_service,
            "translate_to_chinese_ollama",
            side_effect=RuntimeError("local unavailable"),
        ), patch.object(
            llm_service,
            "translate_to_chinese_openai",
            return_value=("云端结果", "gpt-test", "flex"),
        ):
            result = llm_service.translate_to_chinese(
                "hello",
                provider_override="auto",
            )
        self.assertEqual(result, ("云端结果", "gpt-test", "flex"))

    def test_ollama_only_never_calls_openai(self):
        with patch.object(
            llm_service,
            "translate_to_chinese_ollama",
            return_value=("本地结果", "ollama:test", "local"),
        ), patch.object(llm_service, "translate_to_chinese_openai") as cloud:
            result = llm_service.translate_to_chinese(
                "hello",
                provider_override="ollama",
            )
        self.assertEqual(result[0], "本地结果")
        cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
