import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ["MEDIA_DICTATION_DB"] = str(Path(_tmp.name) / "api_test.db")

import app
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
        self.assertGreaterEqual(data["schema_version"], 4)
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

    def test_auto_router_falls_back_to_openai(self):
        with patch.object(app, "llm_provider", return_value="auto"), patch.object(
            app,
            "translate_to_chinese_ollama",
            side_effect=RuntimeError("local unavailable"),
        ), patch.object(
            app,
            "translate_to_chinese_openai",
            return_value=("云端结果", "gpt-test", "flex"),
        ):
            result = app.translate_to_chinese("hello")
        self.assertEqual(result, ("云端结果", "gpt-test", "flex"))

    def test_ollama_only_never_calls_openai(self):
        with patch.object(app, "llm_provider", return_value="ollama"), patch.object(
            app,
            "translate_to_chinese_ollama",
            return_value=("本地结果", "ollama:test", "local"),
        ), patch.object(app, "translate_to_chinese_openai") as cloud:
            result = app.translate_to_chinese("hello")
        self.assertEqual(result[0], "本地结果")
        cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
