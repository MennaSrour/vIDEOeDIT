# ReelsForge

ReelsForge is a local Streamlit editor for Instagram Reels. It cuts pauses,
transcribes Arabic or English, and exports vertical MP4s with burned-in captions,
optional safe-zone badges, and ducked soundtrack audio.

## Install and launch

1. Install **Python 3.11 or 3.12** and **FFmpeg 5.1+** with `ffprobe`, H.264
   (`libx264`), and AAC. Open a new terminal after updating PATH.

   | Platform | FFmpeg and fonts |
   | --- | --- |
   | Windows | `winget install --id Gyan.FFmpeg -e`. Segoe UI is normally preinstalled. |
   | macOS | `brew install ffmpeg`. If needed, install Cairo or Amiri in Font Book or copy a compatible TTF into `assets/fonts/`. |
   | Debian / Ubuntu | `sudo apt install ffmpeg fonts-dejavu-core python3-venv`. |

   Confirm with `ffmpeg -version` and `ffprobe -version`. See
   [font setup](assets/fonts/README.md) for custom Arabic fonts.

2. From the repository root, run `./scripts/setup_and_run.sh` on Linux or macOS,
   or `scripts\setup_and_run.bat` on Windows. Each script creates `.venv`,
   installs the pinned dependencies, and starts Streamlit. Use `--setup-only`
   to install without launching.
3. Open **http://127.0.0.1:8501**. The start scripts bind to loopback by
   default. Stop the server with Ctrl+C.

Whisper runs locally on the CPU. On first use, automatic captions download the
multilingual Faster Whisper `base` model from Hugging Face into
`.cache/huggingface/`. Set `REELSFORGE_WHISPER_MODEL` to the absolute path of a
complete Faster Whisper CTranslate2 model directory for offline use. You can
also set it to another supported multilingual model size, such as `small`.
Videos and soundtracks are processed on the machine running Streamlit.

## Edit a reel

1. Upload an MP4, MOV, or MKV and optionally add an audio track. Select a preset,
   choose a center crop or blurred background, and select a fixed playback speed
   between 1× and 2×. Enable the badge in the preset studio to add text above the
   picture’s main content. The soundtrack loops when needed and ducks under
   the source voice. A 0% track level omits the soundtrack.
2. Choose whether to remove silence and generate captions. Select Arabic,
   English, or auto-detect, then click **Prepare timeline**. In the editor,
   change text, adjust start/end timestamps, add rows, or select rows and press
   Delete. Timecodes use decimal seconds or `HH:MM:SS.mmm` on the post-cut
   timeline. Overlapping captions show the one with the latest start.
   You can download original segment/word timestamps and edited caption
   segments as JSON. Turn automatic captions off to enter captions manually.
3. Click **Render reel**. Playback speed applies to both source audio and
   caption timing. Preview or download the 1080 × 1920, 30 fps H.264/AAC MP4.
   Completed files remain in `exports/`. Temporary media is cleaned up after
   each operation.

Use **Customize / Create New Preset** to change typography, color, vertical
placement, silence thresholds, audio targets, and defaults. Update the selected
preset, save your changes as a new preset, duplicate a saved preset, or delete
one. Saved presets are shared by sessions on the same installation. Preset
changes persist in `config/presets.json`.

## Development checks

With the virtual environment activated:

```sh
python -m pytest
ruff check .
python -m compileall -q app.py core tests
python -m pip check
```

The media integration tests use generated clips. Install FFmpeg and a compatible
Arabic font to run the full suite. The rest of the suite needs no model weights.
