#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
for tool in ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null; then
    printf 'Install FFmpeg (including ffprobe) and add it to PATH. See README.md.\n' >&2
    exit 1
  fi
done
python_command="${REELSFORGE_PYTHON:-python3}"
if [[ ! -x .venv/bin/python ]]; then
  "$python_command" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
if [[ "${1:-}" == "--setup-only" ]]; then
  exit 0
fi
exec .venv/bin/python -m streamlit run app.py --server.address "${REELSFORGE_BIND:-127.0.0.1}" "$@"
