#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

show_help() {
  cat <<'EOF'
Video Memory Indexer

Usage:
  ./run.sh [options]

Main modes:
  ./run.sh
      Scan iCloud Photos videos from the last configured period, default 24h,
      then transcribe new videos only.

  ./run.sh --all
      Scan the whole Photos database instead of only the last 24h.
      This does not intentionally download the whole iCloud library at once.
      It exports videos by UUID and skips already processed items.

  ./run.sh --all --max 20
      Scan the whole Photos database, but transcribe at most 20 eligible videos this run.
      Videos shorter than min_duration_seconds are skipped and do not consume the max budget.

  ./run.sh --max 5
      Scan the configured period, default 24h, but transcribe at most 5 eligible videos this run.

Manual sources:
  ./run.sh --add-folder /path/to/folder
      Add a folder to the persistent manual scan list.
      Missing folders are non-blocking, useful for external disks.

  ./run.sh --add-file /path/to/video.mov
      Add a single manual video file to the persistent scan list.

Analysis:
  ./run.sh --analyze
      Show SQLite status summary and recent errors/skips from logs/results.

Help:
  ./run.sh -h
  ./run.sh --h
  ./run.sh --help
      Show this help.

Current behavior:
  - skips videos shorter than min_duration_seconds, default 30s
  - skips videos with no audio stream instead of blocking the run
  - uses osxphotos exif_info.duration to skip short iCloud videos before export/download when available
  - --max counts eligible transcribed videos, not short skipped candidates
  - forces Whisper language to French, language: fr
  - avoids duplicates with Photos UUID and SHA256
  - stores transcripts as JSON, TXT and SRT
  - enriches JSON with ffprobe metadata and exiftool metadata when available
  - stores osxphotos metadata when available: people, albums, keywords, labels, places
  - deletes temporary iCloud video/audio files after successful transcription by default

Config:
  config/config.yaml

Manual sources registry:
  config/manual_sources.json

Logs:
  data/logs/run.log
  data/logs/cron.log

SQLite state:
  state/transcriber.sqlite3

Examples:
  ./run.sh
  ./run.sh --all
  ./run.sh --all --max 20
  ./run.sh --max 5
  ./run.sh --analyze
  ./run.sh --add-folder /Volumes/SSD/Videos
  ./run.sh --add-file ~/Desktop/video.mov

Recommended optional dependency for richer metadata:
  brew install exiftool
EOF
}

for arg in "${@:-}"; do
  case "$arg" in
    -h|--h|--help)
      show_help
      exit 0
      ;;
  esac
done

if [ ! -f .venv/bin/activate ]; then
  echo "No .venv found, creating it now..."
  ./install.sh
fi

. .venv/bin/activate
python bin/transcribe_videos.py --config config/config.yaml "$@"
