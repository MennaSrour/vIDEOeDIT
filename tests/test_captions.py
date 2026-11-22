import pytest

from core.transcriber import parse_segments, parse_timestamp
from core.typography import shape_text


def test_mixed_arabic_english_shaping_preserves_latin_order():
    rendered = shape_text("سلام Set 42")
    assert rendered.startswith("Set 42")
    assert "ﻡﻼﺳ" in rendered
    assert shape_text("Hello 42") == "Hello 42"
    assert "\u064e" in shape_text("سَلَام")


@pytest.mark.parametrize(("value", "expected"), [("01:02:03,250", 3723.25), ("1.125", 1.125), (0, 0)])
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == expected


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "00:72:02", "abc", None])
def test_invalid_timestamp(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


def test_editor_parses_sorts_and_validates_rows():
    assert [entry.text for entry in parse_segments([
        {"Start": "2", "End": "3", "Text": "Later"},
        {"Start": "0", "End": "1", "Text": " First "},
        {"Start": None, "End": None, "Text": None},
    ], 3)] == ["First", "Later"]
    with pytest.raises(ValueError, match="Caption row 1"):
        parse_segments([{"Start": "1", "End": "4", "Text": "Out of range"}], 3)


def test_whisper_results_include_words_and_detected_language(monkeypatch):
    from types import SimpleNamespace

    import faster_whisper

    from core.transcriber import Segment, Word, transcribe

    class Model:
        def __init__(self, name, **kwargs):
            assert name == "test-model"
            assert kwargs["device"] == "cpu"

        def transcribe(self, path, **kwargs):
            assert path == "source.mp4"
            assert kwargs["language"] is None and kwargs["word_timestamps"]
            words = [SimpleNamespace(start=0.1, end=0.5, word="سلام")]
            return iter([SimpleNamespace(start=0.1, end=0.5, text=" سلام ", words=words)]), (
                SimpleNamespace(language="ar")
            )

    monkeypatch.setenv("REELSFORGE_WHISPER_MODEL", "test-model")
    monkeypatch.setattr(faster_whisper, "WhisperModel", Model)
    updates = []
    segments, language = transcribe("source.mp4", None, 2.0, updates.append)
    assert segments == [Segment(0.1, 0.5, "سلام", (Word(0.1, 0.5, "سلام"),))]
    assert language == "ar"
    assert updates == [0.25]
