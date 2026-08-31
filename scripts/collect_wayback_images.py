#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{original}"
TARGETS = [
    "www.alpha-net.ne.jp/users2/usarabi8/*",
    "ashitaganbaru.sakura.ne.jp/*",
    "honya.uunyan.com/old_diary/*",
]
OUT_DIR = Path("wayback_output")
IMAGES_DIR = OUT_DIR / "images"
USER_AGENT = "Mozilla/5.0 (compatible; personal-archive-recovery/1.0)"
RETRIES = 5


def request_bytes(url: str, timeout: int = 60) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"request failed after {RETRIES} attempts: {url}: {last_error}")


def fetch_cdx(target: str) -> list[dict[str, str]]:
    params = [
        ("url", target),
        ("output", "json"),
        ("fl", "timestamp,original,mimetype,digest,statuscode"),
        ("filter", "statuscode:200"),
        ("filter", "mimetype:image/.*"),
        ("collapse", "digest"),
    ]
    url = CDX_ENDPOINT + "?" + urllib.parse.urlencode(params)
    raw, _ = request_bytes(url, timeout=120)
    rows = json.loads(raw.decode("utf-8", errors="replace"))
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, row)) for row in rows[1:] if len(row) == len(header)]


def clean_name(value: str) -> str:
    value = urllib.parse.unquote(value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:100] or "image"


def extension_for(data: bytes, mime: str, original: str) -> str:
    low = data[:512].lstrip().lower()
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif"
    if data.startswith(b"\x00\x00\x01\x00"):
        return ".ico"
    if b"<svg" in low:
        return ".svg"
    guessed = Path(urllib.parse.urlparse(original).path).suffix.lower()
    if guessed in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".svg"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    mime_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
        "image/x-icon": ".ico",
        "image/svg+xml": ".svg",
    }
    return mime_map.get(mime.split(";", 1)[0].lower(), ".img")


def looks_like_image(data: bytes, mime: str, original: str) -> bool:
    ext = extension_for(data, mime, original)
    if ext != ".img":
        return True
    return False


def main() -> int:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    cdx_rows: list[dict[str, str]] = []
    query_errors: list[dict[str, str]] = []

    for target in TARGETS:
        print(f"CDX: {target}", flush=True)
        try:
            rows = fetch_cdx(target)
            print(f"  {len(rows)} archived image records", flush=True)
            for row in rows:
                row["target"] = target
            cdx_rows.extend(rows)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr, flush=True)
            query_errors.append({"target": target, "error": str(exc)})

    # Deduplicate capture records before downloading.
    unique_capture: dict[tuple[str, str], dict[str, str]] = {}
    for row in cdx_rows:
        key = (row.get("timestamp", ""), row.get("original", ""))
        unique_capture[key] = row
    records = list(unique_capture.values())
    print(f"Total unique captures to try: {len(records)}", flush=True)

    hash_to_file: dict[str, str] = {}
    manifest: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    for i, row in enumerate(records, start=1):
        timestamp = row.get("timestamp", "")
        original = row.get("original", "")
        archive_url = WAYBACK_RAW.format(timestamp=timestamp, original=original)
        try:
            data, content_type = request_bytes(archive_url, timeout=90)
            if not data or not looks_like_image(data, content_type or row.get("mimetype", ""), original):
                raise RuntimeError(f"response is not a recognized image ({content_type or 'unknown type'})")
            sha = hashlib.sha256(data).hexdigest()
            if sha in hash_to_file:
                saved = hash_to_file[sha]
                duplicate = "yes"
            else:
                path_name = Path(urllib.parse.urlparse(original).path).name
                stem = clean_name(Path(path_name).stem or "image")
                ext = extension_for(data, content_type or row.get("mimetype", ""), original)
                saved = f"images/{sha[:16]}_{stem}{ext}"
                (OUT_DIR / saved).write_bytes(data)
                hash_to_file[sha] = saved
                duplicate = "no"
            manifest.append({
                "target": row.get("target", ""),
                "timestamp": timestamp,
                "original_url": original,
                "wayback_url": archive_url,
                "cdx_mimetype": row.get("mimetype", ""),
                "response_content_type": content_type,
                "sha256": sha,
                "saved_file": saved,
                "duplicate_content": duplicate,
                "bytes": str(len(data)),
            })
        except Exception as exc:
            failures.append({
                "target": row.get("target", ""),
                "timestamp": timestamp,
                "original_url": original,
                "wayback_url": archive_url,
                "error": str(exc),
            })
        if i % 50 == 0 or i == len(records):
            print(f"Progress {i}/{len(records)} | unique images {len(hash_to_file)} | failures {len(failures)}", flush=True)

    manifest_path = OUT_DIR / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["target", "timestamp", "original_url", "wayback_url", "cdx_mimetype", "response_content_type", "sha256", "saved_file", "duplicate_content", "bytes"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest)

    failures_path = OUT_DIR / "failures.csv"
    with failures_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["target", "timestamp", "original_url", "wayback_url", "error"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(failures)

    query_errors_path = OUT_DIR / "query_errors.csv"
    with query_errors_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["target", "error"])
        writer.writeheader()
        writer.writerows(query_errors)

    summary = {
        "targets": TARGETS,
        "cdx_records": len(cdx_rows),
        "unique_capture_records": len(records),
        "downloaded_capture_records": len(manifest),
        "unique_images": len(hash_to_file),
        "download_failures": len(failures),
        "query_errors": len(query_errors),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = Path("wayback_images.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(OUT_DIR))

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"Created {zip_path} ({zip_path.stat().st_size} bytes)", flush=True)

    # Fail only when no CDX query succeeded at all. Partial archive gaps are expected.
    if len(query_errors) == len(TARGETS):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
