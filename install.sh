#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

missing=0
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Missing ffmpeg. Install with: brew install ffmpeg"
  missing=1
fi
if ! command -v osxphotos >/dev/null 2>&1; then
  echo "Missing osxphotos. Install with: pipx install osxphotos"
  missing=1
fi
if ! command -v exiftool >/dev/null 2>&1; then
  echo "Optional but recommended: exiftool. Install with: brew install exiftool"
fi

if [ "$missing" -eq 1 ]; then
  echo "Python deps installed, but system deps are missing."
fi
