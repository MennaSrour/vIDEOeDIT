"""Silence cutting and voice/music filters."""
import math
import re

import ffmpeg

from core.media import INPUT_FORMATS, INPUT_PROTOCOLS, MediaError, run_command

SILENCE_EVENT = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)", re.I)


def kept_intervals(log, duration, padding=0.06):
    """Convert FFmpeg silence events to retained source ranges."""
    kept = []
    cursor = 0.0
    silence_start = None
    for event, timestamp in SILENCE_EVENT.findall(log):
        timestamp = min(duration, max(0.0, float(timestamp)))
        if event.lower() == "start":
            silence_start = timestamp
        elif silence_start is not None:
            left = silence_start + (padding if silence_start else 0.0)
            right = timestamp - (padding if timestamp < duration - 0.001 else 0.0)
            if right > left:
                if left > cursor:
                    kept.append((cursor, left))
                cursor = max(cursor, right)
            silence_start = None
    if silence_start is not None:
        duration = min(duration, silence_start + (padding if silence_start else 0.0))
    if duration > cursor:
        kept.append((cursor, duration))
    return kept


def prepare_video(source, output, info, *, trim, threshold, minimum):
    """Cut matching audio and video ranges before transcription."""
    if not trim or not info.has_audio:
        return source, None
    if not math.isfinite(threshold) or not -80 <= threshold <= -10 or not 0.1 <= minimum <= 5:
        raise MediaError("Invalid silence detection settings.")
    media = ffmpeg.input(str(source), format_whitelist=INPUT_FORMATS, protocol_whitelist=INPUT_PROTOCOLS)
    detect = ffmpeg.output(
        media["a:0"].filter("silencedetect", n=f"{threshold}dB", d=minimum),
        "-", f="null",
    )
    log = run_command(ffmpeg.compile(detect.global_args("-nostdin", "-hide_banner")))
    intervals = kept_intervals(log, info.duration)
    if not intervals:
        return source, "The audio was silent throughout. The original timeline was retained."
    if intervals == [(0.0, info.duration)]:
        return source, None

    # Split each stream explicitly, then use the same ranges for both tracks.
    video = media["V:0"].filter_multi_output("split") if len(intervals) > 1 else None
    padded = media["a:0"].filter("apad")
    audio = padded.filter_multi_output("asplit") if len(intervals) > 1 else None
    streams = []
    for index, (start, end) in enumerate(intervals):
        clip_video = (video[index] if video else media["V:0"]).trim(start=start, end=end)
        clip_audio = (audio[index] if audio else padded).filter("atrim", start=start, end=end)
        streams.extend((clip_video.setpts("PTS-STARTPTS"), clip_audio.filter("asetpts", "PTS-STARTPTS")))
    joined = ffmpeg.concat(*streams, v=1, a=1).node if len(intervals) > 1 else streams
    command = ffmpeg.output(
        joined[0], joined[1], str(output), vcodec="libx264", preset="ultrafast",
        crf=15, acodec="pcm_s16le", **{"filter_complex_threads": 2, "threads": 4},
    )
    run_command(ffmpeg.compile(command.global_args("-nostdin", "-hide_banner", "-loglevel", "error")))
    return output, None


def render_audio_command(info, duration, speed, loudness, music_index, volume):
    """Build the audio graph and label the final stereo output."""
    if not 1 <= speed <= 2 or not -24 <= loudness <= -12 or not 0 <= volume <= 0.3:
        raise MediaError("Invalid speed, loudness or music level.")
    audio_format = "aformat=sample_rates=48000:channel_layouts=stereo"
    finish = f"apad,atrim=duration={duration:.6f}"
    graph = []
    if info.has_audio:
        graph.append(
            f"[0:a:0]asetpts=PTS-STARTPTS,atempo={speed},"
            f"loudnorm=I={loudness}:TP=-1.5:LRA=7,{audio_format},{finish}[voice]"
        )
    if music_index is not None:
        graph.append(
            f"[{music_index}:a:0]asetpts=PTS-STARTPTS,{audio_format},"
            f"volume={volume},{finish}[music]"
        )
    if info.has_audio and music_index is not None:
        graph.extend([
            "[voice]asplit[main][side]",
            "[music][side]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=300[ducked]",
            "[main][ducked]amix=inputs=2:normalize=0,alimiter=limit=0.95:latency=1[aout]",
        ])
    elif info.has_audio or music_index is not None:
        source = "voice" if info.has_audio else "music"
        graph.append(f"[{source}]anull[aout]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,{finish}[aout]")
    return graph
