import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import llm_service as llm
import semantic_segmentation as semantic
import sentence_ladder


def completion(content, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish, message=SimpleNamespace(content=content))])


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "test-only-key", "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-flash", "DEEPSEEK_WORD_MODEL": ""})
        self.env.start()
        self.client_patch = patch.object(llm, "OpenAI")
        self.factory = self.client_patch.start()
        self.client = self.factory.return_value
        self.client.chat.completions.create.return_value = completion("测试结果")

    def tearDown(self):
        self.client_patch.stop()
        self.env.stop()

    def test_chat_uses_deepseek_endpoint_and_compatible_payload(self):
        text, model, tier = llm.translate_to_chinese("Hello.", "deepseek")
        self.assertEqual((text, model, tier), ("测试结果", "deepseek:deepseek-flash", "default"))
        self.assertEqual(self.factory.call_args.kwargs["base_url"], "https://api.deepseek.com")
        self.assertEqual(self.factory.call_args.kwargs["api_key"], "test-only-key")
        payload = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "Hello."})
        self.assertEqual(payload["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertNotIn("service_tier", payload)
        self.assertNotIn("max_output_tokens", payload)
        self.client.responses.create.assert_not_called()

    def test_default_provider_and_explicit_selection_do_not_call_others(self):
        with patch.object(llm, "translate_to_chinese_openai") as cloud, \
             patch.object(llm, "translate_to_chinese_ollama") as local:
            llm.translate_to_chinese("Hello.")
            cloud.assert_not_called()
            local.assert_not_called()
        self.assertEqual(llm.normalize_provider("DeepSeek"), "deepseek")

    def test_word_model_override_and_cache_identity(self):
        with patch.dict(os.environ, {"DEEPSEEK_WORD_MODEL": "deepseek-v4-pro"}):
            result = llm.translate_word_in_context("run", "Run the program.", "deepseek")
            self.assertEqual(result[1], "deepseek:deepseek-v4-pro")
            self.assertEqual(llm.cache_candidates(word=True, provider_override="deepseek"),
                             [("deepseek", "deepseek-v4-pro")])
        self.assertEqual(llm.result_identity(result[1]), ("deepseek", "deepseek-v4-pro"))
        self.assertEqual(llm.deepseek_model(word=True), "deepseek-flash")

    def test_analysis_summary_and_ladder_use_deepseek(self):
        self.assertEqual(llm.analyze_english_sentence("Hello.", "deepseek")[1], "deepseek:deepseek-flash")
        self.assertEqual(llm.generate_learning_summary({"sessions": 3}, "deepseek")[1], "deepseek:deepseek-flash")
        self.client.chat.completions.create.return_value = completion(json.dumps(
            {"steps": [{"label": "主干", "text": "I run."}, {"label": "完整原句", "text": "I run every day."}]}))
        result = sentence_ladder.build_ladder("I run every day.", "deepseek")
        self.assertEqual(result["model"], "deepseek:deepseek-flash")
        self.assertEqual(result["steps"][-1]["text"], "I run every day.")

    def test_semantic_segmentation_uses_deepseek_and_preserves_timing(self):
        self.client.chat.completions.create.return_value = completion('{"ends":[1,3]}')
        words = [{"text": word, "start": i, "end": i+.5}
                 for i, word in enumerate("Hello world. Thanks again.".split())]
        result, models = semantic.segment_timed_words(words, provider_override="deepseek")
        self.assertEqual([r["text"] for r in result], ["Hello world.", "Thanks again."])
        self.assertEqual(result[1]["start"], 2)
        self.assertEqual(result[1]["end"], 3.5)
        self.assertEqual(models, ["deepseek:deepseek-flash"])

    def test_missing_key_is_explicit_and_never_uses_other_keys(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "other-key"}):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                llm.translate_to_chinese("Hello.", "deepseek")
        self.factory.assert_not_called()

    def test_empty_or_truncated_output_is_not_accepted(self):
        for output in (completion(""), completion("partial", "length"), SimpleNamespace(choices=[])):
            with self.subTest(output=output):
                self.client.chat.completions.create.return_value = output
                with self.assertRaises(RuntimeError):
                    llm.translate_to_chinese("Hello.", "deepseek")

    def test_auto_keeps_existing_fallback_and_cache_candidates(self):
        with patch.object(llm, "translate_to_chinese_ollama", side_effect=RuntimeError("offline")), \
             patch.object(llm, "translate_to_chinese_openai", return_value=("你好", "cloud", "default")) as cloud:
            self.assertEqual(llm.translate_to_chinese("Hello", "auto")[0], "你好")
            cloud.assert_called_once()
        self.factory.assert_not_called()
        self.assertEqual([p for p, _ in llm.cache_candidates(provider_override="auto")], ["ollama", "openai"])


class DeepSeekApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MEDIA_DICTATION_DB": str(Path(self.tmp.name)/"api.db"),
            "LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-only-key",
            "DEEPSEEK_MODEL": "shared-model", "OPENAI_TRANSLATION_MODEL": "shared-model"})
        self.env.start()
        import storage
        import app
        storage.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_translation_cache_is_reused_and_isolated_from_openai(self):
        with patch.object(llm, "OpenAI") as factory:
            factory.return_value.chat.completions.create.return_value = completion("你好")
            first = self.client.post("/api/translate", json={"text": "Hello", "provider": "deepseek"}).get_json()
            second = self.client.post("/api/translate", json={"text": "Hello", "provider": "deepseek"}).get_json()
            self.assertTrue(first["ok"])
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(second["provider"], "deepseek")
            self.assertEqual(second["model"], "deepseek:shared-model")
            self.assertEqual(factory.return_value.chat.completions.create.call_count, 1)
        with patch("app.translate_to_chinese", return_value=("另一结果", "shared-model", "default")) as translate:
            other = self.client.post("/api/translate", json={"text": "Hello", "provider": "openai"}).get_json()
            self.assertFalse(other["cached"])
            self.assertEqual(other["provider"], "openai")
            translate.assert_called_once()

    def test_health_reports_configuration_without_exposing_key(self):
        with patch("app.ollama_available", return_value=False):
            data = self.client.get("/api/health").get_json()
        self.assertEqual(data["llm_provider"], "deepseek")
        self.assertTrue(data["deepseek_enabled"])
        self.assertTrue(data["translation_enabled"])
        self.assertNotIn("test-only-key", json.dumps(data))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), patch("app.ollama_available", return_value=True):
            data = self.client.get("/api/health").get_json()
        self.assertFalse(data["translation_enabled"])

    def test_word_lookup_cache_uses_deepseek_identity(self):
        with patch.dict(os.environ, {"DEEPSEEK_WORD_MODEL": "word-model"}), patch.object(llm, "OpenAI") as factory:
            factory.return_value.chat.completions.create.return_value = completion("运行")
            payload = {"word": "run", "context": "Run the program.", "provider": "deepseek"}
            first = self.client.post("/api/word-lookup", json=payload).get_json()
            second = self.client.post("/api/word-lookup", json=payload).get_json()
            self.assertTrue(first["ok"])
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(second["model"], "deepseek:word-model")
            self.assertEqual(second["provider"], "deepseek")
            self.assertEqual(factory.return_value.chat.completions.create.call_count, 1)


class DeepSeekWireTests(unittest.TestCase):
    def test_real_sdk_sends_chat_completions_to_configured_server(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({"id": "test", "object": "chat.completion", "created": 0,
                    "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "你好"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
            thread.start()
            try:
                with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-key",
                    "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "DEEPSEEK_MODEL": "deepseek-flash", "NO_PROXY": "127.0.0.1,localhost",
                    "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
                    "http_proxy": "", "https_proxy": "", "all_proxy": ""}):
                    result = llm.translate_to_chinese("Hello.", "deepseek")
                self.assertEqual(result[0], "你好")
                self.assertEqual(received[0][0], "/chat/completions")
                self.assertEqual(received[0][1]["thinking"], {"type": "disabled"})
                self.assertNotIn("service_tier", received[0][1])
            finally:
                server.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
