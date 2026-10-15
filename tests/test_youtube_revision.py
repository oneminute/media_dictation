import unittest

from youtube_revision_service import align_caption_to_whisper


class CaptionAlignmentTests(unittest.TestCase):
    def test_preserves_caption_text_and_replaces_timing(self):
        captions = [
            {"text": "The Roman Empire was", "start": 1.0, "end": 2.0},
            {"text": "very powerful.", "start": 2.0, "end": 3.0},
        ]
        words = [
            {"text": t, "start": i * 0.4 + 5, "end": i * 0.4 + 5.3}
            for i, t in enumerate("The Roman Empire was very powerful".split())
        ]
        output = align_caption_to_whisper(captions, words)
        self.assertIsNotNone(output)
        self.assertEqual(output[0]["text"], "The Roman Empire was very powerful.")
        self.assertAlmostEqual(output[0]["start"], 5)
        self.assertGreater(output[0]["end"], 6.9)

    def test_rejects_unrelated_caption_text(self):
        captions = [{"text": "A completely unrelated narration", "start": 1, "end": 3}]
        words = [{"text": t, "start": i, "end": i + 0.3}
                 for i, t in enumerate("We walked down the street".split())]
        self.assertIsNone(align_caption_to_whisper(captions, words))


if __name__ == "__main__":
    unittest.main()
