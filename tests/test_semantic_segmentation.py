import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import semantic_segmentation as semantic
import youtube_revision_service as revision
from storage import connect


def timed(text):
    return [{"text": word, "start": i * 2.0, "end": i * 2.0 + .4}
            for i, word in enumerate(text.split())]


class SemanticSegmentationTests(unittest.TestCase):
    def test_long_sentence_and_long_pauses_are_not_cut(self):
        source = timed("Although we had been waiting for a very long time in the cold "
                       "outside the station we decided to stay until our friends arrived.")
        with patch.object(semantic, "_request_ends", return_value=([len(source)-1], "test")):
            result, models = semantic.segment_timed_words(source)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], " ".join(w["text"] for w in source))
        self.assertEqual(result[0]["start"], source[0]["start"])
        self.assertEqual(result[0]["end"], source[-1]["end"])
        self.assertEqual(models, ["test"])

    def test_unfinished_batch_is_carried_to_more_context(self):
        source = timed("If you wait for me I will go with you. Thanks.")
        seen = []

        def model(units, context, final, provider):
            seen.append(([w["text"] for w in units], context, final))
            if len(seen) == 1:
                return [], "test"
            return [9, 10], "test"

        with patch.object(semantic, "BATCH_WORDS", 6), patch.object(semantic, "_request_ends", side_effect=model):
            result, _ = semantic.segment_timed_words(source)
        self.assertEqual([r["text"] for r in result],
                         ["If you wait for me I will go with you.", "Thanks."])
        self.assertFalse(seen[0][2])
        self.assertTrue(seen[1][2])

    def test_completed_sentences_leave_trailing_words_for_next_batch(self):
        source = timed("Hello there. If you wait I will come. Thanks.")
        seen = []

        def model(units, context, final, provider):
            seen.append(([w["text"] for w in units], context))
            return ([1] if len(seen) == 1 else [5, 6]), "test"

        with patch.object(semantic, "BATCH_WORDS", 8), patch.object(semantic, "_request_ends", side_effect=model):
            result, _ = semantic.segment_timed_words(source)
        self.assertEqual(seen[1][0][0], "If")
        self.assertEqual(seen[1][1], "Hello there.")
        self.assertEqual(" ".join(r["text"] for r in result), " ".join(w["text"] for w in source))

    def test_invalid_boundaries_are_rejected(self):
        for ends in ([True], [-1], [2], [1, 0], [0, 0], [], [0]):
            with self.subTest(ends=ends), self.assertRaises(ValueError):
                semantic._parse_ends(json.dumps({"ends": ends}), 2, True)

    def test_context_limit_raises_instead_of_cutting(self):
        with patch.object(semantic, "BATCH_WORDS", 2), patch.object(semantic, "MAX_CONTEXT_WORDS", 4), \
             patch.object(semantic, "_request_ends", return_value=([], "test")):
            with self.assertRaisesRegex(RuntimeError, "未强制截断"):
                semantic.segment_timed_words(timed("one two three four five six"))

    def test_local_request_only_asks_model_for_boundaries(self):
        with patch.object(semantic.llm, "ollama_chat", return_value='{"ends":[1]}') as chat:
            result, _ = semantic.segment_timed_words(timed("Hello world."), provider_override="ollama")
        self.assertEqual(result[0]["text"], "Hello world.")
        prompt = json.loads(chat.call_args.kwargs["user_prompt"])
        self.assertEqual(prompt["words"], [{"index": 0, "text": "Hello"}, {"index": 1, "text": "world."}])
        self.assertTrue(prompt["final"])


class RevisionCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MEDIA_DICTATION_DB": str(Path(self.tmp.name)/"revision.db")})
        self.env.start()
        self.source = {"words": timed("Hello world. Thank you."), "language": "en", "duration": 9}
        with connect() as conn:
            revision._ensure_table(conn)
            for version, payload in [("caption-align-v2", {"items": [{"text": "legacy"}]}),
                                     (revision.AUDIO_SOURCE_VERSION, self.source)]:
                conn.execute("INSERT INTO youtube_transcript_revisions(video_id,revision_version,transcript_json) VALUES(?,?,?)",
                             ("video123", version, json.dumps(payload)))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_old_cache_is_readable_but_not_reused_as_semantic(self):
        self.assertTrue(revision.get_revision("video123")["revision_outdated"])
        self.assertIsNone(revision.get_revision("video123", require_current=True))

    def test_semantic_result_and_timestamps_persist_and_are_reused(self):
        with patch.object(semantic, "_request_ends", return_value=([1, 3], "test")) as model, \
             patch.object(revision, "transcribe_media", side_effect=AssertionError("must use audio cache")):
            result, cached = revision.revise_youtube("video123")
            again, cached_again = revision.revise_youtube("video123")
        self.assertFalse(cached)
        self.assertTrue(cached_again)
        self.assertEqual(result, again)
        self.assertEqual(model.call_count, 1)
        self.assertEqual([x["text"] for x in result["items"]], ["Hello world.", "Thank you."])
        self.assertEqual(result["items"][1]["start"], 4)
        self.assertEqual(result["items"][1]["end"], 6.4)
        self.assertEqual(result["words"], self.source["words"])
        self.assertEqual(result["segmentation_method"], "semantic")

    def test_failed_model_keeps_old_revision_and_audio_cache(self):
        with patch.object(revision, "segment_timed_words", side_effect=RuntimeError("model failed")):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                revision.revise_youtube("video123")
        self.assertIsNone(revision.get_revision("video123", require_current=True))
        self.assertEqual(revision.get_revision("video123")["items"][0]["text"], "legacy")
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM youtube_transcript_revisions").fetchone()[0]
        self.assertEqual(count, 2)

    def test_fresh_transcription_survives_failed_semantic_step_and_retry(self):
        def download(command, **kwargs):
            output = command[command.index("--output") + 1]
            Path(output.replace("%(ext)s", "wav")).write_bytes(b"fake audio")

        with patch.object(revision, "whisper_available", return_value=True), \
             patch.object(revision.subprocess, "run", side_effect=download), \
             patch.object(revision, "transcribe_media", return_value=self.source) as transcribe, \
             patch.object(revision, "segment_timed_words", side_effect=RuntimeError("model failed")):
            with self.assertRaises(RuntimeError):
                revision.revise_youtube("fresh123")
        self.assertEqual(transcribe.call_count, 1)
        # The intermediate source must never be returned as a completed revision.
        self.assertIsNone(revision.get_revision("fresh123"))
        with patch.object(revision, "transcribe_media", side_effect=AssertionError("repeat transcription")), \
             patch.object(semantic, "_request_ends", return_value=([1, 3], "test")):
            result, _ = revision.revise_youtube("fresh123")
        self.assertEqual(len(result["items"]), 2)


class ForcedRevisionTests(unittest.TestCase):
    setUp = RevisionCacheTests.setUp
    tearDown = RevisionCacheTests.tearDown
    def test_force_bypasses_both_caches_and_replaces_result(self):
        with patch.object(semantic, "_request_ends", return_value=([1, 3], "test")):
            previous, _ = revision.revise_youtube("video123")

        def download(command, **kwargs):
            output = command[command.index("--output") + 1]
            Path(output.replace("%(ext)s", "wav")).write_bytes(b"fresh audio")

        fresh = {**self.source, "words": timed("Fresh words. New sentence.")}
        with patch.object(revision, "whisper_available", return_value=True), \
             patch.object(revision.subprocess, "run", side_effect=download) as downloaded, \
             patch.object(revision, "transcribe_media", return_value=fresh) as transcribe, \
             patch.object(semantic, "_request_ends", return_value=([1, 3], "test")):
            result, cached = revision.revise_youtube("video123", force=True)
        self.assertFalse(cached)
        self.assertEqual(downloaded.call_count, 1)
        self.assertEqual(transcribe.call_count, 1)
        self.assertNotEqual(result, previous)
        self.assertEqual(revision.get_revision("video123", require_current=True), result)
        self.assertEqual(result["items"][0]["text"], "Fresh words.")

    def test_force_failure_keeps_current_completed_revision(self):
        with patch.object(semantic, "_request_ends", return_value=([1, 3], "test")):
            previous, _ = revision.revise_youtube("video123")
        def download(command, **kwargs):
            output = command[command.index("--output") + 1]
            Path(output.replace("%(ext)s", "wav")).write_bytes(b"fresh audio")

        with patch.object(revision, "whisper_available", return_value=True), \
             patch.object(revision.subprocess, "run", side_effect=download), \
             patch.object(revision, "transcribe_media", return_value=self.source), \
             patch.object(revision, "segment_timed_words", side_effect=RuntimeError("semantic failed")):
            with self.assertRaises(RuntimeError):
                revision.revise_youtube("video123", force=True)
        self.assertEqual(revision.get_revision("video123", require_current=True), previous)

    def test_force_submission_queues_even_with_existing_cache_and_deduplicates(self):
        import youtube_revision_jobs as jobs
        with patch.object(semantic, "_request_ends", return_value=([1, 3], "test")):
            revision.revise_youtube("video123")
        try:
            with patch.object(jobs._executor, "submit") as submit:
                cached = jobs.submit("video123")
                self.assertTrue(cached["cached"])
                job = jobs.submit("video123", "ollama", force=True)
                self.assertEqual(job["status"], "queued")
                submit.assert_called_once_with(jobs._run, job["id"], "video123", "ollama", True)
                self.assertEqual(jobs.submit("video123", force=True)["id"], job["id"])
                self.assertEqual(jobs.submit("video123")["id"], job["id"])
        finally:
            jobs._running.discard("video123")


class RevisionApiTests(unittest.TestCase):
    def test_revision_passes_selected_provider_and_rejects_invalid_provider(self):
        import app
        client = app.app.test_client()
        with patch.object(app, "submit_youtube_revision", return_value={"status": "queued"}) as submit:
            response = client.post("/api/transcript/revise", json={"video_id": "UNP03fDSj1U", "provider": "ollama"})
            self.assertEqual(response.status_code, 202)
            submit.assert_called_once_with("UNP03fDSj1U", provider_override="ollama", force=False)
        with patch.object(app, "submit_youtube_revision") as submit:
            response = client.post("/api/transcript/revise", json={"video_id": "UNP03fDSj1U", "provider": "unknown"})
            self.assertEqual(response.status_code, 400)
            submit.assert_not_called()

    def test_revision_accepts_explicit_force_and_rejects_strings(self):
        import app
        client = app.app.test_client()
        with patch.object(app, "submit_youtube_revision", return_value={"status": "queued"}) as submit:
            response = client.post("/api/transcript/revise", json={"video_id": "UNP03fDSj1U", "provider": "ollama", "force": True})
            self.assertEqual(response.status_code, 202)
            submit.assert_called_once_with("UNP03fDSj1U", provider_override="ollama", force=True)
        with patch.object(app, "submit_youtube_revision") as submit:
            response = client.post("/api/transcript/revise", json={"video_id": "UNP03fDSj1U", "force": "true"})
            self.assertEqual(response.status_code, 400)
            submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
