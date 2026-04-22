"""
Doka Story Scheduler — publisher.

Runs inside GitHub Actions on a cron (every 15 min by default). Reads every
schedules/<brand>.json, finds entries whose `scheduled_at` is in the past and
`status == "pending"`, and publishes them as Instagram stories via Graph API.

Entries are marked "published" (or "error") in-place. The workflow commits the
updated JSON back to the repo so published items aren't re-sent.

Env vars required:
    META_ACCESS_TOKEN         Long-lived page token (or System User token).
    GITHUB_REPOSITORY         Set automatically by GitHub Actions (owner/repo).
    GITHUB_REF_NAME           Set automatically (usually "main").

Image resolution:
    Each schedule entry has an `image` field. If it starts with http(s), used
    as-is. Otherwise it's treated as a repo-relative path and rewritten to a
    raw.githubusercontent.com URL so Meta can fetch it. This means the repo
    must be public (or use a different host like Drive/S3 for images).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
ROOT = Path(__file__).resolve().parent.parent
SCHEDULES_DIR = ROOT / "schedules"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def resolve_image_url(image: str) -> str:
    if image.startswith(("http://", "https://")):
        return image
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    path = image.lstrip("/")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def create_story_container(ig_user_id: str, image_url: str, token: str) -> str:
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": token,
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def wait_container_ready(container_id: str, token: str, timeout: int = 120) -> None:
    url = f"{GRAPH_BASE}/{container_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(
            url,
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        r.raise_for_status()
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container {container_id} reported ERROR")
        time.sleep(3)
    raise TimeoutError(f"Container {container_id} not ready after {timeout}s")


def publish_container(ig_user_id: str, container_id: str, token: str) -> str:
    url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
    r = requests.post(
        url,
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def publish_story(ig_user_id: str, image_url: str, token: str) -> str:
    container_id = create_story_container(ig_user_id, image_url, token)
    wait_container_ready(container_id, token)
    return publish_container(ig_user_id, container_id, token)


def process_schedule(path: Path, token: str, now: datetime) -> bool:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    brand = data.get("brand", path.stem)
    ig_user_id = data["ig_user_id"]
    entries: list[dict[str, Any]] = data.get("entries", [])

    dirty = False
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        scheduled_at = datetime.fromisoformat(entry["scheduled_at"].replace("Z", "+00:00"))
        if scheduled_at > now:
            continue

        image_url = resolve_image_url(entry["image"])
        log(f"[{brand}] publishing {entry['image']} (scheduled {scheduled_at.isoformat()})")
        try:
            media_id = publish_story(ig_user_id, image_url, token)
            entry["status"] = "published"
            entry["media_id"] = media_id
            entry["published_at"] = now.isoformat()
            log(f"[{brand}] OK media_id={media_id}")
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)[:500]
            entry["error_at"] = now.isoformat()
            log(f"[{brand}] ERROR: {exc}")
        dirty = True

    if dirty:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return dirty


def main() -> int:
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        log("META_ACCESS_TOKEN not set")
        return 1

    if not SCHEDULES_DIR.exists():
        log(f"no schedules dir at {SCHEDULES_DIR}")
        return 0

    now = datetime.now(timezone.utc)
    any_changes = False
    for path in sorted(SCHEDULES_DIR.glob("*.json")):
        try:
            if process_schedule(path, token, now):
                any_changes = True
        except Exception as exc:
            log(f"[{path.name}] fatal: {exc}")

    if any_changes:
        # Signal workflow to commit updated schedules.
        gh_output = os.environ.get("GITHUB_OUTPUT")
        if gh_output:
            with open(gh_output, "a", encoding="utf-8") as f:
                f.write("changed=true\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
