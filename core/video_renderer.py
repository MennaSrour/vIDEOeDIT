"""Build and execute the vertical rendering pipeline."""
import math
import tempfile
from pathlib import Path

from PIL import Image

from core.audio_processor import render_audio_command
from core.media import INPUT_FORMATS, INPUT_PROTOCOLS, MediaError, run_command
from core.typography import CANVAS_WIDTH, CAPTION_HEIGHT, BADGE_HEIGHT, build_pill

WIDTH, HEIGHT, FPS = 1080, 1920, 30
REFRAMES = {
    "Smart Center Crop (9:16)": "crop",
    "Fit with Blurred Background (9:16)": "blur",
}


def caption_track(directory, segments, preset, speed, duration):
    """Write a sparse, frame-aligned timeline of transparent PNG overlays."""
    if not segments:
        return None
    blank = directory / "blank.png"
    Image.new("RGBA", (CANVAS_WIDTH, CAPTION_HEIGHT)).save(blank)
    events = {}
    last_frame = math.ceil(duration * FPS)
    for index, segment in enumerate(segments):
        start = min(last_frame, math.ceil(segment.start / speed * FPS))
        end = min(last_frame, math.ceil(segment.end / speed * FPS))
        if end <= start:
            continue
        name = f"caption-{index}.png"
        build_pill(segment.text, preset, directory / name)
        events.setdefault(start, [[], []])[0].append((index, name))
        events.setdefault(end, [[], []])[1].append(index)
    active = {}
    entries = [(0, blank.name)]
    for frame, (begins, ends) in sorted(events.items()):
        for index in ends:
            active.pop(index)
        active.update(begins)
        name = active[max(active)] if active else blank.name
        if frame == entries[-1][0]:
            entries[-1] = (frame, name)
        elif name != entries[-1][1]:
            entries.append((frame, name))

    track = directory / "captions.ffconcat"
    with track.open("w", encoding="ascii") as file:
        file.write("ffconcat version 1.0\n")
        for (start, name), (end, _) in zip(entries, entries[1:]):
            file.write(f"file {name}\noption framerate {FPS}\nduration {(end-start)/FPS:.9f}\n")
        file.write(f"file {entries[-1][1]}\noption framerate {FPS}\n")
    return track.resolve()


def build_render_command(source, info, output, *, preset, mode, speed, music=None,
                         captions=None, badge=None):
    if mode not in REFRAMES.values() or speed not in (1.0, 1.25, 1.5, 2.0):
        raise MediaError("Invalid reframe mode or playback speed.")
    duration = info.duration / speed
    input_flags = ["-format_whitelist", INPUT_FORMATS, "-protocol_whitelist", INPUT_PROTOCOLS]
    inputs = [*input_flags, "-i", str(source)]
    music_index = 1 if music and preset.music_volume else None
    if music_index:
        inputs.extend([*input_flags, "-stream_loop", "-1", "-i", str(music)])
    next_index = 1 + bool(music_index)
    # Convert anamorphic input to square pixels before computing the crop.
    video = f"[0:V:0]setpts=(PTS-STARTPTS)/{speed},fps={FPS},scale=trunc(iw*sar/2)*2:ih,setsar=1"
    out_size = f"{WIDTH}:{HEIGHT}"
    if mode == "crop":
        graph = [
            f"{video},scale={out_size}:force_original_aspect_ratio=increase:"
            f"force_divisible_by=2,crop={out_size},setsar=1[canvas]"
        ]
    else:
        graph = [
            f"{video},split=2[bg][fg]",
            f"[bg]scale=270:480:force_original_aspect_ratio=increase:force_divisible_by=2,"
            f"crop=270:480,boxblur=12:2,scale={out_size}[blur]",
            f"[fg]scale={out_size}:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2[fit]",
            "[blur][fit]overlay=(W-w)/2:(H-h)/2,setsar=1[canvas]",
        ]
    current = "canvas"
    if captions:
        inputs.extend(["-f", "concat", "-safe", "0", "-i", str(captions)])
        y = round(HEIGHT * preset.caption_position / 100 - CAPTION_HEIGHT / 2)
        graph.append(f"[{current}][{next_index}:v:0]overlay=(W-w)/2:{y}[captioned]")
        current = "captioned"
        next_index += 1
    if badge:
        inputs.extend(["-i", str(badge)])
        badge_y = 260 - BADGE_HEIGHT // 2
        graph.append(f"[{current}][{next_index}:v:0]overlay=(W-w)/2:{badge_y}[badged]")
        current = "badged"
    graph.extend(render_audio_command(
        info, duration, speed, preset.loudness, music_index, preset.music_volume / 100,
    ))
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex_threads", "2",
        "-filter_complex", ";".join(graph), "-map", f"[{current}]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-threads", "4",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{duration:.6f}", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(output),
    ]


def render_video(source, info, output, *, segments, preset, mode, speed,
                 music=None, badge_text="", progress=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reelsforge-", dir=output.parent) as workspace:
        directory = Path(workspace).resolve()
        captions = caption_track(directory, segments, preset, speed, info.duration / speed)
        badge = None
        if preset.badge and badge_text.strip():
            badge = directory / "badge.png"
            build_pill(badge_text.strip(), preset, badge, badge=True)
        pending = directory / "render.mp4"
        cmd = build_render_command(
            source, info, pending, preset=preset, mode=mode, speed=speed,
            music=music, captions=captions, badge=badge,
        )
        run_command(cmd, duration=info.duration / speed, progress=progress)
        pending.replace(output)
    if progress:
        progress(1.0)
    return output
