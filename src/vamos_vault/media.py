from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


MEDIA_EXTENSIONS = {
    ".3gp",
    ".aac",
    ".aif",
    ".aiff",
    ".arw",
    ".avi",
    ".braw",
    ".cr2",
    ".cr3",
    ".dng",
    ".flac",
    ".heic",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mts",
    ".mxf",
    ".nef",
    ".png",
    ".raf",
    ".wav",
    ".webm",
}


@dataclass
class MediaProbe:
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS


def iter_media(paths: list[Path], *, recursive: bool = True) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file() and is_media_file(path):
            found.append(path)
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            found.extend(item for item in iterator if is_media_file(item))
    return sorted(set(found))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def probe_media(path: Path) -> MediaProbe:
    if shutil.which("ffprobe") is None:
        return MediaProbe()

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError):
        return MediaProbe()

    data = json.loads(result.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    duration = (data.get("format") or {}).get("duration")
    return MediaProbe(
        duration_seconds=float(duration) if duration else None,
        width=stream.get("width"),
        height=stream.get("height"),
        codec=stream.get("codec_name"),
    )


def normalize_tags(value: str | None) -> str | None:
    if not value:
        return None
    tags = []
    for item in value.replace("#", "").split(","):
        tag = item.strip().lower().replace(" ", "-")
        if tag and tag not in tags:
            tags.append(tag)
    return ",".join(tags) if tags else None


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_caption(
    *,
    filename: str,
    size_bytes: int,
    sha256: str,
    asset_kind: str = "original",
    project: str | None = None,
    shoot_date: str | None = None,
    camera: str | None = None,
    lens: str | None = None,
    tags: str | None = None,
    scene: str | None = None,
    location: str | None = None,
    people: str | None = None,
    rights: str | None = None,
    rating: int | None = None,
    favorite: bool = False,
    youtube_status: str | None = None,
    notes: str | None = None,
    duration_seconds: float | None = None,
    limit: int = 1024,
) -> str:
    lines = [
        "VAMOS VAULT",
        f"File: {filename}",
        f"Size: {format_bytes(size_bytes)}",
    ]
    if duration_seconds:
        lines.append(f"Duration: {format_duration(duration_seconds)}")
    if project:
        lines.append(f"Project: {project}")
    if shoot_date:
        lines.append(f"Shoot date: {shoot_date}")
    if asset_kind:
        lines.append(f"Kind: {asset_kind}")
    if scene:
        lines.append(f"Scene: {scene}")
    if location:
        lines.append(f"Location: {location}")
    camera_line = " | ".join(part for part in [camera, lens] if part)
    if camera_line:
        lines.append(f"Kit: {camera_line}")
    if people:
        lines.append(f"People: {people}")
    if rights:
        lines.append(f"Rights: {rights}")
    if rating:
        lines.append(f"Rating: {rating}/5")
    if favorite:
        lines.append("Favorite: yes")
    if youtube_status:
        lines.append(f"YouTube: {youtube_status}")
    if tags:
        lines.append(f"Tags: {tags}")
    if notes:
        lines.append(f"Notes: {notes}")
    lines.append(f"SHA256: {sha256[:16]}")

    caption = "\n".join(lines)
    if len(caption) <= limit:
        return caption
    suffix = f"\nSHA256: {sha256[:16]}"
    trimmed = caption[: max(0, limit - len(suffix) - 3)].rstrip()
    return f"{trimmed}...{suffix}"
