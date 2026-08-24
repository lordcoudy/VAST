from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import materialize_kpp_legacy_iss_v2_model_corpus as corpus  # noqa: E402


FFPROBE_FIXTURE = FIXTURES / "kpp_v2_ffprobe_recorded.json"
SHOWINFO_FIXTURE = FIXTURES / "kpp_v2_ffmpeg_showinfo_recorded.txt"


class ModelCorpusGatewayParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.media = SimpleNamespace(
            path=Path(r"C:\synthetic-only\iss_v2_underbody.mp4"),
            codec="h264",
            role="underbody",
        )
        self.context = object()

    def test_ffprobe_gateway_command_and_recorded_json_are_parsed(self) -> None:
        stdout = FFPROBE_FIXTURE.read_bytes()
        calls: list[tuple[list[str], object, str, int | None]] = []

        def gateway(
            command: list[str],
            *,
            context: object,
            policy_id: str,
            exact_stdout_limit_bytes: int | None = None,
        ) -> subprocess.CompletedProcess[bytes]:
            calls.append((command, context, policy_id, exact_stdout_limit_bytes))
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

        tool = Path(r"C:\synthetic-only\ffprobe.exe")
        with mock.patch.object(corpus, "_run_sanitized_subprocess", side_effect=gateway):
            probe = corpus._run_ffprobe(self.media, tool, self.context)

        self.assertEqual(
            calls,
            [
                (
                    [
                        str(tool),
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-count_frames",
                        "-show_entries",
                        "stream=index,codec_name,width,height,time_base,nb_read_frames:frame=stream_index,best_effort_timestamp",
                        "-show_frames",
                        "-of",
                        "json",
                        str(self.media.path),
                    ],
                    self.context,
                    "ffprobe_frame_catalog",
                    None,
                )
            ],
        )
        self.assertEqual(
            probe,
            corpus.MediaProbe(
                codec="h264",
                width=2,
                height=2,
                stream_index=0,
                time_base="1/600",
                frame_count=4,
                frame_pts=(0, 1, 2, 3),
            ),
        )

    def test_ffmpeg_gateway_command_and_recorded_showinfo_are_parsed(self) -> None:
        stderr = SHOWINFO_FIXTURE.read_bytes()
        rgb = bytes(range(24))
        calls: list[tuple[list[str], object, str, int | None]] = []

        def gateway(
            command: list[str],
            *,
            context: object,
            policy_id: str,
            exact_stdout_limit_bytes: int | None = None,
        ) -> subprocess.CompletedProcess[bytes]:
            calls.append((command, context, policy_id, exact_stdout_limit_bytes))
            return subprocess.CompletedProcess(command, 0, stdout=rgb, stderr=stderr)

        probe = corpus.MediaProbe(
            codec="h264",
            width=2,
            height=2,
            stream_index=0,
            time_base="1/600",
            frame_count=4,
            frame_pts=(0, 1, 2, 3),
        )
        indexes = (1, 3)
        tool = Path(r"C:\synthetic-only\ffmpeg.exe")
        with mock.patch.object(corpus, "_run_sanitized_subprocess", side_effect=gateway):
            frames = corpus._run_ffmpeg_decode(
                self.media,
                indexes,
                probe,
                tool,
                self.context,
            )

        self.assertEqual(
            calls,
            [
                (
                    [
                        str(tool),
                        "-hide_banner",
                        "-loglevel",
                        "info",
                        "-nostdin",
                        "-i",
                        str(self.media.path),
                        "-map",
                        "0:v:0",
                        "-an",
                        "-sn",
                        "-dn",
                        "-vf",
                        "select=eq(n\\,1)+eq(n\\,3),showinfo,settb=expr=1/1000000000,showinfo",
                        "-fps_mode",
                        "passthrough",
                        "-pix_fmt",
                        "rgb24",
                        "-f",
                        "rawvideo",
                        "pipe:1",
                    ],
                    self.context,
                    "ffmpeg_selected_frame_decode",
                    len(rgb),
                )
            ],
        )
        self.assertEqual(set(frames), {1, 3})
        self.assertEqual(frames[1].rgb, bytes(range(12)))
        self.assertEqual(frames[3].rgb, bytes(range(12, 24)))
        self.assertEqual((frames[1].source_pts, frames[1].pts_ns), (1, 1_666_667))
        self.assertEqual((frames[3].source_pts, frames[3].pts_ns), (3, 5_000_000))
        self.assertEqual(
            corpus._validated_frames(
                frames,
                indexes=indexes,
                probe=probe,
                media=self.media,
            ),
            frames,
        )

    def test_ffmpeg_showinfo_partial_second_component_fails_closed(self) -> None:
        lines = SHOWINFO_FIXTURE.read_text(encoding="utf-8").splitlines()
        partial_lines = [
            line
            for line in lines
            if not ("Parsed_showinfo_3" in line and "n:   1" in line)
        ]
        self.assertEqual(len(partial_lines), len(lines) - 1)
        partial = "\n".join(partial_lines).encode("utf-8")

        def gateway(
            command: list[str],
            *,
            context: object,
            policy_id: str,
            exact_stdout_limit_bytes: int | None = None,
        ) -> subprocess.CompletedProcess[bytes]:
            self.assertEqual(policy_id, "ffmpeg_selected_frame_decode")
            self.assertEqual(exact_stdout_limit_bytes, 24)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=bytes(range(24)),
                stderr=partial,
            )

        probe = corpus.MediaProbe(
            codec="h264",
            width=2,
            height=2,
            stream_index=0,
            time_base="1/600",
            frame_count=4,
            frame_pts=(0, 1, 2, 3),
        )
        with mock.patch.object(corpus, "_run_sanitized_subprocess", side_effect=gateway):
            with self.assertRaisesRegex(
                corpus.ModelCorpusError,
                "ffmpeg decoded frame/PTS coverage is partial",
            ):
                corpus._run_ffmpeg_decode(
                    self.media,
                    (1, 3),
                    probe,
                    Path(r"C:\synthetic-only\ffmpeg.exe"),
                    self.context,
                )


if __name__ == "__main__":
    unittest.main()
