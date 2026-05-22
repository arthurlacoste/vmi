#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, shutil, sqlite3, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from faster_whisper import WhisperModel

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}


def utcnow(): return datetime.now(timezone.utc)
def iso(dt=None): return (dt or utcnow()).isoformat()

def run(cmd, log_file: Path, check=True, capture=False):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"\n[{iso()}] $ {' '.join(map(str, cmd))}\n")
    p = subprocess.run(list(map(str, cmd)), capture_output=capture, text=True)
    if capture:
        with log_file.open("a", encoding="utf-8") as f:
            if p.stdout: f.write(p.stdout + "\n")
            if p.stderr: f.write(p.stderr + "\n")
    else:
        with log_file.open("a", encoding="utf-8") as f:
            if p.returncode != 0: f.write(f"exit={p.returncode}\n")
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd))}\n{p.stderr if capture else ''}")
    return p

def load_config(path: Path): return yaml.safe_load(path.read_text(encoding="utf-8"))
def resolve(base: Path, value: str):
    p = Path(os.path.expanduser(value)); return p if p.is_absolute() else base / p

def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024): h.update(chunk)
    return h.hexdigest()

def duration_seconds(path: Path, log_file: Path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], log_file, check=True, capture=True)
    return float((p.stdout or "0").strip() or 0)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def ffprobe_metadata(path: Path, log_file: Path) -> dict:
    try:
        p = run([
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ], log_file, check=True, capture=True)
        return json.loads(p.stdout or "{}")
    except Exception as e:
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(f"\n[{iso()}] WARNING ffprobe metadata failed: {path} | {e}\n")
        return {"error": str(e)}




def has_audio_stream(path: Path, log_file: Path) -> bool:
    try:
        meta = ffprobe_metadata(path, log_file)
        return any(st.get("codec_type") == "audio" for st in meta.get("streams", []))
    except Exception as e:
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(f"\n[{iso()}] WARNING audio stream detection failed: {path} | {e}\n")
        return False

def exiftool_metadata(path: Path, log_file: Path) -> dict:
    if not command_exists("exiftool"):
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(f"\n[{iso()}] WARNING exiftool unavailable, metadata will be ffprobe-only: {path}\n")
        return {"available": False, "error": "exiftool not installed"}
    try:
        p = run([
            "exiftool",
            "-json",
            "-n",
            "-G1",
            "-a",
            "-s",
            str(path),
        ], log_file, check=True, capture=True)
        data = json.loads(p.stdout or "[]")
        return {"available": True, "data": data[0] if data else {}}
    except Exception as e:
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(f"\n[{iso()}] WARNING exiftool metadata failed: {path} | {e}\n")
        return {"available": True, "error": str(e)}


def metadata_summary(exif: dict, ffprobe: dict) -> dict:
    exif_data = exif.get("data", {}) if isinstance(exif, dict) else {}
    fmt = ffprobe.get("format", {}) if isinstance(ffprobe, dict) else {}
    streams = ffprobe.get("streams", []) if isinstance(ffprobe, dict) else []
    video_stream = next((st for st in streams if st.get("codec_type") == "video"), {})
    audio_stream = next((st for st in streams if st.get("codec_type") == "audio"), {})

    def first(*keys):
        for key in keys:
            if key in exif_data and exif_data[key] not in (None, ""):
                return exif_data[key]
        tags = fmt.get("tags", {}) or {}
        for key in keys:
            simple = key.split(":")[-1]
            for candidate in (key, simple, simple.lower(), simple.upper()):
                if candidate in tags and tags[candidate] not in (None, ""):
                    return tags[candidate]
        return None

    return {
        "created_at": first("QuickTime:CreateDate", "QuickTime:CreationDate", "EXIF:DateTimeOriginal", "Composite:SubSecCreateDate", "creation_time"),
        "modified_at": first("QuickTime:ModifyDate", "File:FileModifyDate"),
        "device_make": first("QuickTime:Make", "EXIF:Make"),
        "device_model": first("QuickTime:Model", "EXIF:Model"),
        "software": first("QuickTime:Software", "EXIF:Software"),
        "gps_latitude": first("Composite:GPSLatitude", "QuickTime:GPSLatitude", "EXIF:GPSLatitude"),
        "gps_longitude": first("Composite:GPSLongitude", "QuickTime:GPSLongitude", "EXIF:GPSLongitude"),
        "gps_altitude": first("Composite:GPSAltitude", "QuickTime:GPSAltitude", "EXIF:GPSAltitude"),
        "width": video_stream.get("width") or first("QuickTime:ImageWidth", "EXIF:ImageWidth"),
        "height": video_stream.get("height") or first("QuickTime:ImageHeight", "EXIF:ImageHeight"),
        "rotation": first("Composite:Rotation", "QuickTime:Rotation"),
        "duration": fmt.get("duration") or first("QuickTime:Duration", "Composite:Duration"),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
        "frame_rate": video_stream.get("avg_frame_rate"),
        "bit_rate": fmt.get("bit_rate") or video_stream.get("bit_rate"),
    }

def init_db(db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)

    existing = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assets'").fetchone()
    if existing:
        cols = [r[1] for r in con.execute('PRAGMA table_info(assets)').fetchall()]
        # Migration from the old schema: photos_uuid primary key -> source_id primary key.
        if 'source_id' not in cols and 'photos_uuid' in cols:
            con.execute('ALTER TABLE assets RENAME TO assets_old')
            con.execute("""
            CREATE TABLE assets (
              source_id TEXT PRIMARY KEY,
              source_kind TEXT NOT NULL,
              original_filename TEXT,
              creation_date TEXT,
              exported_path TEXT,
              sha256 TEXT,
              duration_seconds REAL,
              status TEXT NOT NULL,
              transcript_json TEXT,
              transcript_txt TEXT,
              transcript_srt TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """)
            old_cols = [r[1] for r in con.execute('PRAGMA table_info(assets_old)').fetchall()]
            def has(c): return c in old_cols
            select_original = 'original_filename' if has('original_filename') else "NULL"
            select_creation = 'creation_date' if has('creation_date') else "NULL"
            select_exported = 'exported_path' if has('exported_path') else "NULL"
            select_sha = 'sha256' if has('sha256') else "NULL"
            select_json = 'transcript_json' if has('transcript_json') else "NULL"
            select_txt = 'transcript_txt' if has('transcript_txt') else "NULL"
            select_srt = 'transcript_srt' if has('transcript_srt') else "NULL"
            select_error = 'error' if has('error') else "NULL"
            select_created = 'created_at' if has('created_at') else "updated_at"
            con.execute(f"""
                INSERT OR REPLACE INTO assets (
                    source_id, source_kind, original_filename, creation_date, exported_path,
                    sha256, duration_seconds, status, transcript_json, transcript_txt,
                    transcript_srt, error, created_at, updated_at
                )
                SELECT
                    photos_uuid,
                    'icloud',
                    {select_original},
                    {select_creation},
                    {select_exported},
                    {select_sha},
                    NULL,
                    status,
                    {select_json},
                    {select_txt},
                    {select_srt},
                    {select_error},
                    {select_created},
                    updated_at
                FROM assets_old
            """)
            con.execute('DROP TABLE assets_old')
            con.commit()

    con.execute("""
    CREATE TABLE IF NOT EXISTS assets (
      source_id TEXT PRIMARY KEY,
      source_kind TEXT NOT NULL,
      original_filename TEXT,
      creation_date TEXT,
      exported_path TEXT,
      sha256 TEXT,
      duration_seconds REAL,
      status TEXT NOT NULL,
      transcript_json TEXT,
      transcript_txt TEXT,
      transcript_srt TEXT,
      error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """)
    cols = [r[1] for r in con.execute('PRAGMA table_info(assets)').fetchall()]
    required = {
        'source_kind': 'TEXT',
        'original_filename': 'TEXT',
        'creation_date': 'TEXT',
        'exported_path': 'TEXT',
        'sha256': 'TEXT',
        'duration_seconds': 'REAL',
        'transcript_json': 'TEXT',
        'transcript_txt': 'TEXT',
        'transcript_srt': 'TEXT',
        'error': 'TEXT',
    }
    for col, typ in required.items():
        if col not in cols:
            con.execute(f'ALTER TABLE assets ADD COLUMN {col} {typ}')
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256) WHERE sha256 IS NOT NULL")
    con.commit(); return con

def seen_source(con, source_id: str):
    row = con.execute("SELECT status FROM assets WHERE source_id=?", (source_id,)).fetchone()
    return bool(row and row[0] in ("exported", "transcribing", "done", "skipped_short", "skipped_short_metadata", "skipped_no_audio", "duplicate"))

def seen_hash(con, digest: str):
    row = con.execute("SELECT status FROM assets WHERE sha256=?", (digest,)).fetchone()
    return bool(row and row[0] in ("done", "skipped_short", "skipped_short_metadata", "skipped_no_audio", "duplicate"))

def upsert(con, source_id: str, **fields):
    fields["updated_at"] = iso()
    row = con.execute("SELECT 1 FROM assets WHERE source_id=?", (source_id,)).fetchone()
    if row:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE assets SET {sets} WHERE source_id=?", [*fields.values(), source_id])
    else:
        fields["created_at"] = iso(); fields["source_id"] = source_id
        cols = ", ".join(fields); qs = ", ".join("?" for _ in fields)
        con.execute(f"INSERT INTO assets ({cols}) VALUES ({qs})", list(fields.values()))
    con.commit()

def manual_sources_path(cfg, base): return resolve(base, cfg.get('manual_sources_file', 'config/manual_sources.json'))
def load_manual_sources(cfg, base):
    p = manual_sources_path(cfg, base)
    if not p.exists(): return {"folders": [], "files": []}
    return json.loads(p.read_text(encoding='utf-8'))
def save_manual_sources(cfg, base, data):
    p = manual_sources_path(cfg, base); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
def add_manual_folder(cfg, base, folder):
    data = load_manual_sources(cfg, base); folder = str(Path(folder).expanduser().resolve())
    if folder not in data['folders']: data['folders'].append(folder)
    save_manual_sources(cfg, base, data)
def add_manual_file(cfg, base, file):
    data = load_manual_sources(cfg, base); file = str(Path(file).expanduser().resolve())
    if file not in data['files']: data['files'].append(file)
    save_manual_sources(cfg, base, data)



def parse_limit(value, default=None):
    if value in (None, "", "all", 0, "0"):
        return default
    return int(value)

def osxphotos_query_recent_movies(cfg, log_file: Path, scan_all: bool = False):
    osx = cfg["osxphotos"]; library = os.path.expanduser(osx.get("library", "~/Pictures/Photos Library.photoslibrary"))
    cmd = ["osxphotos", "query", "--library", library, "--json", "--only-movies"]
    if not scan_all:
        since = (datetime.now() - timedelta(hours=int(osx.get("hours_back", 24)))).strftime("%Y-%m-%d %H:%M:%S")
        cmd += ["--from-date", since]
    if osx.get("album"): cmd += ["--album", osx["album"]]
    if osx.get("favorite_only"): cmd += ["--favorite"]
    p = run(cmd, log_file, check=True, capture=True)
    data = json.loads(p.stdout or "[]")
    # Important: this is only the candidate scan cap. --max counts eligible processed videos,
    # so short videos skipped by min_duration_seconds do not consume the --max budget.
    candidate_limit = parse_limit(osx.get("candidate_scan_limit", 200), default=None)
    if candidate_limit is None:
        return data
    return data[:candidate_limit]

def export_asset(cfg, uuid: str, incoming: Path, log_file: Path):
    library = os.path.expanduser(cfg["osxphotos"].get("library", "~/Pictures/Photos Library.photoslibrary"))
    before = set(p for p in incoming.rglob("*") if p.is_file())
    run(["osxphotos", "export", incoming, "--library", library, "--uuid", uuid, "--only-movies", "--download-missing", "--update"], log_file)
    after = set(p for p in incoming.rglob("*") if p.is_file())
    new_files = [p for p in after - before if p.suffix.lower() in VIDEO_EXTS]
    candidates = new_files or [p for p in after if p.suffix.lower() in VIDEO_EXTS]
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None

def extract_audio(video: Path, wav: Path, log_file: Path):
    run(["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav], log_file)

def srt_ts(sec: float):
    ms = int(round(sec * 1000)); h, r = divmod(ms, 3600000); m, r = divmod(r, 60000); s, ms = divmod(r, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def write_transcripts(stem, segments, info, out_dir: Path, formats):
    out_dir.mkdir(parents=True, exist_ok=True); res = {}
    if "json" in formats:
        p = out_dir / f"{stem}.json"; p.write_text(json.dumps({"info": info, "segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8"); res["transcript_json"] = str(p)
    if "txt" in formats:
        p = out_dir / f"{stem}.txt"; p.write_text("\n".join(s["text"].strip() for s in segments).strip() + "\n", encoding="utf-8"); res["transcript_txt"] = str(p)
    if "srt" in formats:
        lines=[]
        for i,s in enumerate(segments,1): lines += [str(i), f"{srt_ts(s['start'])} --> {srt_ts(s['end'])}", s["text"].strip(), ""]
        p = out_dir / f"{stem}.srt"; p.write_text("\n".join(lines), encoding="utf-8"); res["transcript_srt"] = str(p)
    return res





def osxphotos_duration(asset: dict | None):
    if not asset:
        return None

    def as_seconds(value):
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            if "value" in value and "timescale" in value and value.get("timescale"):
                try:
                    return float(value["value"]) / float(value["timescale"])
                except Exception:
                    return None
            # Sometimes osxphotos nests duration one level deeper.
            if "duration" in value:
                return as_seconds(value.get("duration"))
            return None
        try:
            return float(value)
        except Exception:
            return None

    def collect_duration_candidates(obj):
        out = []
        if isinstance(obj, dict):
            if "duration" in obj:
                out.append(obj.get("duration"))
            for key in ("flag_segments", "quality_segments", "segments"):
                if key in obj:
                    out.extend(collect_duration_candidates(obj.get(key)))
        elif isinstance(obj, list):
            for item in obj:
                out.extend(collect_duration_candidates(item))
        return out

    candidates = [
        asset.get("duration"),
        (asset.get("exif_info") or {}).get("duration"),
    ]
    candidates.extend(collect_duration_candidates(asset.get("media_analysis")))

    for candidate in candidates:
        seconds = as_seconds(candidate)
        if seconds is not None:
            return seconds
    return None

def compact_osxphotos_asset(asset: dict | None) -> dict:
    if not asset:
        return {}
    wanted_keys = [
        "uuid", "filename", "original_filename", "date", "creation_date", "added_date", "modified_date",
        "title", "description", "keywords", "albums", "persons", "labels", "detected_text",
        "favorite", "hidden", "burst", "live_photo", "uti", "path", "original_path", "ismovie",
        "height", "width", "orientation", "duration", "place", "latitude", "longitude", "altitude",
        "score", "aesthetic_score", "overall_aesthetic_score", "curation_score", "promotion_score"
    ]
    out = {}
    for key in wanted_keys:
        if key in asset and asset[key] not in (None, "", [], {}):
            out[key] = asset[key]
    # Keep unknown osxphotos fields too, but under raw, because osxphotos evolves and may include useful ML fields.
    out["raw"] = asset
    return out


def osxphotos_summary(asset: dict | None) -> dict:
    if not asset:
        return {}
    def get(*keys):
        for k in keys:
            v = asset.get(k)
            if v not in (None, "", [], {}):
                return v
        return None
    return {
        "persons": get("persons"),
        "keywords": get("keywords"),
        "albums": get("albums"),
        "labels": get("labels"),
        "detected_text": get("detected_text"),
        "favorite": get("favorite"),
        "title": get("title"),
        "description": get("description"),
        "place": get("place"),
    }

def transcribe_file(cfg, con, source_id, source_kind, source_path: Path, processed, audio_dir, transcripts, log_file, model, osxphotos_asset=None):
    working = None
    wav = None
    try:
        min_dur = float(cfg.get('min_duration_seconds', 30))
        digest = sha256_file(source_path)
        if seen_hash(con, digest): return 'duplicate'
        dur = duration_seconds(source_path, log_file)
        upsert(con, source_id, source_kind=source_kind, original_filename=source_path.name, exported_path=str(source_path), sha256=digest, duration_seconds=dur, status='exported')
        if dur < min_dur:
            upsert(con, source_id, status='skipped_short', error=f'duration {dur:.2f}s < {min_dur:.2f}s')
            return 'skipped_short'
        if not has_audio_stream(source_path, log_file):
            upsert(con, source_id, status='skipped_no_audio', error='video has no audio stream')
            storage = cfg.get('storage', {})
            if storage.get('delete_video_after_transcription', True) and source_kind == 'icloud':
                source_path.unlink(missing_ok=True)
            return 'skipped_no_audio'
        stem = f"{source_path.stem}_{digest[:8]}"
        working = processed / f"{stem}{source_path.suffix.lower()}"; shutil.copy2(source_path, working)
        wav = audio_dir / f"{stem}.wav"
        extract_audio(working, wav, log_file); upsert(con, source_id, status='transcribing')
        tx = cfg['transcription']
        seg_iter, info_obj = model.transcribe(str(wav), language=tx.get('language', 'fr'), beam_size=int(tx.get('beam_size', 5)), vad_filter=bool(tx.get('vad_filter', True)))
        segments = [{"start": float(s.start), "end": float(s.end), "text": s.text} for s in seg_iter]
        ffmeta = ffprobe_metadata(source_path, log_file)
        exifmeta = exiftool_metadata(source_path, log_file)
        info = {
            "source_id": source_id,
            "source_kind": source_kind,
            "filename": source_path.name,
            "source_path": str(source_path),
            "sha256": digest,
            "duration": dur,
            "requested_language": tx.get('language', 'fr'),
            "detected_language": getattr(info_obj, 'language', None),
            "transcribed_at": iso(),
            "metadata_summary": {
                **metadata_summary(exifmeta, ffmeta),
                "osxphotos": osxphotos_summary(osxphotos_asset),
            },
            "metadata": {
                "osxphotos": compact_osxphotos_asset(osxphotos_asset),
                "exiftool": exifmeta,
                "ffprobe": ffmeta,
            },
        }
        outputs = write_transcripts(stem, segments, info, transcripts, tx.get('formats', ['txt','srt','json']))
        upsert(con, source_id, status='done', error=None, **outputs)
        storage = cfg.get('storage', {})
        if storage.get('delete_audio_after_transcription', True) and wav: wav.unlink(missing_ok=True)
        if storage.get('delete_video_after_transcription', True) and source_kind == 'icloud':
            source_path.unlink(missing_ok=True)
            if working: working.unlink(missing_ok=True)
        return 'done'
    except Exception as e:
        upsert(con, source_id, status='error', error=str(e))
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(f"\n[{iso()}] ERROR video failed, continuing: {source_path} | {e}\n")
        try:
            if wav: wav.unlink(missing_ok=True)
        except Exception:
            pass
        return 'error'

def analyze(cfg, con, base):
    rows = con.execute("SELECT status, count(*) FROM assets GROUP BY status ORDER BY status").fetchall()
    print("Status summary:")
    for status, n in rows: print(f"- {status}: {n}")
    print("\nRecent errors/skips:")
    for r in con.execute("SELECT source_id, status, original_filename, duration_seconds, error FROM assets WHERE status IN ('error','skipped_short','skipped_short_metadata','skipped_no_audio') ORDER BY updated_at DESC LIMIT 20"):
        print(f"- {r[1]} | {r[2]} | {r[3]}s | {r[4]}")
    log_file = resolve(base, cfg['paths']['log_file'])
    if log_file.exists():
        lines = log_file.read_text(errors='ignore').splitlines()
        errs = [l for l in lines if 'Error:' in l or 'RuntimeError' in l or 'No such option' in l or 'Invalid value' in l]
        print(f"\nLog errors found: {len(errs)}")
        for l in errs[-20:]: print(f"- {l}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config/config.yaml')
    ap.add_argument('--add-folder')
    ap.add_argument('--add-file')
    ap.add_argument('--analyze', action='store_true')
    ap.add_argument('--all', action='store_true', help='Scan the whole Photos library instead of only the last configured hours')
    ap.add_argument('--max', type=str, default=None, help='Override osxphotos.max_videos_per_run for this run, e.g. --all --max 20 or --max all')
    args = ap.parse_args()
    cfg = load_config(Path(args.config).resolve()); base = Path(cfg['paths']['project_dir']).expanduser()
    log_file = resolve(base, cfg['paths']['log_file']); con = init_db(resolve(base, cfg['paths']['state_db']))
    if args.add_folder:
        add_manual_folder(cfg, base, args.add_folder); print(f"Added folder: {Path(args.add_folder).expanduser().resolve()}"); return
    if args.add_file:
        add_manual_file(cfg, base, args.add_file); print(f"Added file: {Path(args.add_file).expanduser().resolve()}"); return
    if args.analyze:
        analyze(cfg, con, base); return
    incoming = resolve(base, cfg['paths']['incoming_dir']); incoming.mkdir(parents=True, exist_ok=True)
    processed = resolve(base, cfg['paths']['processed_dir']); processed.mkdir(parents=True, exist_ok=True)
    transcripts = resolve(base, cfg['paths']['transcripts_dir']); transcripts.mkdir(parents=True, exist_ok=True)
    audio_dir = resolve(base, cfg['paths']['audio_dir']); audio_dir.mkdir(parents=True, exist_ok=True)
    tx = cfg['transcription']; model = WhisperModel(tx.get('model', 'small'), device=tx.get('device', 'auto'), compute_type=tx.get('compute_type', 'auto'))
    run(['open', '-a', 'Photos'], log_file, check=False)
    if args.max is not None:
        cfg.setdefault('osxphotos', {})['max_videos_per_run'] = args.max
    eligible_limit = parse_limit(cfg.get('osxphotos', {}).get('max_videos_per_run', 20), default=None)
    eligible_done = 0
    candidates_seen = 0
    for asset in osxphotos_query_recent_movies(cfg, log_file, scan_all=args.all):
        if eligible_limit is not None and eligible_done >= eligible_limit:
            break
        candidates_seen += 1
        uuid = asset.get('uuid') or asset.get('UUID')
        if not uuid or seen_source(con, uuid):
            continue
        upsert(con, uuid, source_kind='icloud', original_filename=asset.get('original_filename') or asset.get('filename') or uuid, creation_date=str(asset.get('date') or asset.get('creation_date') or ''), status='queued')
        try:
            meta_duration = osxphotos_duration(asset)
        except Exception as e:
            meta_duration = None
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING osxphotos duration parse failed for {uuid}, continuing with export fallback | {e}\n")
        min_dur = float(cfg.get('min_duration_seconds', 30))
        if meta_duration is not None and meta_duration < min_dur:
            upsert(
                con,
                uuid,
                source_kind='icloud',
                original_filename=asset.get('original_filename') or asset.get('filename') or uuid,
                creation_date=str(asset.get('date') or asset.get('creation_date') or ''),
                duration_seconds=meta_duration,
                status='skipped_short_metadata',
                error=f'osxphotos metadata duration {meta_duration:.2f}s < {min_dur:.2f}s',
            )
            continue
        exported = export_asset(cfg, uuid, incoming, log_file)
        if exported:
            result = transcribe_file(cfg, con, uuid, 'icloud', exported, processed, audio_dir, transcripts, log_file, model, osxphotos_asset=asset)
            if result == 'done':
                eligible_done += 1
    with log_file.open('a', encoding='utf-8') as lf:
        lf.write(f"\n[{iso()}] RUN SUMMARY icloud candidates_seen={candidates_seen} eligible_done={eligible_done} eligible_limit={eligible_limit}\n")
    manual = load_manual_sources(cfg, base)
    for folder in manual.get('folders', []):
        folder_path = Path(folder).expanduser()
        if not folder_path.exists():
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual folder unavailable, skipping: {folder_path}\n")
            continue
        if not folder_path.is_dir():
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual folder is not a directory, skipping: {folder_path}\n")
            continue
        try:
            files_iter = folder_path.rglob('*')
            for f in files_iter:
                try:
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                        sid = 'file:' + str(f.resolve())
                        if not seen_source(con, sid):
                            transcribe_file(cfg, con, sid, 'manual_folder', f, processed, audio_dir, transcripts, log_file, model)
                except Exception as e:
                    with log_file.open('a', encoding='utf-8') as lf:
                        lf.write(f"\n[{iso()}] WARNING manual file skipped: {f} | {e}\n")
                    continue
        except Exception as e:
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual folder scan failed, skipping: {folder_path} | {e}\n")
            continue
    for file in manual.get('files', []):
        f = Path(file).expanduser()
        if not f.exists():
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual file unavailable, skipping: {f}\n")
            continue
        if f.suffix.lower() not in VIDEO_EXTS:
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual file extension not supported, skipping: {f}\n")
            continue
        try:
            sid = 'file:' + str(f.resolve())
            if not seen_source(con, sid):
                transcribe_file(cfg, con, sid, 'manual_file', f, processed, audio_dir, transcripts, log_file, model)
        except Exception as e:
            with log_file.open('a', encoding='utf-8') as lf:
                lf.write(f"\n[{iso()}] WARNING manual file failed, skipping: {f} | {e}\n")
            continue

if __name__ == '__main__': main()
