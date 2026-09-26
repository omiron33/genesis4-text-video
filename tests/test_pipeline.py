import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import genesis4_video as video


SOURCE = Path(__file__).resolve().parents[1] / "source"


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lyrics = json.loads((SOURCE / "approved-lyrics.json").read_text(encoding="utf-8"))
        cls.timing = json.loads((SOURCE / "timing.machine.json").read_text(encoding="utf-8"))

    def test_full_chapter_lines_are_in_order(self):
        lines = video.lyric_lines(self.lyrics)
        self.assertEqual(len(lines), 95)
        self.assertEqual([x["verse"] for x in lines if x["line"] == 1], list(range(1, 27)))

    def test_machine_timing_covers_each_line_and_instrumental_outro(self):
        lines = video.lyric_lines(self.lyrics)
        events = video.check_timing(self.timing, lines, 312.02)
        self.assertEqual(events, self.timing["segments"])
        self.assertEqual(events[-1]["text"], "the name of the Lord God.")
        self.assertEqual(events[-1]["end"], 299)

    def test_missing_line_or_wrong_text_is_rejected(self):
        lines = video.lyric_lines(self.lyrics)
        bad = json.loads(json.dumps(self.timing))
        bad["segments"][25]["text"] = "something else"
        with self.assertRaisesRegex(ValueError, "exact sung lyric line"):
            video.check_timing(bad, lines, 312.02)

    def test_visual_frame(self):
        base = video.make_base((640, 360), None)
        events = video.check_timing(self.timing, video.lyric_lines(self.lyrics), 312.02)
        frame = video.make_frame(100.3, 312.02, events, [e["start"] for e in events], base, (640, 360), False)
        self.assertEqual(frame.size, (640, 360))
        self.assertEqual(frame.mode, "RGB")

    def test_immutable_copy_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, target = folder / "source", folder / "target"
            source.write_bytes(b"approved")
            digest = hashlib.sha256(b"approved").hexdigest()
            video.safe_copy(source, target, digest)
            video.safe_copy(source, target, digest)
            target.write_bytes(b"other")
            with self.assertRaisesRegex(ValueError, "Immutable destination differs"):
                video.safe_copy(source, target, digest)
            self.assertEqual(target.read_bytes(), b"other")


if __name__ == "__main__":
    unittest.main()
