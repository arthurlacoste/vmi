#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Full macOS VMI pipeline test

Usage:
  scripts/test_macos_full.sh --video /absolute/path/to/video.mov

What this checks:
  - running on macOS
  - Python virtualenv installation
  - ffmpeg availability
  - osxphotos availability
  - exiftool availability, optional but reported
  - portable unit tests
  - manual file registration
  - transcription pipeline on the provided video
  - direct recall by file path
  - search index rebuild
  - shorts package generation
  - ChatGPT prompt URL generation

This script intentionally needs a real local video with audio because it validates the full runtime path.
EOF
}

VIDEO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --video)
      VIDEO="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$VIDEO" ]; then
  echo "Missing --video /absolute/path/to/video.mov" >&2
  usage >&2
  exit 2
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This full pipeline test must run on macOS." >&2
  exit 1
fi

VIDEO_PATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$VIDEO")"
if [ ! -f "$VIDEO_PATH" ]; then
  echo "Video file not found: $VIDEO_PATH" >&2
  exit 1
fi

case "${VIDEO_PATH##*.}" in
  mov|MOV|mp4|MP4|m4v|M4V) ;;
  *)
    echo "Unsupported video extension: $VIDEO_PATH" >&2
    exit 1
    ;;
esac

if [ ! -f .venv/bin/activate ]; then
  ./install.sh
fi
. .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
python -m pip install PyYAML >/dev/null

missing=0
for command in ffmpeg ffprobe osxphotos; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    missing=1
  fi
done
if ! command -v exiftool >/dev/null 2>&1; then
  echo "Optional command missing: exiftool"
fi
if [ "$missing" -eq 1 ]; then
  exit 1
fi

python -m compileall bin tests
python -m unittest discover -s tests -p 'test_*.py'

./run.sh --add-file "$VIDEO_PATH"
./run.sh --max 0

./run.sh --recall "$VIDEO_PATH"
./run.sh --index
./run.sh --select-video "$VIDEO_PATH"

SOURCE_ID="file:$VIDEO_PATH"
SHORTS_DIR="data/shorts/${SOURCE_ID//\//_}"
SHORTS_DIR="${SHORTS_DIR//:/_}"

if [ ! -f "$SHORTS_DIR/chatgpt_prompt.txt" ]; then
  echo "Missing generated prompt file: $SHORTS_DIR/chatgpt_prompt.txt" >&2
  exit 1
fi

if [ ! -f "$SHORTS_DIR/chatgpt_url.txt" ]; then
  echo "Missing generated ChatGPT URL file: $SHORTS_DIR/chatgpt_url.txt" >&2
  exit 1
fi

TRANSCRIPTION_DIR="$(dirname "$VIDEO_PATH")/transcription"
if [ ! -d "$TRANSCRIPTION_DIR" ]; then
  echo "Missing local transcription folder: $TRANSCRIPTION_DIR" >&2
  exit 1
fi

if ! ls "$TRANSCRIPTION_DIR"/*.json >/dev/null 2>&1; then
  echo "No JSON transcript found in $TRANSCRIPTION_DIR" >&2
  exit 1
fi

if ! ls "$TRANSCRIPTION_DIR"/*.srt >/dev/null 2>&1; then
  echo "No SRT transcript found in $TRANSCRIPTION_DIR" >&2
  exit 1
fi

echo "Full macOS pipeline test passed for: $VIDEO_PATH"
