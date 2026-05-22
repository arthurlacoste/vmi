#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, os
from datetime import datetime, timedelta

parser = argparse.ArgumentParser()
parser.add_argument('--library', default='~/Pictures/Photos Library.photoslibrary')
parser.add_argument('--hours', type=int, default=24)
parser.add_argument('--limit', type=int, default=3)
args = parser.parse_args()

since = (datetime.now() - timedelta(hours=args.hours)).strftime('%Y-%m-%d %H:%M:%S')
cmd = [
    'osxphotos', 'query',
    '--library', os.path.expanduser(args.library),
    '--json',
    '--only-movies',
    '--from-date', since,
]

p = subprocess.run(cmd, capture_output=True, text=True)
print('command:', ' '.join(cmd))
print('returncode:', p.returncode)
if p.stderr.strip():
    print('\nstderr preview:')
    print(p.stderr[-2000:])

raw = p.stdout.strip()
start = raw.find('[')
end = raw.rfind(']')
if start == -1 or end == -1 or end <= start:
    print('\nNo JSON array found in stdout. stdout preview:')
    print(raw[:3000])
    raise SystemExit(2)

json_text = raw[start:end+1]
data = json.loads(json_text)
print('\ncount:', len(data))
for i, item in enumerate(data[:args.limit]):
    print(f'\nitem {i+1} keys:')
    print(sorted(item.keys()))
    print('\nduration-ish fields:')
    for k, v in item.items():
        if 'duration' in k.lower() or 'time' in k.lower() or 'movie' in k.lower() or 'video' in k.lower():
            print(f'  {k}: {v!r}')
    print('\nfull item preview:')
    print(json.dumps(item, indent=2, ensure_ascii=False)[:5000])
