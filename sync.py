#!/usr/bin/env python3
"""
Kamiza VOD archive. Runs on GitHub Actions, not on anyone's machine.

Every few hours: list this channel's Twitch VODs, skip anything already
archived or still being written, download it, upload it to YouTube as private,
record it in the manifest, and post a card to the Kamiza Discord.

Notes that matter:

* Quota. videos.insert used to cost 1600 units against a 10,000/day budget,
  which capped you at six uploads a day. Google cut it to 1 unit with a
  100/day allowance. The old Forge script capped itself at 5 per run because
  of the old maths; that cap is gone. The real limits now are runner disk and
  the six hour job timeout, so we bound by BYTES and TIME, not by count.

* Unfinished VODs. A stream that is still live, or finished in the last few
  minutes, has a VOD that Twitch is still writing. Downloading it gets you a
  truncated file that looks complete. We skip anything younger than 20 min.

* Private means private. Only the uploading account can ever watch these.
  That is deliberate. The Discord card carries the metadata so the other
  person can see what exists without being able to open it.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded.json")

TWITCH_ID = os.environ["TWITCH_CLIENT_ID"]
TWITCH_SECRET = os.environ["TWITCH_CLIENT_SECRET"]
TWITCH_CHANNEL = os.environ["TWITCH_CHANNEL"]
YT_ID = os.environ["YT_CLIENT_ID"]
YT_SECRET = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH = os.environ["YT_REFRESH_TOKEN"]
WHO = os.environ.get("KAMIZA_WHO", TWITCH_CHANNEL)
WORKER = os.environ.get("KAMIZA_WORKER_URL", "").rstrip("/")
WORKER_TOKEN = os.environ.get("KAMIZA_WEBHOOK_TOKEN", "")

# Stay inside the runner's disk and the 6h job limit.
MAX_BYTES_PER_RUN = int(os.environ.get("MAX_BYTES_PER_RUN", 40 * 1024**3))
DEADLINE = time.time() + int(os.environ.get("RUN_SECONDS", 5 * 3600))
MIN_AGE_MINUTES = 20


def log(msg):
    print(msg, flush=True)


def load_manifest():
    if not os.path.exists(MANIFEST):
        return []
    with open(MANIFEST) as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def save_manifest(done):
    with open(MANIFEST, "w") as fh:
        json.dump(done, fh, indent=1)


def twitch_token():
    r = requests.post("https://id.twitch.tv/oauth2/token", params={
        "client_id": TWITCH_ID, "client_secret": TWITCH_SECRET,
        "grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def twitch_vods(token):
    h = {"Client-ID": TWITCH_ID, "Authorization": f"Bearer {token}"}
    u = requests.get("https://api.twitch.tv/helix/users",
                     params={"login": TWITCH_CHANNEL}, headers=h, timeout=30)
    u.raise_for_status()
    users = u.json().get("data", [])
    if not users:
        sys.exit(f"Twitch channel '{TWITCH_CHANNEL}' not found")
    uid = users[0]["id"]

    out, cursor = [], None
    while True:
        params = {"user_id": uid, "type": "archive", "first": 100}
        if cursor:
            params["after"] = cursor
        r = requests.get("https://api.twitch.tv/helix/videos",
                         params=params, headers=h, timeout=30)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("data", []))
        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            return out


def parse_duration(s):
    """Twitch gives '3h21m9s'. Return seconds."""
    total, num = 0, ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            total += int(num or 0) * {"h": 3600, "m": 60, "s": 1}.get(ch, 0)
            num = ""
    return total


def youtube():
    creds = Credentials(
        None, refresh_token=YT_REFRESH, client_id=YT_ID, client_secret=YT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


PLAYLIST_TITLE = "VoD Archive"


def get_or_create_playlist(yt):
    """Find the archive playlist, or make it. Returns its id, or None if the
    token predates the playlist scope - in which case uploads still work and
    only the playlist step is skipped."""
    try:
        req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
        while req is not None:
            res = req.execute()
            for p in res.get("items", []):
                if p["snippet"]["title"].strip().lower() == PLAYLIST_TITLE.lower():
                    log(f"using existing playlist '{PLAYLIST_TITLE}' ({p['id']})")
                    return p["id"]
            req = yt.playlists().list_next(req, res)

        created = yt.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": PLAYLIST_TITLE,
                    "description": "Twitch VODs archived automatically before Twitch deletes them.",
                },
                # Private, to match the videos. A public playlist of private
                # videos would show as a wall of unavailable entries anyway.
                "status": {"privacyStatus": "private"},
            },
        ).execute()
        log(f"created playlist '{PLAYLIST_TITLE}' ({created['id']})")
        return created["id"]
    except Exception as exc:  # noqa: BLE001
        log(f"playlist unavailable ({exc}) - uploads will still work, just not grouped")
        return None


def add_to_playlist(yt, playlist_id, video_id):
    if not playlist_id:
        return False
    try:
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }},
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - a playlist failure must not fail the archive
        log(f"  could not add to playlist: {exc}")
        return False


def download(vod, path):
    cmd = ["yt-dlp", "-f", "best", "--no-progress", "--no-warnings",
           "-o", path, vod["url"]]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"  yt-dlp failed: {res.stderr[-400:]}")
        return False
    return os.path.exists(path)


def upload(yt, vod, path):
    body = {
        "snippet": {
            "title": f"[{vod['created_at'][:10]}] {vod['title']}"[:100],
            "description": (
                f"Twitch VOD archive.\n\n"
                f"Streamed: {vod['created_at']}\n"
                f"Duration: {vod['duration']}\n"
                f"Original: {vod['url']}\n"
                f"Twitch id: {vod['id']}\n"
            )[:5000],
            # 20 = Gaming. Avoids YouTube guessing.
            "categoryId": "20",
        },
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(path, chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response, tries = None, 0
    while response is None:
        try:
            _, response = req.next_chunk()
        except Exception as exc:  # noqa: BLE001 - resumable uploads fail transiently
            tries += 1
            if tries > 5:
                raise
            log(f"  chunk failed ({exc}), retry {tries}/5")
            time.sleep(2 ** tries)
    return response["id"]


def notify(vod, video_id, size):
    if not (WORKER and WORKER_TOKEN):
        return
    try:
        requests.post(f"{WORKER}/vod", timeout=20,
            headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
            json={
                "who": WHO,
                "title": vod["title"],
                "game": vod.get("game_name") or "",
                "duration": parse_duration(vod["duration"]),
                "bytes": size,
                "streamed_at": int(datetime.fromisoformat(
                    vod["created_at"].replace("Z", "+00:00")).timestamp()),
                "url": f"https://youtu.be/{video_id}",
            })
    except Exception as exc:  # noqa: BLE001 - a failed card must not fail the archive
        log(f"  card post failed (upload was fine): {exc}")


def main():
    done = load_manifest()
    done_ids = {d["twitch_id"] if isinstance(d, dict) else d for d in done}

    vods = twitch_vods(twitch_token())
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MIN_AGE_MINUTES)

    pending = []
    for v in vods:
        if v["id"] in done_ids:
            continue
        created = datetime.fromisoformat(v["created_at"].replace("Z", "+00:00"))
        if created > cutoff:
            log(f"skip {v['id']}: too fresh, Twitch may still be writing it")
            continue
        if v.get("status") == "recording" or v.get("thumbnail_url", "").find("404_processing") != -1:
            log(f"skip {v['id']}: still recording")
            continue
        pending.append(v)

    pending.sort(key=lambda v: v["created_at"])  # oldest first: they expire first
    log(f"{len(vods)} VODs on Twitch, {len(done_ids)} already archived, {len(pending)} to do")

    if not pending:
        log("nothing to archive")
        return

    yt = youtube()
    playlist_id = get_or_create_playlist(yt)
    used = 0

    for v in pending:
        if time.time() > DEADLINE:
            log("stopping: approaching job time limit, rest go next run")
            break
        if used > MAX_BYTES_PER_RUN:
            log("stopping: disk budget for this run used, rest go next run")
            break

        path = os.path.join(HERE, f"_tmp_{v['id']}.mp4")
        log(f"\n=== {v['id']}  {v['created_at'][:10]}  {v['duration']}  {v['title'][:60]}")
        try:
            if not download(v, path):
                continue
            size = os.path.getsize(path)
            log(f"  downloaded {size/1e9:.1f} GB, uploading")
            vid = upload(yt, v, path)
            log(f"  uploaded as {vid} (private)")

            if add_to_playlist(yt, playlist_id, vid):
                log(f"  added to '{PLAYLIST_TITLE}'")

            done.append({"twitch_id": v["id"], "youtube_id": vid,
                         "title": v["title"], "archived": datetime.now(timezone.utc).isoformat()})
            save_manifest(done)
            notify(v, vid, size)
            used += size
        finally:
            if os.path.exists(path):
                os.remove(path)

    # Tell the workflow whether to run itself again. Continuing only when
    # progress was actually made means a persistent failure stops the loop
    # instead of re-triggering forever.
    archived_this_run = len(done) - len(done_ids)
    remaining = len(pending) - archived_this_run
    log(f"\narchived {archived_this_run} this run, {remaining} still outstanding")

    step_out = os.environ.get("GITHUB_OUTPUT")
    if step_out:
        with open(step_out, "a", encoding="utf-8") as fh:
            fh.write(f"archived={archived_this_run}\n")
            fh.write(f"remaining={remaining}\n")
            fh.write(f"continue={'yes' if remaining > 0 and archived_this_run > 0 else 'no'}\n")

    log("done")


if __name__ == "__main__":
    main()
