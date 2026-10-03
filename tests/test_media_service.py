import io
import os
import tempfile
import unittest
from pathlib import Path

from werkzeug.datastructures import FileStorage

import media_service


class FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class FakeSegment:
    def __init__(self, words):
        self.words = words
        self.text = " ".join(word.word for word in words)
        self.start = words[0].start
        self.end = words[-1].end


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_media_dir = os.environ.get("MEDIA_DICTATION_MEDIA_DIR")
        os.environ["MEDIA_DICTATION_MEDIA_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old_media_dir is None:
            os.environ.pop("MEDIA_DICTATION_MEDIA_DIR", None)
        else:
            os.environ["MEDIA_DICTATION_MEDIA_DIR"] = self.old_media_dir
        self.tmp.cleanup()

    def test_word_timestamps_form_stable_sentences(self):
        segments = [
            FakeSegment(
                [
                    FakeWord("Hello", 0.0, 0.25),
                    FakeWord("there.", 0.25, 0.55),
                    FakeWord("How", 1.0, 1.2),
                    FakeWord("are", 1.2, 1.35),
                    FakeWord("you?", 1.35, 1.7),
                ]
            )
        ]
        items = media_service.whisper_segments_to_practice_items(segments)
        self.assertEqual(
            [item["text"] for item in items],
            ["Hello there.", "How are you?"],
        )
        self.assertAlmostEqual(items[0]["start"], 0.0)
        self.assertAlmostEqual(items[1]["end"], 1.7)

    def test_persist_uploaded_media(self):
        upload = FileStorage(
            stream=io.BytesIO(b"fake audio"),
            filename="Lesson One.mp3",
            content_type="audio/mpeg",
        )
        item = media_service.persist_uploaded_media(upload)
        self.assertEqual(item["original_name"], "Lesson_One.mp3")
        self.assertTrue(item["path"].exists())
        self.assertEqual(item["title"], "Lesson_One")
        self.assertEqual(item["mime_type"], "audio/mpeg")

    def test_rejects_unsupported_extension(self):
        upload = FileStorage(
            stream=io.BytesIO(b"not media"),
            filename="notes.txt",
            content_type="text/plain",
        )
        with self.assertRaises(ValueError):
            media_service.persist_uploaded_media(upload)


if __name__ == "__main__":
    unittest.main()
