"""Font discovery, Unicode shaping, and safe-area graphics."""
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import arabic_reshaper
from bidi import get_display as unicode_display
from bidi.algorithm import get_display
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageDraw, ImageFont

from core.media import MediaError

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
CANVAS_WIDTH = 880
CAPTION_HEIGHT = 400
BADGE_HEIGHT = 128
RESHAPER = arabic_reshaper.ArabicReshaper(
    configuration={"delete_harakat": False, "shift_harakat_position": True},
)

FONT_NAMES = {
    "Bold": ("Cairo-Bold.ttf", "DejaVuSans-Bold.ttf", "segoeuib.ttf"),
    "Sans": ("Cairo-Regular.ttf", "DejaVuSans.ttf", "segoeui.ttf", "Arial.ttf"),
    "Arabic": ("Amiri-Regular.ttf", "Cairo-Regular.ttf", "DejaVuSans.ttf", "segoeui.ttf"),
}


def shape_text(text):
    reshaped = RESHAPER.reshape(text)
    try:
        return get_display(reshaped)
    except (AssertionError, KeyError):
        return unicode_display(reshaped)


@lru_cache(maxsize=1)
def installed_fonts():
    roots = (
        FONT_DIR, Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
        Path("/System/Library/Fonts"), Path("/Library/Fonts"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    )
    return tuple(
        path for root in roots if root.is_dir()
        for path in sorted(root.rglob("*")) if path.suffix.lower() in (".ttf", ".otf")
    )


@lru_cache(maxsize=128)
def font_codepoints(path):
    try:
        with TTFont(path, lazy=True) as font:
            return frozenset(font.getBestCmap() or ())
    except (OSError, TTLibError, ValueError):
        return frozenset()


def choose_font(style, text):
    custom = os.environ.get("REELSFORGE_FONT")
    fonts = installed_fonts()
    names = tuple(name.casefold() for name in FONT_NAMES[style])
    preferred = sorted(
        (path for path in fonts if path.name.casefold() in names),
        key=lambda path: names.index(path.name.casefold()),
    )
    candidates = [Path(custom)] if custom else []
    candidates.extend(preferred)
    candidates.extend(fonts)
    required = {
        ord(char) for char in shape_text(text)
        if not char.isspace() and unicodedata.category(char) != "Cf"
    }
    for path in candidates:
        if required <= font_codepoints(path):
            return path
    raise MediaError("No installed font covers the caption or badge glyphs. Add a compatible TTF "
                     "to assets/fonts or set REELSFORGE_FONT.")


def _wrap(draw, text, font, width):
    lines = []
    for paragraph in text.splitlines():
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(shape_text(candidate), font=font) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return [shape_text(line) for line in lines]


def build_pill(text, preset, path, *, badge=False):
    height = BADGE_HEIGHT if badge else CAPTION_HEIGHT
    image = Image.new("RGBA", (CANVAS_WIDTH, height))
    draw = ImageDraw.Draw(image)
    font_path = choose_font(preset.font_style, text)
    largest = min(preset.font_size, 49) if badge else preset.font_size
    for size in range(largest, 19, -2):
        font = ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.BASIC)
        lines = _wrap(draw, text, font, CANVAS_WIDTH - 68)
        gap = max(6, size // 8)
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        if not boxes:
            image.save(path)
            return
        widths = [right - left for left, _, right, _ in boxes]
        heights = [bottom - top for _, top, _, bottom in boxes]
        total_height = sum(heights) + gap * (len(lines) - 1)
        if max(widths) <= CANVAS_WIDTH - 68 and total_height <= height - 32:
            break
    else:
        raise MediaError("A caption or badge is too long to fit. Shorten it or split it into rows.")
    width = max(widths) + 60
    left = (CANVAS_WIDTH - width) // 2
    top = (height - total_height) // 2
    draw.rounded_rectangle(
        (left, top - 15, left + width, top + total_height + 15),
        radius=30 if badge else 24, fill=preset.box_color,
    )
    for line, (x_offset, y_offset, _, _), line_width, line_height in zip(
        lines, boxes, widths, heights, strict=True,
    ):
        draw.text(
            ((CANVAS_WIDTH - line_width) // 2 - x_offset, top - y_offset),
            line, font=font, fill=preset.text_color,
        )
        top += line_height + gap
    image.save(path)
