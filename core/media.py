"""Shared FFmpeg execution and stream inspection."""
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


# Restrict user inputs to media demuxers that do not follow playlist references.
INPUT_FORMATS = "mov,matroska,webm,mp3,wav,aac,ogg,flac"
INPUT_PROTOCOLS = "file,pipe"


class MediaError(RuntimeError):
    """An actionable failure in the media pipeline."""


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_audio: bool
    has_video: bool


def check_tools():
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise MediaError(
            f"Missing {', '.join(missing)}. Install FFmpeg with ffprobe, add its bin "
            "directory to PATH, then restart ReelsForge. See README.md for platform commands."
        )


def run_command(command, *, cwd=None, duration=None, progress=None):
    """Run without a shell. Stream progress and keep diagnostics off the pipe."""
    try:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as errors:
            with subprocess.Popen(
                command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=errors, text=True, encoding="utf-8", errors="replace",
            ) as process:
                try:
                    for line in process.stdout:
                        key, _, value = line.strip().partition("=")
                        if progress and duration and key == "out_time_us":
                            if value.lstrip("-").isdigit():
                                progress(max(0.0, min(0.99, int(value) / 1_000_000 / duration)))
                    code = process.wait()
                finally:
                    if process.poll() is None:
                        process.kill()
            errors.seek(0)
            diagnostics = errors.read()
    except OSError as exc:
        raise MediaError(f"Could not run {Path(command[0]).name}: {exc}") from exc
    if code:
        raise MediaError(f"{Path(command[0]).name} failed: {diagnostics.strip()[-2500:]}")
    return diagnostics


def probe(path):
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-format_whitelist", INPUT_FORMATS,
                "-protocol_whitelist", INPUT_PROTOCOLS, "-show_entries",
                "stream=codec_type,duration:stream_disposition=attached_pic:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, timeout=30,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        videos = [
            stream for stream in streams
            if stream["codec_type"] == "video"
            and not stream.get("disposition", {}).get("attached_pic", 0)
        ]
        audio = [stream for stream in streams if stream["codec_type"] == "audio"]
        primary = (videos or audio)[0]
        value = primary.get("duration")
        if value in (None, "N/A"):
            value = data.get("format", {}).get("duration")
        duration = float(value)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid duration")
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, IndexError, KeyError) as exc:
        raise MediaError("Could not read the media streams or duration. Check the uploaded file.") from exc
    return MediaInfo(duration, bool(audio), bool(videos))
