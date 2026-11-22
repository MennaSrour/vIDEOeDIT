"""ReelsForge's local Streamlit entry point."""
import json
import logging
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
from filelock import Timeout

from core.audio_processor import prepare_video
from core.media import MediaError, check_tools, probe
from core.preset_manager import PresetManager
from core.transcriber import parse_segments, transcribe
from core.video_renderer import REFRAMES, render_video

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
LANGUAGES = {"Auto-detect": None, "Arabic": "ar", "English": "en"}
LOGGER = logging.getLogger(__name__)

CSS = """
<style>
[data-testid="stMainBlockContainer"] {max-width: 67rem; padding-top: 2.5rem;}
.rf-title {font-size: clamp(2.9rem, 7vw, 5.2rem); letter-spacing: -.075em;
  line-height: 1; font-weight: 800; color: #f5f3ec; padding-bottom: .45rem;}
.rf-title span {color: #d9f96a;}
.rf-intro {color: #bfc8b4; margin-bottom: 1.5rem; font-size: 1.05rem;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color: #354133; border-radius: 1rem;}
input[type="text"], textarea {unicode-bidi: plaintext; text-align: start;}
</style>
"""


def apply_preset_action(manager, action, selected, name, edited):
    if action == "Update selected":
        return manager.update(selected, edited)
    if action == "Save as new":
        return manager.create(name, edited)
    if action == "Duplicate saved preset":
        return manager.duplicate(selected, name)
    manager.delete(selected)
    return next(iter(manager.all()))


def preset_studio(manager, selected, base):
    prefix = f"studio:{selected}:{st.session_state.get('preset_revision', 0)}"
    with st.expander("Customize / Create New Preset"):
        first, second, third = st.columns(3)
        edited = replace(
            base,
            font_size=first.slider("Caption font size", 28, 96, base.font_size, key=prefix + ":size"),
            text_color=second.color_picker("Text color", base.text_color, key=prefix + ":text"),
            box_color=third.color_picker("Pill color", base.box_color, key=prefix + ":box"),
            caption_position=first.slider(
                "Caption height (% from top)", 40, 82, base.caption_position,
                key=prefix + ":position",
            ),
            silence_threshold=second.slider(
                "Silence threshold (dB)", -80, -10, base.silence_threshold,
                key=prefix + ":threshold",
            ),
            min_silence=third.slider(
                "Minimum silence (seconds)", 0.1, 5.0, float(base.min_silence), 0.05,
                key=prefix + ":minimum",
            ),
            font_style=first.selectbox(
                "Font style", ("Bold", "Sans", "Arabic"),
                index=("Bold", "Sans", "Arabic").index(base.font_style), key=prefix + ":style",
            ),
            loudness=second.slider(
                "Voice target (LUFS)", -24, -12, base.loudness, key=prefix + ":loudness",
            ),
            badge=third.toggle("Enable top badge", value=base.badge, key=prefix + ":badge"),
            music_volume=third.slider(
                "Preset track volume (%)", 0, 30, base.music_volume, key=prefix + ":music",
            ),
            language=first.selectbox(
                "Preset caption language", tuple(LANGUAGES),
                index=tuple(LANGUAGES).index(base.language), key=prefix + ":language",
            ),
        )
        st.caption("Studio changes apply to this reel immediately. Save them to reuse the look.")
        with st.form(prefix + ":save"):
            actions = ("Update selected", "Save as new", "Duplicate saved preset", "Delete selected")
            action = st.selectbox("Preset action", actions)
            name = st.text_input("Name for new or duplicate preset", max_chars=64)
            confirm = st.checkbox("Confirm deletion")
            if st.form_submit_button("Apply preset action"):
                try:
                    if action == "Delete selected" and not confirm:
                        raise ValueError("Confirm deletion before applying this action.")
                    st.session_state.next_preset = apply_preset_action(
                        manager, action, selected, name, edited,
                    )
                except (OSError, ValueError, Timeout) as exc:
                    st.error(str(exc))
                else:
                    st.session_state.preset_revision = st.session_state.get("preset_revision", 0) + 1
                    st.session_state.preset_notice = "Preset changes saved."
                    st.rerun()
    return edited, prefix


def write_upload(upload, directory, kind):
    suffix = Path(upload.name).suffix.lower()
    path = directory / f"{kind}{suffix}"
    with path.open("wb") as output:
        output.write(upload.getbuffer())
    return path


def prepare_upload(upload, directory, preset, trim):
    source = write_upload(upload, directory, "source")
    info = probe(source)
    if not info.has_video:
        raise MediaError("Upload a file with a playable video stream.")
    prepared, notice = prepare_video(
        source, directory / "prepared.mkv", info, trim=trim,
        threshold=preset.silence_threshold, minimum=preset.min_silence,
    )
    if trim and not info.has_audio:
        notice = "This clip has no audio stream. The original timeline was retained."
    return prepared, probe(prepared) if prepared != source else info, notice


def prepare_editor(upload, preset, trim, captions, language, signature):
    bar = st.progress(0.0, text="Preparing the video timeline…")
    try:
        with tempfile.TemporaryDirectory(prefix="reelsforge-") as workspace:
            source, info, notice = prepare_upload(upload, Path(workspace), preset, trim)
            segments = []
            detected = None
            if captions and info.has_audio:
                bar.progress(0.2, text="Loading the local Whisper model and transcribing…")
                segments, detected = transcribe(
                    source, LANGUAGES[language], info.duration,
                    lambda value: bar.progress(0.2 + value * 0.8, text="Transcribing audio…"),
                )
            elif captions:
                notice = "This clip has no audio stream. You can add captions manually."
        st.session_state.prepared = {
            "signature": signature, "duration": info.duration, "notice": notice,
            "segments": segments, "language": detected, "version": uuid4().hex,
        }
        st.session_state.pop("export", None)
        bar.progress(1.0, text="Caption editor ready")
    except (MediaError, OSError, ValueError) as exc:
        bar.empty()
        st.error(str(exc))
    except Exception:
        bar.empty()
        LOGGER.exception("Local transcription failed")
        st.error(
            "Local transcription failed. Check the Whisper model path or download access. "
            "See the terminal log for details."
        )


def edit_captions(prepared):
    st.caption(
        f"Timeline: {prepared['duration']:.3f} s after jump cuts, before playback speed. "
        "Add or delete rows, and use seconds or HH:MM:SS.mmm."
    )
    if prepared["notice"]:
        st.info(prepared["notice"])
    if prepared["language"]:
        st.caption(f"Whisper language: {prepared['language'].upper()}")
    rows = [
        {"Start": f"{segment.start:.3f}", "End": f"{segment.end:.3f}", "Text": segment.text}
        for segment in prepared["segments"]
    ]
    # An explicit string schema also keeps the initially empty table editable.
    rows = st.data_editor(
        pd.DataFrame(rows, columns=["Start", "End", "Text"], dtype="string"),
        num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "Start": st.column_config.TextColumn("Start", required=True),
            "End": st.column_config.TextColumn("End", required=True),
            "Text": st.column_config.TextColumn("Caption / الترجمة", width="large"),
        },
        column_order=("Start", "End", "Text"), key="editor:" + prepared["version"],
    )
    if prepared["segments"]:
        st.download_button(
            "Download Whisper timestamps",
            json.dumps([asdict(segment) for segment in prepared["segments"]], ensure_ascii=False, indent=2),
            file_name="whisper-timestamps.json", mime="application/json",
        )
    records = rows.astype(object).where(rows.notna(), None).to_dict("records")
    try:
        edited = parse_segments(records, prepared["duration"])
    except ValueError:
        pass
    else:
        if edited:
            st.download_button(
                "Download edited captions",
                json.dumps([asdict(segment) for segment in edited], ensure_ascii=False, indent=2),
                file_name="edited-captions.json", mime="application/json",
            )
    return records


def export_reel(upload, soundtrack, preset, trim, rows, mode, speed, badge_text, render_settings):
    bar = st.progress(0.0, text="Preparing media…")
    try:
        with tempfile.TemporaryDirectory(prefix="reelsforge-") as workspace:
            directory = Path(workspace)
            source, info, _ = prepare_upload(upload, directory, preset, trim)
            segments = parse_segments(rows, info.duration)
            music = None
            if soundtrack and preset.music_volume:
                music = write_upload(soundtrack, directory, "music")
                if not probe(music).has_audio:
                    raise MediaError("The soundtrack does not contain an audio stream.")
            export = ROOT / "exports" / f"reel-{uuid4().hex[:12]}.mp4"
            render_video(
                source, info, export, segments=segments, preset=preset, mode=mode,
                speed=speed, music=music, badge_text=badge_text,
                progress=lambda value: bar.progress(0.1 + value * 0.9, text="Rendering your reel…"),
            )
        st.session_state.export = (render_settings, export)
        bar.progress(1.0, text="Export complete")
    except (MediaError, OSError, ValueError) as exc:
        bar.empty()
        st.error(str(exc))


def main():
    st.set_page_config(page_title="ReelsForge", page_icon="🎬", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="rf-title">Reels<span>Forge</span></div>'
        '<p class="rf-intro">Edit vertical videos locally. Cut pauses, refine captions, and export.</p>',
        unsafe_allow_html=True,
    )
    try:
        check_tools()
        manager = PresetManager()
        presets = manager.all()
        if not presets:
            raise ValueError("No presets were found. Restore config/presets.json from the checkout.")
    except (MediaError, OSError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    with st.container(border=True):
        st.header("1. Upload & configure")
        media_column, options_column = st.columns([3, 2], gap="large")
        with media_column:
            upload = st.file_uploader("Source video", type=("mp4", "mov", "mkv"))
            soundtrack = st.file_uploader(
                "Background audio (optional)", type=("mp3", "wav", "m4a", "aac", "ogg", "flac"),
            )
        with options_column:
            if "next_preset" in st.session_state:
                st.session_state.selected = st.session_state.pop("next_preset")
            selected = st.selectbox("Visual preset", tuple(presets), key="selected")
            mode = st.selectbox("Vertical reframe", tuple(REFRAMES))
            speed = st.select_slider(
                "Playback speed", options=(1.0, 1.25, 1.5, 2.0),
                format_func=lambda value: f"{value:g}×",
            )
        if notice := st.session_state.pop("preset_notice", None):
            st.success(notice)
        preset, prefix = preset_studio(manager, selected, presets[selected])
        if soundtrack:
            volume = st.slider("Background volume (%)", 0, 30, preset.music_volume, key=prefix + ":mix")
            preset = replace(preset, music_volume=volume)
        badge = st.text_input("Top safe-zone badge", max_chars=100, placeholder="450 kcal • 42g Protein",
                              disabled=not preset.badge)

    with st.container(border=True):
        st.header("2. Process & edit captions")
        left, middle, right = st.columns(3)
        trim = left.toggle("Auto-remove silence", value=True)
        captions = middle.toggle("Auto-generate captions", value=True)
        language = right.selectbox(
            "Spoken language", tuple(LANGUAGES), index=tuple(LANGUAGES).index(preset.language),
            disabled=not captions, key=prefix + ":spoken:" + preset.language,
        )
        file_id = upload.file_id if upload else None
        signature = (
            file_id, trim, (preset.silence_threshold, preset.min_silence) if trim else None,
            captions, language if captions else None,
        )
        if st.button("Prepare timeline", type="primary", disabled=upload is None):
            prepare_editor(upload, preset, trim, captions, language, signature)
        prepared = st.session_state.get("prepared")
        ready = upload is not None and prepared is not None and prepared["signature"] == signature
        rows = edit_captions(prepared) if ready else []
        if upload and not ready:
            st.caption("Prepare the timeline to add, edit, or remove caption rows.")

    with st.container(border=True):
        st.header("3. Render & export")
        st.caption("1080 × 1920 · 30 fps · H.264 / AAC")
        render_settings = (
            signature, soundtrack.file_id if soundtrack else None, preset, mode, speed, badge, rows,
        )
        if st.button("Render reel", type="primary", disabled=not ready):
            st.session_state.pop("export", None)
            export_reel(
                upload, soundtrack, preset, trim, rows, REFRAMES[mode], speed, badge, render_settings,
            )
        saved_settings, export = st.session_state.get("export", (None, None))
        if ready and render_settings == saved_settings and export.is_file():
            st.video(str(export))
            with export.open("rb") as video:
                st.download_button("Download MP4", video, file_name=export.name, mime="video/mp4")
            st.caption(f"Saved in exports/{export.name}")


if __name__ == "__main__":
    main()
