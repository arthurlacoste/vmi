from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def flatten_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(flatten_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(flatten_text(v) for v in value.values())
    return str(value)


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def init_search_schema(con: sqlite3.Connection):
    con.execute("""
    CREATE TABLE IF NOT EXISTS videos(
      source_id TEXT PRIMARY KEY,
      source_kind TEXT,
      sha256 TEXT,
      filename TEXT,
      source_path TEXT,
      transcript_json TEXT,
      transcript_txt TEXT,
      transcript_srt TEXT,
      duration_seconds REAL,
      created_at TEXT,
      transcribed_at TEXT,
      status TEXT
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS video_metadata(
      source_id TEXT PRIMARY KEY,
      metadata_json TEXT,
      metadata_summary_json TEXT,
      date_original TEXT,
      device_make TEXT,
      device_model TEXT,
      latitude REAL,
      longitude REAL,
      place TEXT,
      labels_text TEXT,
      persons_text TEXT,
      albums_text TEXT,
      keywords_text TEXT,
      ai_caption TEXT,
      width INTEGER,
      height INTEGER,
      fps REAL
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS transcript_segments(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT,
      segment_index INTEGER,
      start REAL,
      end REAL,
      text TEXT
    )
    """)
    con.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
      source_id UNINDEXED,
      filename,
      transcript,
      segments,
      labels,
      persons,
      albums,
      keywords,
      place,
      ai_caption,
      metadata
    )
    """)
    con.commit()


def as_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def parse_fps(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if "/" in text:
        a, b = text.split("/", 1)
        try:
            denominator = float(b)
            return float(a) / denominator if denominator else None
        except Exception:
            return None
    return as_float(text)


def index_one_transcript(con: sqlite3.Connection, row) -> bool:
    source_id, source_kind, filename, source_path, sha256, duration, transcript_json, transcript_txt, transcript_srt, status, created_at = row
    if not transcript_json or not Path(transcript_json).exists():
        return False

    data = read_json(transcript_json)
    info = data.get("info", {})
    segments = data.get("segments", [])
    meta_summary = info.get("metadata_summary", {}) or {}
    osx_summary = meta_summary.get("osxphotos", {}) if isinstance(meta_summary, dict) else {}
    metadata = info.get("metadata", {}) or {}
    osx_metadata = metadata.get("osxphotos", {}) or {}

    transcript = "\n".join((seg.get("text") or "").strip() for seg in segments).strip()
    filename = filename or info.get("filename") or Path(transcript_json).stem
    source_path = source_path or info.get("source_path")
    duration = duration if duration is not None else info.get("duration")

    con.execute("""
      INSERT OR REPLACE INTO videos(source_id, source_kind, sha256, filename, source_path, transcript_json, transcript_txt, transcript_srt, duration_seconds, created_at, transcribed_at, status)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (source_id, source_kind, sha256 or info.get("sha256"), filename, source_path, transcript_json, transcript_txt, transcript_srt, duration, created_at, info.get("transcribed_at"), status))

    con.execute("DELETE FROM transcript_segments WHERE source_id=?", (source_id,))
    for idx, seg in enumerate(segments):
        con.execute("INSERT INTO transcript_segments(source_id, segment_index, start, end, text) VALUES(?,?,?,?,?)", (source_id, idx, seg.get("start"), seg.get("end"), seg.get("text")))

    labels = osx_summary.get("labels") or osx_metadata.get("labels")
    persons = osx_summary.get("persons") or osx_metadata.get("persons")
    albums = osx_summary.get("albums") or osx_metadata.get("albums")
    keywords = osx_summary.get("keywords") or osx_metadata.get("keywords")
    place = osx_summary.get("place") or meta_summary.get("place") or osx_metadata.get("place")
    latitude = meta_summary.get("gps_latitude") or osx_metadata.get("latitude")
    longitude = meta_summary.get("gps_longitude") or osx_metadata.get("longitude")
    ai_caption = osx_summary.get("description") or osx_summary.get("title") or ""

    con.execute("""
      INSERT OR REPLACE INTO video_metadata(source_id, metadata_json, metadata_summary_json, date_original, device_make, device_model, latitude, longitude, place, labels_text, persons_text, albums_text, keywords_text, ai_caption, width, height, fps)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        source_id,
        json.dumps(metadata, ensure_ascii=False),
        json.dumps(meta_summary, ensure_ascii=False),
        meta_summary.get("created_at") or info.get("created_at"),
        meta_summary.get("device_make"),
        meta_summary.get("device_model"),
        as_float(latitude),
        as_float(longitude),
        flatten_text(place),
        flatten_text(labels),
        flatten_text(persons),
        flatten_text(albums),
        flatten_text(keywords),
        ai_caption,
        meta_summary.get("width"),
        meta_summary.get("height"),
        parse_fps(meta_summary.get("frame_rate")),
    ))

    con.execute("DELETE FROM search_index WHERE source_id=?", (source_id,))
    con.execute("""
      INSERT INTO search_index(source_id, filename, transcript, segments, labels, persons, albums, keywords, place, ai_caption, metadata)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """, (
        source_id,
        filename,
        transcript,
        transcript,
        flatten_text(labels),
        flatten_text(persons),
        flatten_text(albums),
        flatten_text(keywords),
        flatten_text(place),
        ai_caption,
        flatten_text(meta_summary) + " " + flatten_text(metadata),
    ))
    return True


def rebuild_search_index(con: sqlite3.Connection) -> int:
    init_search_schema(con)
    rows = con.execute("""
      SELECT source_id, source_kind, original_filename, exported_path, sha256, duration_seconds, transcript_json, transcript_txt, transcript_srt, status, created_at
      FROM assets
      WHERE transcript_json IS NOT NULL AND status='done'
    """).fetchall()
    count = 0
    for row in rows:
        try:
            if index_one_transcript(con, row):
                count += 1
        except Exception as exc:
            print(f"Index warning: {row[0]}: {exc}")
    con.commit()
    return count


def search_videos(con: sqlite3.Connection, query: str, limit: int = 20, field: str | None = None, json_output: bool = False):
    init_search_schema(con)
    if field:
        allowed = {"filename", "transcript", "segments", "labels", "persons", "albums", "keywords", "place", "ai_caption", "metadata"}
        if field not in allowed:
            raise SystemExit(f"Unknown search field: {field}. Allowed: {', '.join(sorted(allowed))}")
        fts_query = f'{field}:"{query}"'
    else:
        fts_query = query

    rows = con.execute("""
      SELECT s.source_id, v.filename, v.duration_seconds, bm25(search_index) AS score,
             snippet(search_index, 2, '"', '"', '…', 14) AS snippet,
             v.transcript_json, m.labels_text, m.persons_text, m.place
      FROM search_index s
      LEFT JOIN videos v ON v.source_id=s.source_id
      LEFT JOIN video_metadata m ON m.source_id=s.source_id
      WHERE search_index MATCH ?
      ORDER BY score
      LIMIT ?
    """, (fts_query, limit)).fetchall()

    if json_output:
        print(json_dumps({"query": query, "results": [
            {"source_id": r[0], "filename": r[1], "duration": r[2], "score": r[3], "match": r[4], "transcript_json": r[5], "labels": r[6], "persons": r[7], "place": r[8]}
            for r in rows
        ]}))
        return

    for idx, row in enumerate(rows, 1):
        print(f"{idx}. {row[1] or row[0]}")
        print(f"   source_id: {row[0]}")
        print(f"   duration: {row[2] or ''}s")
        if row[6]:
            print(f"   labels: {row[6]}")
        if row[7]:
            print(f"   persons: {row[7]}")
        if row[8]:
            print(f"   place: {row[8]}")
        print(f"   match: {row[4] or ''}")
        print(f"   transcript_json: {row[5] or ''}")


def show_video(con: sqlite3.Connection, source_id: str):
    init_search_schema(con)
    row = con.execute("""
      SELECT v.source_id, v.filename, v.source_path, v.duration_seconds, v.transcript_json, v.transcript_txt, v.transcript_srt, m.metadata_summary_json
      FROM videos v
      LEFT JOIN video_metadata m ON m.source_id=v.source_id
      WHERE v.source_id=?
    """, (source_id,)).fetchone()
    if not row:
        print(f"Video not found in index: {source_id}")
        return
    print(json_dumps({
        "source_id": row[0],
        "filename": row[1],
        "source_path": row[2],
        "duration_seconds": row[3],
        "transcript_json": row[4],
        "transcript_txt": row[5],
        "transcript_srt": row[6],
        "metadata_summary": json.loads(row[7] or "{}"),
    }))


def format_seconds(sec):
    sec = float(sec)
    minutes, seconds = divmod(sec, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02}:{minutes:02}:{seconds:05.2f}" if hours else f"{minutes:02}:{seconds:05.2f}"


def candidates_from_segments(segments, max_candidates: int = 5):
    candidates = []
    hook_words = ("mais", "donc", "jamais", "incroyable", "truc", "problème", "pourquoi", "comment", "regarde", "attends", "secret", "vrai", "faux")
    for i in range(len(segments)):
        start = float(segments[i].get("start") or 0)
        end = start
        text_parts = []
        source_segments = []
        for j in range(i, min(len(segments), i + 12)):
            segment = segments[j]
            source_segments.append(j)
            text_parts.append((segment.get("text") or "").strip())
            end = float(segment.get("end") or end)
            duration = end - start
            if 12 <= duration <= 45:
                text = " ".join(text_parts).strip()
                words = text.split()
                score = min(100, 45 + len(words) + sum(8 for word in hook_words if word in text.lower()))
                if len(words) >= 20:
                    candidates.append({
                        "rank": 0,
                        "title": (text[:70] + "…") if len(text) > 70 else text,
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "duration": round(duration, 2),
                        "score": score,
                        "reason": "Extrait court avec densité de parole suffisante et début exploitable en hook.",
                        "hook_text": (text[:90] + "…") if len(text) > 90 else text,
                        "caption": text[:180],
                        "subtitle_style_note": "Sous-titres courts, grands, centrés bas, mots forts en évidence.",
                        "cut_notes": "Couper au début du premier segment et à la fin du dernier segment sélectionné.",
                        "risks": [],
                        "source_segments": source_segments,
                    })
                break
    candidates.sort(key=lambda item: (-item["score"], item["duration"]))
    for rank, candidate in enumerate(candidates[:max_candidates], 1):
        candidate["rank"] = rank
    return candidates[:max_candidates]


def fcpxml_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def seconds_to_fcpxml(sec) -> str:
    return f"{int(round(float(sec) * 1000))}/1000s"


def write_fcpxml(path: Path, timeline: dict):
    clips = timeline["clips"]
    total = sum(float(clip["source_end"]) - float(clip["source_start"]) for clip in clips) or 1
    source_video = timeline.get("source_video") or ""
    resource = f'<asset id="r1" name="{fcpxml_escape(Path(source_video or "source").name)}" src="file://{fcpxml_escape(source_video)}" hasVideo="1" />'
    clip_lines = []
    offset = 0.0
    for clip in clips:
        duration = float(clip["source_end"]) - float(clip["source_start"])
        clip_lines.append(
            f'<asset-clip name="{fcpxml_escape(clip["name"])}" ref="r1" offset="{seconds_to_fcpxml(offset)}" start="{seconds_to_fcpxml(clip["source_start"])}" duration="{seconds_to_fcpxml(duration)}" />'
        )
        offset += duration
    spine = "\n            ".join(clip_lines)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<fcpxml version="1.10">\n'
        f'  <resources>{resource}</resources>\n'
        '  <library>\n'
        '    <event name="VMI Shorts">\n'
        f'      <project name="{fcpxml_escape(timeline["name"])}">\n'
        f'        <sequence duration="{seconds_to_fcpxml(total)}" tcStart="0s" tcFormat="NDF">\n'
        '          <spine>\n'
        f'            {spine}\n'
        '          </spine>\n'
        '        </sequence>\n'
        '      </project>\n'
        '    </event>\n'
        '  </library>\n'
        '</fcpxml>\n'
    )
    path.write_text(xml, encoding="utf-8")


def resolve_video_selector(con: sqlite3.Connection, selector: str):
    init_search_schema(con)
    candidates = [selector]
    selector_path = Path(selector).expanduser()
    if selector_path.exists():
        resolved = str(selector_path.resolve())
        candidates.extend([resolved, f"file:{resolved}", selector_path.name])
    else:
        candidates.append(selector_path.name)

    def lookup():
        for value in dict.fromkeys(candidates):
            row = con.execute(
                "SELECT source_id, filename, source_path, transcript_json FROM videos WHERE source_id=? OR source_path=? OR filename=? LIMIT 1",
                (value, value, value),
            ).fetchone()
            if row:
                return row
        for value in dict.fromkeys(candidates):
            asset = con.execute("""
                SELECT source_id, source_kind, original_filename, exported_path, sha256, duration_seconds,
                       transcript_json, transcript_txt, transcript_srt, status, created_at
                FROM assets
                WHERE source_id=? OR exported_path=? OR original_filename=?
                LIMIT 1
            """, (value, value, value)).fetchone()
            if asset and asset[6]:
                index_one_transcript(con, asset)
                con.commit()
                return con.execute(
                    "SELECT source_id, filename, source_path, transcript_json FROM videos WHERE source_id=? LIMIT 1",
                    (asset[0],),
                ).fetchone()
        return None

    row = lookup()
    if row:
        return row
    rebuild_search_index(con)
    row = lookup()
    if row:
        return row
    return None


def select_video(con: sqlite3.Connection, selector: str, base: Path):
    row = resolve_video_selector(con, selector)
    if not row:
        raise SystemExit(
            f"Video not found in index: {selector}. Run ./run.sh --add-file {selector!r} then ./run.sh once to transcribe it, or use an existing source_id."
        )

    source_id, filename, source_path, transcript_json = row
    data = read_json(transcript_json)
    candidates = candidates_from_segments(data.get("segments", []))
    out_dir = base / "data" / "shorts" / source_id.replace("/", "_").replace(":", "_")
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"video": {"source_id": source_id, "filename": filename, "transcript_json": transcript_json, "source_path": source_path}, "candidates": candidates}
    (out_dir / "viral_candidates.json").write_text(json_dumps(result), encoding="utf-8")

    md = [f"# Short candidates: {filename}", ""]
    for candidate in candidates:
        md.extend([
            f"## {candidate['rank']}. {candidate['title']}",
            f"- Timecode: {format_seconds(candidate['start'])} → {format_seconds(candidate['end'])}",
            f"- Score: {candidate['score']}",
            f"- Hook: {candidate['hook_text']}",
            f"- Raison: {candidate['reason']}",
            "",
        ])
    (out_dir / "viral_candidates.md").write_text("\n".join(md), encoding="utf-8")

    timeline = {"timeline": {"name": f"short_candidates_{Path(filename or source_id).stem}", "source_video": source_path, "clips": [
        {"name": f"candidate_{candidate['rank']:02}", "source_start": candidate["start"], "source_end": candidate["end"], "timeline_start": 0, "timeline_end": candidate["duration"]}
        for candidate in candidates
    ]}}
    (out_dir / "cuts.timeline.json").write_text(json_dumps(timeline), encoding="utf-8")
    write_fcpxml(out_dir / "cuts.fcpxml", timeline["timeline"])

    prompt = f"Utilise MCP DL. Lis docs/SHORTS_AGENT.md, puis vérifie et améliore les candidats dans {out_dir}. Transcription: {transcript_json}. Vidéo source: {source_path}."
    (out_dir / "chatgpt_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"Shorts package written: {out_dir}")
    print(f"Prompt file: {out_dir / 'chatgpt_prompt.txt'}")
