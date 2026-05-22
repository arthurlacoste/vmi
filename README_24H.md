# 24h on-demand mode

This mode does not download the whole iCloud Photos library.

It queries Photos for videos from the last 24h only:

```bash
osxphotos query --movie --from-date "YYYY-MM-DD HH:MM:SS"
```

Then it exports each unseen asset by Photos UUID:

```bash
osxphotos export data/incoming --uuid <UUID> --movie --download-missing --update
```

Duplicates are avoided in SQLite with:

- `photos_uuid` as primary key
- `sha256` unique index after export

After a successful transcription, local video and audio files are deleted by default.
Only transcripts and metadata remain.

## Full library scan

To scan the whole Photos database instead of the last 24h:

```bash
./run.sh --all
```

This still exports by UUID and uses the duplicate registry, so it does not intentionally download the whole iCloud library at once. It processes up to `osxphotos.max_videos_per_run` per run unless this value is set to `0` or `all`.

## Photos semantic metadata

The transcription JSON now stores the osxphotos asset metadata under:

```json
info.metadata.osxphotos
```

Depending on what Photos has indexed, this can include people, albums, keywords, detected labels, places, favorites and other ML/search fields exposed by osxphotos.
