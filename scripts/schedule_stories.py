"""
Local helper: take a folder of images and enqueue them in a brand's schedule.

Usage:
    python scripts/schedule_stories.py \
        --brand aromia \
        --folder "C:/path/to/images" \
        --times "2026-04-22 08:00,2026-04-22 12:00,2026-04-23 09:00" \
        --tz America/Costa_Rica

What it does:
    1. Sorts image files in --folder alphabetically.
    2. Copies them into images/<brand>/<YYYY-MM-DD>/ inside this repo.
    3. Appends one entry per image to schedules/<brand>.json with status=pending.
    4. Leaves git changes ready for you to commit + push — once pushed, the
       GitHub Actions cron (every 15 min) will publish each story at its time.

Times can also be provided with --every (e.g. "daily 09:00,18:00 starting
2026-04-22 count 10") for recurring patterns.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCHEDULES_DIR = ROOT / "schedules"
IMAGES_DIR = ROOT / "images"
VALID_EXTS = {".jpg", ".jpeg", ".png"}


def load_schedule(brand: str) -> dict:
    path = SCHEDULES_DIR / f"{brand}.json"
    if not path.exists():
        print(
            f"No existe schedules/{brand}.json. Créalo primero con ig_user_id.",
            file=sys.stderr,
        )
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_schedule(brand: str, data: dict) -> None:
    path = SCHEDULES_DIR / f"{brand}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def parse_times(raw: str, tz: ZoneInfo) -> list[datetime]:
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        dt = datetime.fromisoformat(chunk.replace("/", "-"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        out.append(dt.astimezone(ZoneInfo("UTC")))
    return out


def parse_daily(raw: str, tz: ZoneInfo) -> list[datetime]:
    # Format: "HH:MM,HH:MM starting YYYY-MM-DD count N"
    parts = raw.split()
    hhmm_list = parts[0].split(",")
    start = None
    count = None
    i = 1
    while i < len(parts):
        if parts[i] == "starting":
            start = datetime.fromisoformat(parts[i + 1]).date()
            i += 2
        elif parts[i] == "count":
            count = int(parts[i + 1])
            i += 2
        else:
            i += 1
    if start is None or count is None:
        raise ValueError("--every requires 'starting YYYY-MM-DD count N'")

    out = []
    day = start
    remaining = count
    while remaining > 0:
        for hm in hhmm_list:
            if remaining == 0:
                break
            hour, minute = map(int, hm.split(":"))
            dt_local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            out.append(dt_local.astimezone(ZoneInfo("UTC")))
            remaining -= 1
        day += timedelta(days=1)
    return out


def collect_images(folder: Path) -> list[Path]:
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VALID_EXTS]
    files.sort(key=lambda p: p.name.lower())
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--folder", required=True, help="Carpeta local con las imágenes")
    ap.add_argument("--times", help="Lista CSV: '2026-04-22 08:00,2026-04-22 12:00'")
    ap.add_argument("--every", help="Recurrente: '09:00,18:00 starting 2026-04-22 count 10'")
    ap.add_argument("--tz", default="America/Costa_Rica")
    args = ap.parse_args()

    if not args.times and not args.every:
        ap.error("Pasa --times o --every")

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Carpeta no existe: {folder}", file=sys.stderr)
        return 1

    tz = ZoneInfo(args.tz)
    times_utc = parse_times(args.times, tz) if args.times else parse_daily(args.every, tz)

    images = collect_images(folder)
    if not images:
        print(f"No hay imágenes .jpg/.jpeg/.png en {folder}", file=sys.stderr)
        return 1

    if len(images) != len(times_utc):
        print(
            f"Aviso: {len(images)} imágenes vs {len(times_utc)} horarios. "
            f"Se usarán las primeras {min(len(images), len(times_utc))}.",
            file=sys.stderr,
        )

    pairs = list(zip(images, times_utc))
    schedule = load_schedule(args.brand)
    schedule.setdefault("entries", [])

    today_stamp = datetime.now(tz).strftime("%Y-%m-%d")
    dest_dir = IMAGES_DIR / args.brand / today_stamp
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src, when_utc in pairs:
        dest = dest_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
        rel = dest.relative_to(ROOT).as_posix()
        schedule["entries"].append({
            "image": rel,
            "scheduled_at": when_utc.isoformat().replace("+00:00", "Z"),
            "status": "pending",
        })
        print(f"+ {rel}  ->  {when_utc.isoformat()}")

    save_schedule(args.brand, schedule)
    print(f"\nListo. {len(pairs)} historias agregadas a schedules/{args.brand}.json")
    print("Ahora: git add -A && git commit -m 'schedule' && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
