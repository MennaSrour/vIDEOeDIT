import json
import shutil
import subprocess

import pytest
from PIL import Image

from core.audio_processor import kept_intervals, prepare_video
from core.media import MediaInfo, probe
from core.preset_manager import PresetManager
from core.transcriber import Segment
from core.video_renderer import build_render_command, render_video


def test_silence_event_intervals():
    log = "silence_start: 0\nsilence_end: 0.5\nsilence_start: 1\nsilence_end: 1.8"
    assert kept_intervals(log, 2) == [(0.44, 1.06), (1.74, 2)]
    assert kept_intervals("silence_start: 0\nsilence_end: 2", 2) == []


def test_ffmpeg_command():
    preset = PresetManager().all()["Gym_High_Energy"]
    command = build_render_command(
        "my video.mp4", MediaInfo(8, True, True), "out.mp4", preset=preset,
        mode="blur", speed=2, music="music.mp3", captions="captions.ffconcat", badge="badge.png",
    )
    graph = command[command.index("-filter_complex") + 1]
    for token in (
        "boxblur=12:2", "scale=1080:1920", "atempo=2", "loudnorm=I=-14",
        "sidechaincompress", "[2:v:0]overlay", "[3:v:0]overlay",
    ):
        assert token in graph
    assert command[command.index("-t") + 1] == "4.000000"
    assert "my video.mp4" in command
    assert "libx264" in command and "aac" in command


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_render_reel_with_jump_cuts_and_timed_arabic_caption(tmp_path):
    source, cut, exported = (tmp_path / name for name in ("a.mp4", "cut.mkv", "reel.mp4"))
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=2.8",
        "-f", "lavfi", "-i", "aevalsrc=if(between(t\\,0.9\\,1.8)\\,0\\,0.4*sin(220*t)):d=2.8",
        "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True)
    prepared, _ = prepare_video(
        source, cut, probe(source), trim=True, threshold=-35, minimum=0.35,
    )
    info = probe(prepared)
    assert prepared == cut and 1.8 < info.duration < 2.2
    preset = PresetManager().all()["Gym_High_Energy"]
    updates = []
    render_video(
        cut, info, exported, segments=[Segment(0.4, 1.1, "سَلَام 42")], preset=preset,
        mode="blur", speed=1.25, music=source, badge_text="4 Sets • 12 Reps",
        progress=updates.append,
    )
    assert updates[-1] == 1.0
    streams = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(exported),
    ]))["streams"]
    assert streams[0]["codec_name"] == "h264"
    assert (streams[0]["width"], streams[0]["height"]) == (1080, 1920)
    assert streams[1]["codec_name"] == "aac"
    assert probe(exported).duration == pytest.approx(info.duration / 1.25, abs=0.07)

    def caption_pixel(at):
        frame = tmp_path / f"frame-{at}.png"
        subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(at), "-i", str(exported),
            "-frames:v", "1", "-threads", "1", str(frame),
        ], check=True)
        with Image.open(frame) as image:
            return image.getpixel((540, 1340))

    before, visible, after = (caption_pixel(at) for at in (0.1, 0.55, 1.15))
    assert before[2] > 200 and after[2] > 200
    assert visible[2] < 80
