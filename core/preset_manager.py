"""Validated preset storage with locked, atomic writes."""
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from filelock import FileLock

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "presets.json"


@dataclass(frozen=True)
class Preset:
    font_size: int
    text_color: str
    box_color: str
    caption_position: int
    silence_threshold: int
    min_silence: float
    badge: bool
    music_volume: int
    loudness: int
    font_style: str
    language: str = "Auto-detect"

    def __post_init__(self):
        for name, lower, upper in (
            ("font_size", 28, 96), ("caption_position", 40, 82),
            ("silence_threshold", -80, -10), ("min_silence", 0.10, 5.0),
            ("music_volume", 0, 30), ("loudness", -24, -12),
        ):
            value = getattr(self, name)
            types = (int, float) if name == "min_silence" else (int,)
            if type(value) not in types or not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}.")
        for color in (self.text_color, self.box_color):
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("Preset colors must use #RRGGBB notation.")
        if type(self.badge) is not bool or self.font_style not in ("Bold", "Sans", "Arabic"):
            raise ValueError("Invalid badge or font style.")
        if self.language not in ("Auto-detect", "Arabic", "English"):
            raise ValueError("Invalid caption language.")


class PresetManager:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.lock = FileLock(self.path.with_suffix(".lock"), timeout=5)

    def all(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {name: Preset(**fields) for name, fields in data.items()}
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid presets file: {self.path.name}. {exc}") from exc

    def _write(self, presets):
        payload = {name: asdict(preset) for name, preset in presets.items()}
        pending = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=".presets-", delete=False,
            ) as output:
                pending = Path(output.name)
                json.dump(payload, output, indent=2, ensure_ascii=False)
                output.write("\n")
            pending.replace(self.path)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)

    @staticmethod
    def _validate_name(name):
        name = name.strip()
        if not name or len(name) > 64 or not all(
            char.isalnum() or char in " _-" for char in name
        ):
            raise ValueError("Use 1–64 letters, numbers, spaces, underscores or hyphens.")
        return name

    def create(self, name, preset):
        return self._save(name, preset, create=True)

    def update(self, name, preset):
        return self._save(name, preset, create=False)

    def _save(self, name, preset, *, create):
        name = self._validate_name(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            presets = self.all()
            if create and name in presets:
                raise ValueError(f"Preset {name!r} already exists.")
            if not create and name not in presets:
                raise ValueError(f"Preset {name!r} no longer exists.")
            presets[name] = preset
            self._write(presets)
        return name

    def duplicate(self, source, name):
        name = self._validate_name(name)
        with self.lock:
            presets = self.all()
            if source not in presets or name in presets:
                raise ValueError("Choose an existing source and an unused preset name.")
            presets[name] = presets[source]
            self._write(presets)
        return name

    def delete(self, name):
        with self.lock:
            presets = self.all()
            if name not in presets:
                raise ValueError(f"Preset {name!r} no longer exists.")
            if len(presets) == 1:
                raise ValueError("Keep at least one preset.")
            del presets[name]
            self._write(presets)
