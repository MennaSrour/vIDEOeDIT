"""Local Whisper and editable caption timecodes."""
import math
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()


def parse_timestamp(value):
    """Accept nonnegative decimal seconds or HH:MM:SS.mmm timecodes."""
    text = str(value).strip().replace(",", ".")
    match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        text = str(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    try:
        seconds = float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp {value!r}. Use seconds or HH:MM:SS.mmm.") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timestamps must be finite and nonnegative.")
    return seconds


def parse_segments(rows, duration):
    segments = []
    for index, row in enumerate(rows, start=1):
        text = row["Text"]
        if text is None or not str(text).strip():
            continue
        try:
            start, end = (parse_timestamp(row[key]) for key in ("Start", "End"))
            if not start < min(end, duration) or end > duration + 0.001:
                raise ValueError(f"Use Start < End within the {duration:.3f}s timeline.")
        except ValueError as exc:
            raise ValueError(f"Caption row {index}. {exc}") from exc
        segments.append(Segment(start, min(end, duration), str(text).strip()))
    return sorted(segments, key=lambda segment: segment.start)


def transcribe(path, language, duration, progress=None):
    from faster_whisper import WhisperModel

    model = WhisperModel(
        os.environ.get("REELSFORGE_WHISPER_MODEL", "base"),
        device="cpu", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 1),
    )
    segments, info = model.transcribe(
        str(path), language=language, word_timestamps=True, vad_filter=True, beam_size=5,
    )
    result = []
    for segment in segments:
        text = segment.text.strip()
        if text and segment.start < min(segment.end, duration):
            words = tuple(
                Word(word.start, word.end, word.word)
                for word in segment.words or () if word.start is not None and word.end is not None
            )
            result.append(Segment(segment.start, min(segment.end, duration), text, words))
        if progress:
            progress(min(1.0, segment.end / duration))
    return result, info.language
