#!/usr/bin/env python3
"""Sync the complete YurrMom.Com song preview catalog onto `/mnt/ssd/media/box2-music/`.

Discovers all released YurrMom.Com albums & singles via the public iTunes / Apple Music
catalog API (plus Spotify's top-tracks embed), downloads high-bitrate preview clips for
every track not yet on disk, applies smooth broadcast fade-in / fade-out envelopes, and
names files `YurrMom.Com - <Title>.mp3` for the live Now Playing tab.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

ARTIST_TERM = "YurrMom.Com"
SPOTIFY_ARTIST_ID = "6C2jJcvEiE7iXnVY8H11LX"
DEFAULT_OUT_DIR = Path("/mnt/ssd/media/box2-music")


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def discover_catalog():
    """Return deduplicated list of dicts: {'title': str, 'album': str, 'preview_url': str}."""
    by_key = {}

    # 1. Discover exact artistId(s) for YurrMom.Com
    artist_ids = set()
    search_data = _fetch_json(
        f"https://itunes.apple.com/search?term={urllib.parse.quote(ARTIST_TERM)}&entity=song&limit=200"
    )
    for item in search_data.get("results", []):
        aname = str(item.get("artistName", ""))
        if "yurrmom" not in aname.lower():
            continue
        if item.get("artistId"):
            artist_ids.add(int(item["artistId"]))
        title = str(item.get("trackName", "")).strip()
        prev = str(item.get("previewUrl", "")).strip()
        if title and prev:
            by_key[title.lower()] = {
                "title": title,
                "album": str(item.get("collectionName", "")).strip(),
                "preview_url": prev,
            }

    # 2. Query every album under each discovered artistId to catch deep-cut album tracks beyond 200 search cap
    for aid in sorted(artist_ids):
        try:
            alb_data = _fetch_json(f"https://itunes.apple.com/lookup?id={aid}&entity=album&limit=200")
            collection_ids = [
                int(r["collectionId"])
                for r in alb_data.get("results", [])
                if r.get("wrapperType") == "collection" and r.get("collectionId")
            ]
            # Batch lookup up to 20 collectionIds per request
            for i in range(0, len(collection_ids), 15):
                batch_ids = ",".join(str(cid) for cid in collection_ids[i:i + 15])
                tr_data = _fetch_json(f"https://itunes.apple.com/lookup?id={batch_ids}&entity=song&limit=200")
                for item in tr_data.get("results", []):
                    if item.get("wrapperType") != "track":
                        continue
                    if "yurrmom" not in str(item.get("artistName", "")).lower():
                        continue
                    title = str(item.get("trackName", "")).strip()
                    prev = str(item.get("previewUrl", "")).strip()
                    if title and prev and title.lower() not in by_key:
                        by_key[title.lower()] = {
                            "title": title,
                            "album": str(item.get("collectionName", "")).strip(),
                            "preview_url": prev,
                        }
        except Exception as exc:
            print(f"Catalog album lookup warning: {exc}", flush=True)

    return list(by_key.values())


def sanitize_filename_title(title: str) -> str:
    # Normalize non-ASCII punctuation to clean ASCII for crisp OpenCV/PIL display
    t = (
        title.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", "-")
        .replace("–", "-")
        .replace("/", "-")
    )
    t = re.sub(r"[^A-Za-z0-9 .,!?'()&#$+-]+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:90] or "Untitled"


def _download_and_encode_one(entry: dict, out_dir: Path):
    safe_title = sanitize_filename_title(entry["title"])
    dest = out_dir / f"YurrMom.Com - {safe_title}.mp3"
    if dest.exists() and dest.stat().st_size > 20_000:
        return ("skipped", dest.name)

    fd, raw_tmp = tempfile.mkstemp(suffix=".m4a")
    os.close(fd)
    fd2, mp3_tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".mp3", dir=str(out_dir))
    os.close(fd2)
    try:
        urllib.request.urlretrieve(entry["preview_url"], raw_tmp)
        pr = subprocess.run(
            ["/usr/bin/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", raw_tmp],
            capture_output=True, text=True, timeout=10,
        )
        dur = float(pr.stdout.strip() or 29.5)
        fo_start = max(1.0, dur - 1.6)
        subprocess.run(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-i", raw_tmp,
                "-af", f"afade=t=in:st=0:d=0.7,afade=t=out:st={fo_start:.2f}:d=1.6",
                "-ac", "2", "-ar", "48000",
                "-c:a", "libmp3lame", "-b:a", "192k",
                mp3_tmp,
            ],
            check=True,
            timeout=30,
        )
        os.chmod(mp3_tmp, 0o664)
        os.replace(mp3_tmp, dest)
        return ("added", dest.name)
    except Exception as exc:
        if os.path.exists(mp3_tmp):
            try:
                os.unlink(mp3_tmp)
            except OSError:
                pass
        return ("error", f"{safe_title}: {exc}")
    finally:
        if os.path.exists(raw_tmp):
            try:
                os.unlink(raw_tmp)
            except OSError:
                pass


def sync_catalog(out_dir: Path = DEFAULT_OUT_DIR, workers: int = 6):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Remove old numbered 01_..10_ duplicates once unnumbered canonical files are synced
    entries = discover_catalog()
    added = 0
    skipped = 0
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_download_and_encode_one, e, out_dir) for e in entries]
        for f in concurrent.futures.as_completed(futs):
            status, info = f.result()
            if status == "added":
                added += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors.append(info)

    for old_num in out_dir.glob("[0-9][0-9]_YurrMom.Com - *.mp3"):
        unnum = out_dir / re.sub(r"^\d{2}_", "", old_num.name)
        if unnum.exists():
            try:
                old_num.unlink()
            except OSError:
                pass

    total_files = len([p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"])
    return {
        "discovered_in_catalog": len(entries),
        "newly_added": added,
        "already_present": skipped,
        "total_mp3s_ready": total_files,
        "approx_non_repeating_minutes": round(total_files * 0.5, 1),
        "errors": errors[:5],
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_DIR
    summary = sync_catalog(target)
    print(json.dumps(summary, indent=2))
