import unittest

from app import clean_caption_text, extract_video_id, merge_caption_fragments


class UrlParsingTests(unittest.TestCase):
    def test_youtube_music_watch_url(self):
        self.assertEqual(
            extract_video_id(
                "https://music.youtube.com/watch?v=15m_iQaKHVg&t=82"
            ),
            "15m_iQaKHVg",
        )

    def test_youtube_music_podcast_url(self):
        self.assertEqual(
            extract_video_id("https://music.youtube.com/podcast/AVRF8B504GE"),
            "AVRF8B504GE",
        )


class SegmentationTests(unittest.TestCase):
    def test_removes_music_marker_inside_caption(self):
        self.assertEqual(
            clean_caption_text("[Music] Hello everyone."),
            "Hello everyone.",
        )

    def test_prefers_comma_for_long_sentence(self):
        items = [
            {"text": "I think one of the most important things", "start": 0.0, "end": 2.0},
            {"text": "we need to understand about learning,", "start": 2.1, "end": 4.0},
            {"text": "especially when we are trying something difficult,", "start": 4.1, "end": 6.0},
            {"text": "is that progress is rarely a straight line.", "start": 6.1, "end": 9.0},
        ]

        segments = merge_caption_fragments(items)

        self.assertEqual(
            [item["text"] for item in segments],
            [
                "I think one of the most important things we need to understand about learning,",
                "especially when we are trying something difficult,",
                "is that progress is rarely a straight line.",
            ],
        )

    def test_clause_starter_is_a_good_break(self):
        items = [
            {"text": "Today I want to show you", "start": 0.0, "end": 1.7},
            {"text": "how a very small change", "start": 1.8, "end": 3.2},
            {"text": "can make a big difference", "start": 3.3, "end": 4.8},
            {"text": "because we often underestimate", "start": 5.0, "end": 6.3},
            {"text": "the effect of repeated practice", "start": 6.4, "end": 8.0},
        ]

        segments = merge_caption_fragments(items)

        self.assertEqual(
            [item["text"] for item in segments],
            [
                "Today I want to show you how a very small change can make a big difference",
                "because we often underestimate the effect of repeated practice",
            ],
        )

    def test_does_not_break_after_article(self):
        items = [
            {"text": "This is one of the", "start": 0.0, "end": 1.2},
            {"text": "most important ideas", "start": 1.3, "end": 2.5},
            {"text": "that you should remember", "start": 2.6, "end": 4.0},
            {"text": "when you practice listening", "start": 4.1, "end": 5.8},
            {"text": "every single day", "start": 5.9, "end": 7.0},
        ]

        segments = merge_caption_fragments(items)

        self.assertEqual(
            segments[0]["text"],
            "This is one of the most important ideas that you should remember",
        )


if __name__ == "__main__":
    unittest.main()
