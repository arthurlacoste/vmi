from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

fake_faster_whisper = types.ModuleType("faster_whisper")


class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


fake_faster_whisper.WhisperModel = FakeWhisperModel
sys.modules.setdefault("faster_whisper", fake_faster_whisper)


class PortableModuleTests(unittest.TestCase):
    def test_imports_do_not_require_macos_runtime(self):
        importlib.import_module("search_shorts")
        importlib.import_module("recall_video")
        importlib.import_module("transcribe_videos")

    def test_recall_finds_asset_by_sha256_and_path(self):
        recall_video = importlib.import_module("recall_video")
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            con = sqlite3.connect(db_path)
            con.execute(
                """
                CREATE TABLE assets (
                  source_id TEXT PRIMARY KEY,
                  source_kind TEXT NOT NULL,
                  original_filename TEXT,
                  creation_date TEXT,
                  exported_path TEXT,
                  sha256 TEXT,
                  duration_seconds REAL,
                  status TEXT NOT NULL,
                  transcript_json TEXT,
                  transcript_txt TEXT,
                  transcript_srt TEXT,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            video_path = Path(tmp) / "video.mov"
            transcript_path = Path(tmp) / "transcription" / "video_abcd1234.json"
            con.execute(
                """
                INSERT INTO assets (
                    source_id, source_kind, original_filename, exported_path, sha256,
                    duration_seconds, status, transcript_json, transcript_srt, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "file:/tmp/video.mov",
                    "manual_file",
                    "video.mov",
                    str(video_path),
                    "abc123",
                    42.0,
                    "done",
                    str(transcript_path),
                    str(transcript_path.with_suffix(".srt")),
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            con.commit()

            by_hash = recall_video.recall(con, "abc123")
            by_path = recall_video.recall(con, str(video_path))

            self.assertIsNotNone(by_hash)
            self.assertEqual(by_hash["source_id"], "file:/tmp/video.mov")
            self.assertEqual(by_path["transcript_json"], str(transcript_path))

    def test_local_transcription_dir_and_speaker_text(self):
        transcribe_videos = importlib.import_module("transcribe_videos")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "clip.mov"
            fallback = Path(tmp) / "global_transcripts"
            cfg = {
                "transcription": {
                    "local_transcription_subdir": True,
                    "local_transcription_subdir_name": "transcription",
                }
            }

            out_dir = transcribe_videos.transcription_output_dir(cfg, "manual_file", source, fallback)
            self.assertEqual(out_dir, Path(tmp) / "transcription")
            self.assertEqual(
                transcribe_videos.segment_text({"speaker": "Speaker 1", "text": "Bonjour"}),
                "Speaker 1: Bonjour",
            )

    def test_write_transcripts_defaults_json_and_srt_shape(self):
        transcribe_videos = importlib.import_module("transcribe_videos")
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            outputs = transcribe_videos.write_transcripts(
                "clip_abcd1234",
                [{"start": 0.0, "end": 1.5, "text": "Bonjour", "speaker": "Speaker 1"}],
                {"source_id": "file:/tmp/clip.mov"},
                out,
                ["srt", "json"],
            )

            self.assertEqual(set(outputs), {"transcript_srt", "transcript_json"})
            json_data = json.loads(Path(outputs["transcript_json"]).read_text(encoding="utf-8"))
            srt_text = Path(outputs["transcript_srt"]).read_text(encoding="utf-8")
            self.assertEqual(json_data["segments"][0]["speaker"], "Speaker 1")
            self.assertIn("Speaker 1: Bonjour", srt_text)

    def test_chatgpt_file_url_is_absolute(self):
        search_shorts = importlib.import_module("search_shorts")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a file.json"
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(search_shorts.file_url(path).startswith("file://"))
            self.assertIn("a%20file.json", search_shorts.file_url(path))


if __name__ == "__main__":
    unittest.main()
