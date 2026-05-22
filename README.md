# VMI: Video Memory Indexer

VMI is a local Python pipeline that exports videos from Apple Photos/iCloud Photos, transcribes their audio, enriches the output with video and Photos metadata, and keeps a SQLite state to avoid duplicates.

The project is designed to become a searchable local video memory: transcripts, timestamps, metadata, and eventually short-form highlight selection.

## Features

- Scans recent iCloud Photos videos, default: last 24 hours
- Can scan the whole Photos database with `--all`
- Exports videos by Photos UUID and avoids duplicates
- Supports manual folders and manual video files
- Skips videos shorter than `min_duration_seconds`, default: 30 seconds
- Skips videos without an audio stream
- Uses `osxphotos` duration metadata to skip short iCloud videos before export/download when available
- Transcribes with Whisper, forced language: French (`fr`)
- Stores transcripts as JSON, TXT, and SRT
- Enriches JSON with `ffprobe` metadata
- Enriches JSON with `exiftool` metadata when available
- Stores Apple Photos metadata when available: people, albums, keywords, labels, places, favorites, and other fields exposed by `osxphotos`
- Deletes temporary local video/audio files after successful transcription by default
- Maintains processing state in SQLite

## Requirements

- macOS
- Apple Photos library
- Homebrew
- Python 3
- `ffmpeg`
- `osxphotos`
- Optional: `exiftool` for richer metadata

Install system dependencies:

```bash
brew install ffmpeg pipx
pipx install osxphotos
brew install exiftool
```

`exiftool` is optional but recommended.

In Photos.app, it is best to enable:

```text
Settings > iCloud > Download Originals to this Mac
```

macOS does not provide an official command to force iCloud Photos to immediately download all originals. VMI uses Photos.app wake-up behavior and `osxphotos --download-missing` when exporting assets.

## Installation

```bash
cd ~/dev/vmi
./install.sh
```

This creates the Python virtual environment used by `run.sh`.

## Usage

Run the default scan:

```bash
./run.sh
```

This scans videos from the configured recent period, default: last 24 hours, and transcribes only new videos.

Scan the whole Photos database:

```bash
./run.sh --all
```

This does not intentionally download the whole iCloud library at once. It queries the Photos database, exports videos by UUID, and skips already processed items.

Scan the whole Photos database but transcribe at most 20 eligible videos:

```bash
./run.sh --all --max 20
```

Videos shorter than `min_duration_seconds` are skipped and do not consume the max budget.

Scan the configured recent period but transcribe at most 5 eligible videos:

```bash
./run.sh --max 5
```

Analyze local status and recent errors/skips:

```bash
./run.sh --analyze
```

Show help:

```bash
./run.sh --help
```

## Manual sources

Add a folder to the persistent manual scan list:

```bash
./run.sh --add-folder /path/to/folder
```

Missing folders are non-blocking, which is useful for external disks.

Add a single manual video file:

```bash
./run.sh --add-file ~/Desktop/video.mov
```

Manual sources are stored in:

```text
config/manual_sources.json
```

This file is intentionally ignored by Git.

## 24-hour on-demand mode

The default mode does not download the whole iCloud Photos library.

It queries Photos for videos from the configured recent period:

```bash
osxphotos query --movie --from-date "YYYY-MM-DD HH:MM:SS"
```

Then it exports each unseen asset by Photos UUID:

```bash
osxphotos export data/incoming --uuid <UUID> --movie --download-missing --update
```

Duplicates are avoided in SQLite with:

- `photos_uuid` as the primary key
- `sha256` as a unique index after export

After a successful transcription, local video and audio files are deleted by default. Only transcripts and metadata remain.

## Full library scan

To scan the whole Photos database instead of only the recent period:

```bash
./run.sh --all
```

This still exports by UUID and uses the duplicate registry, so it does not intentionally download the whole iCloud library at once.

It processes up to `osxphotos.max_videos_per_run` videos per run unless this value is set to `0` or `all`.

## Configuration

Main config file:

```text
config/config.yaml
```

Important settings:

```yaml
sync_mode: osxphotos

paths:
  project_dir: .
  incoming_dir: data/incoming
  processed_dir: data/processed
  transcripts_dir: data/transcripts
  audio_dir: data/audio
  state_db: state/transcriber.sqlite3
  log_file: data/logs/run.log

osxphotos:
  library: ~/Pictures/Photos Library.photoslibrary
  hours_back: 24
  max_videos_per_run: 20
  candidate_scan_limit: 200
  album: null
  favorite_only: false

storage:
  delete_video_after_transcription: true
  delete_audio_after_transcription: true

transcription:
  model: medium
  device: auto
  compute_type: auto
  language: fr
  beam_size: 5
  vad_filter: true
  formats: [txt, srt, json]

min_duration_seconds: 30
```

## Output directories

```text
data/incoming      exported videos
data/processed     working copies
data/audio         extracted audio
data/transcripts   JSON, TXT, and SRT transcripts
data/logs          run and cron logs
state/             SQLite state
```

Runtime data is ignored by Git.

## Transcript JSON metadata

The transcription JSON stores Apple Photos metadata under:

```json
info.metadata.osxphotos
```

Depending on what Photos has indexed, this can include people, albums, keywords, detected labels, places, favorites, and other ML/search fields exposed by `osxphotos`.

The JSON can also include:

- Whisper segments and timestamps
- `ffprobe` metadata
- `exiftool` metadata, if available
- normalized metadata summaries

## Cron example

Edit your crontab:

```bash
crontab -e
```

Example hourly run:

```cron
0 * * * * cd ~/dev/vmi && ./run.sh >> data/logs/cron.log 2>&1
```

Example daytime run:

```cron
0 8-23 * * * cd ~/dev/vmi && ./run.sh >> data/logs/cron.log 2>&1
```

A starter file is available in:

```text
crontab.example
```

## Roadmap

The next layer is to use timestamped transcript JSON files in `data/transcripts` to:

- index spoken text and video metadata in SQLite FTS5
- search videos by transcript, people, labels, places, albums, dates, device, duration, dimensions, codec, and filename
- score transcript segments
- select candidate highlights for short-form videos
- generate cut plans and timeline exports such as FCPXML, OTIO, or EDL

See:

```text
docs/PLAN_SEARCH_AND_VIRAL_SHORTS.md
docs/SHORTS_AGENT.md
```
